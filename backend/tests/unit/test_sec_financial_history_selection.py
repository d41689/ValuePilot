from __future__ import annotations

from datetime import date, datetime, timezone
import json

import pytest

from app.edgar.parsers.financial_submissions import DiscoveredFinancialFiling
from app.services.sec_financial_ingestion import (
    FinancialHistoryTarget,
    SecFinancialIngestionError,
    _discover,
    _expected_completed_fiscal_years,
    _financially_useful_6k,
    _ContinuationAuthority,
)


CIK = "0000320193"
SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{CIK}.json"
CUTOFF = datetime(2026, 8, 26, 23, 59, 59, tzinfo=timezone.utc)


def _filing(
    *,
    sequence: int,
    form: str,
    report_date: str,
    accepted_at: str,
    description: str | None = None,
) -> dict[str, str | None]:
    year = int(report_date[:4])
    return {
        "accessionNumber": f"{CIK}-{year % 100:02d}-{sequence:06d}",
        "filingDate": accepted_at[:10],
        "reportDate": report_date,
        "acceptanceDateTime": accepted_at,
        "form": form,
        "primaryDocument": f"filing-{sequence}.htm",
        "primaryDocDescription": description or form,
    }


def _arrays(filings: list[dict[str, str | None]]) -> dict[str, list[str | None]]:
    keys = (
        "accessionNumber",
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "form",
        "primaryDocument",
        "primaryDocDescription",
    )
    return {key: [filing[key] for filing in filings] for key in keys}


class HistoryClient:
    def __init__(
        self,
        *,
        recent: list[dict[str, str | None]],
        historical: list[list[dict[str, str | None]]],
    ) -> None:
        references = [
            {"name": f"CIK{CIK}-submissions-{index:03d}.json"}
            for index in range(len(historical))
        ]
        self.responses = {
            SUBMISSIONS_URL: json.dumps(
                {
                    "cik": str(int(CIK)),
                    "name": "Fixture Issuer",
                    "fiscalYearEnd": "1231",
                    "filings": {
                        "recent": _arrays(recent),
                        "files": references,
                    },
                }
            ).encode()
        }
        for index, filings in enumerate(historical):
            url = (
                "https://data.sec.gov/submissions/"
                f"CIK{CIK}-submissions-{index:03d}.json"
            )
            self.responses[url] = json.dumps(_arrays(filings)).encode()
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        return self.responses[url]


def _target(
    *,
    filing_regime: str = "us_10k_10q",
    fiscal_year_end_mmdd: str = "1231",
    available_start_on: date = date(2015, 1, 1),
    cap: int = 10,
) -> FinancialHistoryTarget:
    return FinancialHistoryTarget(
        filing_regime=filing_regime,
        fiscal_year_end_mmdd=fiscal_year_end_mmdd,
        available_start_on=available_start_on,
        completed_fiscal_year_cap=cap,
        filing_selection_as_of=CUTOFF,
    )


def test_completed_fiscal_years_respect_noncalendar_cutoff_and_history_start() -> None:
    target = _target(
        fiscal_year_end_mmdd="0926",
        available_start_on=date(2021, 1, 1),
        cap=10,
    )

    assert _expected_completed_fiscal_years(target) == (2025, 2024, 2023, 2022, 2021)


def test_recurring_fiscal_year_end_rejects_february_29() -> None:
    with pytest.raises(
        SecFinancialIngestionError,
        match="0229 is unsupported for a recurring fiscal year end",
    ):
        _expected_completed_fiscal_years(_target(fiscal_year_end_mmdd="0229"))


def test_history_target_and_as_of_cutoff_cannot_diverge() -> None:
    with pytest.raises(
        SecFinancialIngestionError,
        match="history target cutoff must match filing_selection_as_of",
    ):
        _discover(
            HistoryClient(recent=[], historical=[]),
            CIK,
            max_filings=10,
            filing_selection_as_of=CUTOFF.replace(day=25),
            history_target=_target(),
        )


