from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

from app.acceptance.financial_truth_gold_set import (
    GoldSetValidationError,
    expected_completed_fiscal_years,
    load_and_validate_gold_set,
    validate_gold_set,
)
from app.cli import sec_financials as sec_financials_cli


MANIFEST = Path("/code/docs/acceptance/financial_truth_beta_gold_set.yml")


def _data() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_locked_manifest_satisfies_ft00_protocol() -> None:
    report = load_and_validate_gold_set(MANIFEST)

    assert report.case_count == 24
    assert report.distinct_economic_issuers == 24
    assert report.primary_strata == {
        "ordinary_us_operating": 6,
        "regulated_financial": 3,
        "insurer": 3,
        "reit": 3,
        "high_sbc_or_acquisitive": 3,
        "cyclical_or_commodity": 3,
        "foreign_issuer": 3,
    }
    assert report.cross_cutting_counts["non_calendar_fiscal_year"] >= 3
    assert report.cross_cutting_counts["fifty_two_or_fifty_three_week"] >= 2
    assert report.cross_cutting_counts["adr_share_class_or_corporate_action"] >= 3
    assert report.cross_cutting_counts["filing_amendment_or_restatement"] >= 2
    assert report.cross_cutting_counts["non_usd_reporting_currency"] >= 2


def test_recently_available_issuer_uses_actual_completed_fy_denominator() -> None:
    data = _data()
    avgo = next(case for case in data["cases"] if case["case_id"] == "avgo-primary")

    assert expected_completed_fiscal_years(
        avgo, cutoff_at=data["cycle"]["cutoff_at"]
    ) == tuple(range(2018, 2026))


def test_manifest_rejects_unavailable_year_outside_locked_denominator() -> None:
    data = _data()
    avgo = next(case for case in data["cases"] if case["case_id"] == "avgo-primary")
    avgo["expected_history"]["unavailable_years"] = [
        {"fiscal_year": 2017, "disposition": "expected"}
    ]

    with pytest.raises(GoldSetValidationError, match="locked fiscal-year denominator"):
        validate_gold_set(data)


def test_coverage_command_uses_locked_cutoff_not_wall_clock(monkeypatch) -> None:
    data = _data()
    manifest = {**data, "cases": [deepcopy(data["cases"][0])]}
    captured: dict[str, object] = {}

    class _Rows:
        def all(self):
            return []

    class _Session:
        def scalar(self, _statement):
            return SimpleNamespace(id=1)

        def scalars(self, _statement):
            return _Rows()

        def close(self):
            return None

    monkeypatch.setattr(sec_financials_cli, "_gold_manifest", lambda: manifest)
    monkeypatch.setattr(
        sec_financials_cli,
        "_matching_stocks",
        lambda _db, ticker: [SimpleNamespace(id=1, ticker=ticker)],
    )
    monkeypatch.setattr(sec_financials_cli, "SessionLocal", _Session)

    def _evidence(_db, *, stock_id, cutoff):
        captured["stock_id"] = stock_id
        captured["cutoff"] = cutoff
        return []

    monkeypatch.setattr(
        sec_financials_cli, "select_sec_financial_evidence_as_of", _evidence
    )

    result = CliRunner().invoke(sec_financials_cli.app, ["coverage-gold-set"])

    assert result.exit_code == 2
    assert captured["stock_id"] == 1
    assert captured["cutoff"].isoformat() == "2026-08-26T23:59:59+00:00"


@pytest.mark.parametrize("field", ["po", "reviewer"])
def test_manifest_rejects_missing_approval(field: str) -> None:
    data = _data()
    data["cycle"]["approvals"].pop(field)

    with pytest.raises(GoldSetValidationError, match=field):
        validate_gold_set(data)


def test_manifest_rejects_selection_after_parser_results() -> None:
    data = _data()
    data["cycle"]["selection_policy"]["parser_results_consulted"] = True

    with pytest.raises(GoldSetValidationError, match="parser results"):
        validate_gold_set(data)


def test_manifest_rejects_cutoff_after_lock_time() -> None:
    data = _data()
    data["cycle"]["cutoff_at"] = "2026-08-28T00:00:00Z"

    with pytest.raises(GoldSetValidationError, match="cutoff_at must not be after locked_at"):
        validate_gold_set(data)


def test_manifest_rejects_duplicate_issuer_and_listing() -> None:
    data = _data()
    duplicate = deepcopy(data["cases"][0])
    duplicate["case_id"] = "duplicate-case"
    data["cases"][-1] = duplicate

    with pytest.raises(GoldSetValidationError, match="economic issuer"):
        validate_gold_set(data)


def test_manifest_rejects_invalid_cik_and_missing_history_disposition() -> None:
    data = _data()
    data["cases"][0]["cik"] = "320193"
    data["cases"][0]["expected_history"].pop("unavailable_years")

    with pytest.raises(GoldSetValidationError) as exc:
        validate_gold_set(data)

    assert "10-digit CIK" in str(exc.value)
    assert "unavailable_years" in str(exc.value)


def test_manifest_rejects_cross_cutting_shortfall() -> None:
    data = _data()
    for case in data["cases"]:
        case["cross_cutting_tags"] = [
            tag
            for tag in case["cross_cutting_tags"]
            if tag != "filing_amendment_or_restatement"
        ]

    with pytest.raises(GoldSetValidationError, match="filing_amendment_or_restatement"):
        validate_gold_set(data)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("fiscal_year_end_mmdd",), "0231", "real month/day"),
        (("primary_listing", "mic"), "nasdaq", "mic is malformed"),
        (("primary_listing", "country"), "USA", "country is malformed"),
        (("primary_listing", "instrument_type"), "mystery", "unsupported"),
        (("primary_listing", "share_class"), "Class B", "share_class is malformed"),
    ],
)
def test_manifest_rejects_malformed_listing_and_calendar_fields(
    path: tuple[str, ...], value: str, message: str
) -> None:
    data = _data()
    target = data["cases"][0]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(GoldSetValidationError, match=message):
        validate_gold_set(data)