def test_invalid_main_period_metadata_cannot_satisfy_annual_coverage() -> None:
    invalid_main = _filing(
        sequence=100,
        form="10-K",
        report_date="2025-12-31",
        accepted_at="2026-02-15T12:00:00Z",
    )
    invalid_main["filingDate"] = "2025-12-30"
    clean_history = _filing(
        sequence=101,
        form="10-K",
        report_date="2025-12-31",
        accepted_at="2026-02-16T12:00:00Z",
    )
    client = HistoryClient(recent=[invalid_main], historical=[[clean_history]])

    result = _discover(
        client,
        CIK,
        max_filings=1,
        filing_selection_as_of=CUTOFF,
        history_target=_target(cap=1),
    )

    assert len(client.calls) == 2
    assert [item.accession_no for item in result.filings] == [
        clean_history["accessionNumber"]
    ]
    assert result.failures == (
        f"invalid_filing_period_metadata:{invalid_main['accessionNumber']}",
    )


def test_invalid_historical_report_after_acceptance_is_excluded_and_bounded() -> None:
    invalid_history = _filing(
        sequence=100,
        form="10-K",
        report_date="2026-02-16",
        accepted_at="2026-02-15T12:00:00Z",
    )
    invalid_history["filingDate"] = "2026-02-17"

    result = _discover(
        HistoryClient(recent=[], historical=[[invalid_history]]),
        CIK,
        max_filings=1,
        filing_selection_as_of=CUTOFF,
        history_target=_target(cap=1),
    )

    assert result.filings == ()
    assert result.failures[0] == (
        f"invalid_filing_period_metadata:{invalid_history['accessionNumber']}"
    )
    assert len(result.failures[0]) < 80
    assert result.failures[-1] == "annual_coverage_gap:2025"


def test_after_hours_acceptance_may_receive_next_business_day_filing_date() -> None:
    after_hours = _filing(
        sequence=100,
        form="10-K",
        report_date="2025-12-31",
        accepted_at="2026-02-15T22:00:00Z",
    )
    after_hours["filingDate"] = "2026-02-16"

    result = _discover(
        HistoryClient(recent=[after_hours], historical=[]),
        CIK,
        max_filings=1,
        filing_selection_as_of=CUTOFF,
        history_target=_target(cap=1),
    )

    assert [item.accession_no for item in result.filings] == [
        after_hours["accessionNumber"]
    ]
    assert result.failures == ()


def test_us_history_scans_for_ten_annuals_before_recent_quarters_consume_limit() -> None:
    recent = [
        _filing(
            sequence=index,
            form="10-Q",
            report_date=f"2026-0{quarter}-01",
            accepted_at=f"2026-0{quarter + 1}-15T12:00:00Z",
        )
        for index, quarter in enumerate((1, 2, 3), start=1)
    ]
    recent.append(
        _filing(
            sequence=100,
            form="10-K",
            report_date="2025-12-31",
            accepted_at="2026-02-15T12:00:00Z",
        )
    )
    historical = [[
        _filing(
            sequence=200 + year,
            form="10-K",
            report_date=f"{year}-12-31",
            accepted_at=f"{year + 1}-02-15T12:00:00Z",
        )
        for year in range(2016, 2025)
    ]]
    client = HistoryClient(recent=recent, historical=historical)

    result = _discover(
        client,
        CIK,
        max_filings=10,
        filing_selection_as_of=CUTOFF,
        history_target=_target(),
    )

    assert len(client.calls) == 2
    assert len(result.filings) == 10
    assert {item.form_type for item in result.filings} == {"10-K"}
    assert {item.report_date.year for item in result.filings if item.report_date} == set(
        range(2016, 2026)
    )
    assert result.failures == ()
    assert list(result.filings) == sorted(
        result.filings,
        key=lambda item: (item.accepted_at, item.accession_no),
        reverse=True,
    )


def test_history_supplemental_filings_do_not_predate_available_start() -> None:
    annual = _filing(
        sequence=100,
        form="10-K",
        report_date="2025-12-31",
        accepted_at="2026-02-15T12:00:00Z",
    )
    stale_quarter = _filing(
        sequence=101,
        form="10-Q",
        report_date="2013-03-31",
        accepted_at="2013-04-18T12:00:00Z",
    )

    result = _discover(
        HistoryClient(recent=[annual, stale_quarter], historical=[]),
        CIK,
        max_filings=2,
        filing_selection_as_of=CUTOFF,
        history_target=_target(cap=1, available_start_on=date(2015, 1, 1)),
    )

    assert [item.accession_no for item in result.filings] == [
        annual["accessionNumber"]
    ]


def test_foreign_history_keeps_annuals_and_only_financially_useful_6k() -> None:
    recent = [
        _filing(
            sequence=index,
            form="6-K",
            report_date="2026-06-30",
            accepted_at=f"2026-07-{index:02d}T12:00:00Z",
            description="Report of foreign private issuer",
        )
        for index in range(1, 16)
    ]
    recent.extend(
        [
            _filing(
                sequence=50,
                form="6-K",
                report_date="2026-06-30",
                accepted_at="2026-08-01T12:00:00Z",
                description="Interim financial results",
            ),
            _filing(
                sequence=51,
                form="6-K",
                report_date="2026-03-31",
                accepted_at="2026-05-01T12:00:00Z",
                description="Quarterly earnings release",
            ),
            _filing(
                sequence=100,
                form="20-F",
                report_date="2025-12-31",
                accepted_at="2026-03-01T12:00:00Z",
            ),
        ]
    )
    historical = [[
        _filing(
            sequence=200 + year,
            form="20-F",
            report_date=f"{year}-12-31",
            accepted_at=f"{year + 1}-03-01T12:00:00Z",
        )
        for year in range(2016, 2025)
    ]]
    client = HistoryClient(recent=recent, historical=historical)

    result = _discover(
        client,
        CIK,
        max_filings=12,
        filing_selection_as_of=CUTOFF,
        history_target=_target(filing_regime="foreign_20f_6k"),
    )

    assert sum(item.form_type == "20-F" for item in result.filings) == 10
    selected_6k = [item for item in result.filings if item.form_type == "6-K"]
    assert len(selected_6k) == 2
    assert {item.primary_doc_description for item in selected_6k} == {
        "Interim financial results",
        "Quarterly earnings release",
    }
    assert result.failures == ()


def test_history_scan_limit_and_missing_annual_year_are_both_typed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.sec_financial_ingestion.MAX_HISTORICAL_SUBMISSION_FILES", 1
    )
    recent = [
        _filing(
            sequence=100,
            form="10-K",
            report_date="2025-12-31",
            accepted_at="2026-02-15T12:00:00Z",
        )
    ]
    historical = [
        [
            _filing(
                sequence=101,
                form="10-K",
                report_date="2024-12-31",
                accepted_at="2025-02-15T12:00:00Z",
            )
        ],
        [
            _filing(
                sequence=102,
                form="10-K",
                report_date="2023-12-31",
                accepted_at="2024-02-15T12:00:00Z",
            )
        ],
    ]
    client = HistoryClient(recent=recent, historical=historical)

    result = _discover(
        client,
        CIK,
        max_filings=3,
        filing_selection_as_of=CUTOFF,
        history_target=_target(cap=3),
    )

    assert len(client.calls) == 2
    assert {item.report_date.year for item in result.filings if item.report_date} == {
        2024,
        2025,
    }
    assert result.failures == (
        "history_scan_limit_exceeded",
        "annual_coverage_gap:2023",
    )
    assert result.next_history_cursor is not None

    continuation_client = HistoryClient(recent=recent, historical=historical)
    continued = _discover(
        continuation_client,
        CIK,
        max_filings=3,
        filing_selection_as_of=CUTOFF,
        history_target=_target(cap=3),
        continuation=_ContinuationAuthority(
            id="fixture",
            main_content=client.responses[SUBMISSIONS_URL],
            main_sha256=result.main_sha256 or "",
            references=result.continuation_references,
            next_index=result.continuation_next_index or 0,
        ),
    )
    assert continuation_client.calls == [
        f"https://data.sec.gov/submissions/CIK{CIK}-submissions-001.json",
    ]
    assert {item.report_date.year for item in continued.filings if item.report_date} == {
        2023,
        2025,
    }
    assert continued.next_history_cursor is None


def test_annual_amendment_reserves_one_year_before_companion_filing() -> None:
    recent = [
        _filing(
            sequence=100,
            form="10-K",
            report_date="2025-12-31",
            accepted_at="2026-02-15T12:00:00Z",
        ),
        _filing(
            sequence=101,
            form="10-K/A",
            report_date="2025-12-31",
            accepted_at="2026-03-15T12:00:00Z",
        ),
    ]
    historical = [[
        _filing(
            sequence=200 + year,
            form="10-K",
            report_date=f"{year}-12-31",
            accepted_at=f"{year + 1}-02-15T12:00:00Z",
        )
        for year in range(2016, 2025)
    ]]

    result = _discover(
        HistoryClient(recent=recent, historical=historical),
        CIK,
        max_filings=10,
        filing_selection_as_of=CUTOFF,
        history_target=_target(),
    )

    assert len(result.filings) == 10
    assert {item.report_date.year for item in result.filings if item.report_date} == set(
        range(2016, 2026)
    )
    selected_2025 = [item for item in result.filings if item.report_date.year == 2025]
    assert [item.form_type for item in selected_2025] == ["10-K/A"]


def test_main_history_accession_conflict_is_excluded_and_typed() -> None:
    recent_2025 = _filing(
        sequence=100,
        form="10-K",
        report_date="2025-12-31",
        accepted_at="2026-02-15T12:00:00Z",
    )
    conflicting_2024 = dict(recent_2025)
    conflicting_2024["reportDate"] = "2024-12-31"
    historical_2024 = _filing(
        sequence=101,
        form="10-K",
        report_date="2024-12-31",
        accepted_at="2025-02-15T12:00:00Z",
    )

    result = _discover(
        HistoryClient(
            recent=[recent_2025],
            historical=[[conflicting_2024, historical_2024]],
        ),
        CIK,
        max_filings=2,
        filing_selection_as_of=CUTOFF,
        history_target=_target(cap=2),
    )

    assert [item.accession_no for item in result.filings] == [
        historical_2024["accessionNumber"]
    ]
    assert result.failures == (
        f"conflicting_filing_metadata:{recent_2025['accessionNumber']}",
        "annual_coverage_gap:2025",
    )


def test_history_history_accession_conflict_is_excluded_and_typed() -> None:
    historical_2025 = _filing(
        sequence=100,
        form="10-K",
        report_date="2025-12-31",
        accepted_at="2026-02-15T12:00:00Z",
    )
    conflicting_2024 = dict(historical_2025)
    conflicting_2024["reportDate"] = "2024-12-31"
    clean_2024 = _filing(
        sequence=101,
        form="10-K",
        report_date="2024-12-31",
        accepted_at="2025-02-15T12:00:00Z",
    )

    result = _discover(
        HistoryClient(
            recent=[],
            historical=[[historical_2025], [conflicting_2024, clean_2024]],
        ),
        CIK,
        max_filings=2,
        filing_selection_as_of=CUTOFF,
        history_target=_target(cap=2),
    )

    assert [item.accession_no for item in result.filings] == [
        clean_2024["accessionNumber"]
    ]
    assert result.failures == (
        f"conflicting_filing_metadata:{historical_2025['accessionNumber']}",
        "annual_coverage_gap:2025",
    )


def test_exact_duplicate_accession_is_canonicalized_deterministically() -> None:
    annual_2025 = _filing(
        sequence=100,
        form="10-K",
        report_date="2025-12-31",
        accepted_at="2026-02-15T12:00:00Z",
    )
    annual_2024 = _filing(
        sequence=101,
        form="10-K",
        report_date="2024-12-31",
        accepted_at="2025-02-15T12:00:00Z",
    )

    result = _discover(
        HistoryClient(
            recent=[annual_2025],
            historical=[[dict(annual_2025), annual_2024]],
        ),
        CIK,
        max_filings=2,
        filing_selection_as_of=CUTOFF,
        history_target=_target(cap=2),
    )

    assert len(result.filings) == 2
    assert len({item.accession_no for item in result.filings}) == 2
    assert result.failures == ()
    duplicate = next(
        item
        for item in result.filings
        if item.accession_no == annual_2025["accessionNumber"]
    )
    assert duplicate.submissions_source_url == SUBMISSIONS_URL


def test_oversize_invalid_accession_is_excluded_with_bounded_hashed_failure() -> None:
    malformed = _filing(
        sequence=100,
        form="10-K",
        report_date="2025-12-31",
        accepted_at="2026-02-15T12:00:00Z",
    )
    malformed["accessionNumber"] = "X" * 12_000
    conflicting = dict(malformed)
    conflicting["reportDate"] = "2024-12-31"

    result = _discover(
        HistoryClient(recent=[malformed, conflicting], historical=[]),
        CIK,
        max_filings=1,
        filing_selection_as_of=CUTOFF,
        history_target=_target(cap=1),
    )

    assert result.filings == ()
    assert len(result.failures[0]) < 80
    assert result.failures[0].startswith("invalid_filing_accession:sha256=")
    assert "X" not in result.failures[0]
    assert not any("conflicting_filing_metadata" in item for item in result.failures)
    assert result.failures[-1] == "annual_coverage_gap:2025"


def test_lone_surrogate_accession_is_excluded_with_bounded_hashed_failure() -> None:
    malformed = _filing(
        sequence=100,
        form="10-K",
        report_date="2025-12-31",
        accepted_at="2026-02-15T12:00:00Z",
    )
    malformed["accessionNumber"] = chr(0xD800)

    result = _discover(
        HistoryClient(recent=[malformed], historical=[]),
        CIK,
        max_filings=1,
        filing_selection_as_of=CUTOFF,
        history_target=_target(cap=1),
    )

    assert result.filings == ()
    assert len(result.failures[0]) < 80
    assert result.failures[0].startswith("invalid_filing_accession:sha256=")
    assert chr(0xD800) not in result.failures[0]
    assert result.failures[-1] == "annual_coverage_gap:2025"


@pytest.mark.parametrize(
    "description",
    [
        "Earnings release",
        "Earnings results",
        "Interim financial results",
        "Quarterly financial statements",
        "Annual financial report",
    ],
)
def test_6k_financial_result_descriptions_are_useful(description: str) -> None:
    assert _financially_useful_6k(_discovered_6k(description)) is True


@pytest.mark.parametrize(
    "description",
    [
        "Earnings call",
        "Earnings results conference call",
        "Financial results announcement",
        "Notice of annual financial results",
        "Conference call announcement",
        "Investor presentation announcement",
        "Notice of annual general meeting",
        "Report of foreign private issuer",
    ],
)
def test_6k_call_announcement_and_notice_descriptions_are_not_useful(
    description: str,
) -> None:
    assert _financially_useful_6k(_discovered_6k(description)) is False


def _discovered_6k(description: str) -> DiscoveredFinancialFiling:
    return DiscoveredFinancialFiling(
        accession_no=f"{CIK}-26-000001",
        form_type="6-K",
        filed_on=date(2026, 8, 1),
        report_date=date(2026, 6, 30),
        accepted_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        primary_document="foreign-issuer.htm",
        primary_doc_description=description,
        submissions_source_url=SUBMISSIONS_URL,
        discovery_payload_sha256="a" * 64,
    )
