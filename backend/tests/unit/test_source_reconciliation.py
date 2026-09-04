from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.services.source_reconciliation import (
    CanonicalReconciliationError,
    ReconciliationCandidate,
    guard_reconciled_source_selection,
    reconcile_candidates,
)
from app.services.canonical_financials import CanonicalSourceConflictError


SPEC_PATH = Path("docs/metric_facts_mapping_spec.yml")
PRD_PATH = Path("docs/prd/value-pilot-prd-v0.1.md")
NOW = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)


def _candidate(
    fact_id: int,
    *,
    source_type: str,
    value: str | None = "100",
    source_role: str | None = None,
    definition_basis: str = "as_filed",
    definition_id: str = "is.net_income",
    mapping_version: str = "canonical-financial-definitions-v1",
    source_mapping_version: str | None = None,
    metric_key: str = "is.net_income",
    period_type: str = "FY",
    period_end: date = date(2025, 12, 31),
    period_start: date | None = date(2025, 1, 1),
    duration_days: int | None = 365,
    fiscal_year: int | None = 2025,
    fiscal_quarter_ordinal: int | None = None,
    dimensions: str = "empty",
    unit: str = "currency",
    currency: str | None = "USD",
    fact_nature: str = "actual",
    known_at: datetime = NOW - timedelta(days=1),
    effective_at: datetime = NOW - timedelta(days=1),
    authorization_state: str = "authorized",
    is_current: bool = True,
    lineage_fact_ids: tuple[int, ...] = (),
) -> ReconciliationCandidate:
    return ReconciliationCandidate(
        fact_id=fact_id,
        stock_id=7,
        source_type=source_type,
        source_role=source_role or {
            "sec": "primary_as_filed_actual",
            "parsed": "value_line_adjusted",
            "manual": "user_manual_correction",
            "calculated": "deterministic_derived",
        }[source_type],
        source_identity=f"{source_type}:{fact_id}",
        metric_key=metric_key,
        definition_family="canonical:" + metric_key,
        definition_basis=definition_basis,
        definition_id=definition_id,
        mapping_version=mapping_version,
        source_mapping_version=source_mapping_version or f"{source_type}-map-v1",
        period_type=period_type,
        period_end_date=period_end,
        fiscal_year=fiscal_year,
        fiscal_quarter_ordinal=fiscal_quarter_ordinal,
        period_start_date=period_start,
        duration_days=duration_days,
        dimensions_identity=dimensions,
        unit=unit,
        currency=currency,
        fact_nature=fact_nature,
        value_numeric=Decimal(value) if value is not None else None,
        known_at=known_at,
        effective_at=effective_at,
        authorization_state=authorization_state,
        is_current=is_current,
        lineage_fact_ids=lineage_fact_ids,
    )


def test_mapping_and_prd_own_the_ft06_contract():
    spec = yaml.safe_load(SPEC_PATH.read_text())
    policy = spec["source_reconciliation"]["versions"][0]

    assert policy["id"] == "financial-source-reconciliation-v1"
    assert policy["status"] == "approved"
    assert policy["source_precedence"] == "none"
    assert policy["canonical_definition_version"] == (
        "canonical-financial-definitions-v1"
    )
    assert policy["source_mapping_identity_required"] is True
    assert policy["comparison_identity"]["align_before_variance"] == [
        "canonical_definition",
        "mapping_version",
        "fiscal_period_and_duration",
        "dimensions",
        "normalized_unit_and_scale",
        "monetary_currency",
        "fact_nature",
        "source_identity_and_authorization",
        "effective_time",
        "knowledge_cutoff",
    ]
    assert set(policy["outcomes"]) == {
        "match",
        "expected_definition_difference",
        "restatement",
        "mapping_conflict",
        "unresolved",
    }
    assert policy["consumer_gate"]["unresolved_conflict"] == "fail_closed"

    prd = PRD_PATH.read_text()
    assert "### H.10 Exact source reconciliation (FT-06)" in prd
    assert "comparison/audit projection" in prd
    assert "must not select a winning source" in prd.lower()
    assert "financial-source-reconciliation-v1" in prd


def test_reconciliation_is_order_independent_and_exact_match_is_decimal():
    sec = _candidate(20, source_type="sec", value="100.000000000000")
    value_line = _candidate(
        10,
        source_type="parsed",
        value="100.0000004",
        definition_basis="adjusted",
    )

    first = reconcile_candidates([sec, value_line], knowledge_cutoff=NOW)
    second = reconcile_candidates([value_line, sec], knowledge_cutoff=NOW)

    assert first == second
    assert first["status"] == "complete"
    assert first["items"][0]["status"] == "expected_definition_difference"
    assert first["items"][0]["reason_code"] == "as_filed_vs_adjusted"
    assert first["items"][0]["absolute_variance"] == "0.0000004"
    assert first["items"][0]["fact_ids"] == [10, 20]
    assert first["report_digest"] == second["report_digest"]


def test_material_same_definition_disagreement_is_unresolved():
    result = reconcile_candidates(
        [
            _candidate(1, source_type="sec", value="100"),
            _candidate(
                2,
                source_type="parsed",
                value="130",
                definition_basis="as_filed",
            ),
        ],
        knowledge_cutoff=NOW,
    )

    assert result["items"][0]["status"] == "unresolved"
    assert result["items"][0]["reason_code"] == "material_value_difference"
    assert result["items"][0]["blocking"] is True


def test_equal_values_with_different_definitions_never_become_a_match():
    item = reconcile_candidates(
        [
            _candidate(1, source_type="sec", value="100"),
            _candidate(
                2,
                source_type="parsed",
                value="100",
                definition_basis="as_filed",
                definition_id="different.definition",
            ),
        ],
        knowledge_cutoff=NOW,
    )["items"][0]

    assert item["status"] == "mapping_conflict"
    assert item["reason_code"] == "definition_mismatch"
    assert item["absolute_variance"] is None
    assert item["blocking"] is True


def test_equal_values_with_aligned_definition_are_a_match():
    item = reconcile_candidates(
        [
            _candidate(1, source_type="sec", value="100"),
            _candidate(
                2,
                source_type="parsed",
                value="100.0000004",
                definition_basis="as_filed",
            ),
        ],
        knowledge_cutoff=NOW,
    )["items"][0]

    assert item["status"] == "match"
    assert item["reason_code"] == "within_review_tolerance"


def test_explicit_sec_and_value_line_definition_difference_is_not_hidden():
    result = reconcile_candidates(
        [
            _candidate(1, source_type="sec", value="100", definition_basis="as_filed"),
            _candidate(
                2,
                source_type="parsed",
                value="130",
                definition_basis="adjusted",
            ),
        ],
        knowledge_cutoff=NOW,
    )

    item = result["items"][0]
    assert item["status"] == "expected_definition_difference"
    assert item["reason_code"] == "as_filed_vs_adjusted"
    assert item["absolute_variance"] == "30"
    assert item["blocking"] is False


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        (
            {"period_end": date(2026, 1, 3), "fiscal_year": 2025},
            "period_mismatch",
        ),
        ({"dimensions": "segment:cloud"}, "dimensions_mismatch"),
        ({"unit": "shares", "currency": None}, "unit_mismatch"),
        ({"currency": "EUR"}, "currency_mismatch"),
        ({"mapping_version": "unknown-map"}, "mapping_version_mismatch"),
    ],
)
def test_alignment_mismatch_blocks_before_variance(override, reason):
    left = _candidate(1, source_type="sec")
    right = _candidate(2, source_type="parsed", definition_basis="as_filed", **override)

    item = reconcile_candidates([left, right], knowledge_cutoff=NOW)["items"][0]

    assert item["status"] == "mapping_conflict"
    assert item["reason_code"] == reason
    assert item["absolute_variance"] is None
    assert item["blocking"] is True


def test_actual_estimate_and_manual_roles_are_not_silently_interchangeable():
    actual_vs_estimate = reconcile_candidates(
        [
            _candidate(1, source_type="sec"),
            _candidate(
                2,
                source_type="parsed",
                fact_nature="estimate",
                definition_basis="adjusted",
            ),
        ],
        knowledge_cutoff=NOW,
    )["items"][0]
    assert actual_vs_estimate["status"] == "expected_definition_difference"
    assert actual_vs_estimate["reason_code"] == "actual_vs_estimate"
    assert actual_vs_estimate["absolute_variance"] is None

    manual = reconcile_candidates(
        [
            _candidate(1, source_type="sec"),
            _candidate(
                3,
                source_type="manual",
                value="95",
                fact_nature="manual",
                lineage_fact_ids=(1,),
            ),
        ],
        knowledge_cutoff=NOW,
    )["items"][0]
    assert manual["status"] == "expected_definition_difference"
    assert manual["reason_code"] == "explicit_manual_correction"
    assert manual["fact_ids"] == [1, 3]


def test_derived_fact_requires_exact_lineage_and_never_overwrites_inputs():
    missing_lineage = reconcile_candidates(
        [
            _candidate(1, source_type="sec"),
            _candidate(
                4,
                source_type="calculated",
                fact_nature="derived_actual",
                value="100",
            ),
        ],
        knowledge_cutoff=NOW,
    )["items"][0]
    assert missing_lineage["status"] == "unresolved"
    assert missing_lineage["reason_code"] == "derived_lineage_unavailable"

    with_lineage = reconcile_candidates(
        [
            _candidate(1, source_type="sec"),
            _candidate(
                4,
                source_type="calculated",
                fact_nature="derived_actual",
                value="100",
                lineage_fact_ids=(1,),
            ),
        ],
        knowledge_cutoff=NOW,
    )["items"][0]
    assert with_lineage["status"] == "expected_definition_difference"
    assert with_lineage["reason_code"] == "direct_vs_derived"


@pytest.mark.parametrize(
    ("source_type", "fact_nature", "reason_code"),
    [
        ("manual", "manual", "manual_lineage_unavailable"),
        ("calculated", "derived_actual", "derived_lineage_unavailable"),
    ],
)
def test_singleton_correction_or_derived_fact_requires_lineage(
    source_type, fact_nature, reason_code
):
    item = reconcile_candidates(
        [_candidate(1, source_type=source_type, fact_nature=fact_nature)],
        knowledge_cutoff=NOW,
    )["items"][0]

    assert item["status"] == "unresolved"
    assert item["reason_code"] == reason_code
    assert item["blocking"] is True


def test_restatement_duplicates_missing_and_cutoff_are_typed():
    restatement = reconcile_candidates(
        [
            _candidate(1, source_type="sec", value="90", is_current=False),
            _candidate(2, source_type="sec", value="100", is_current=True),
        ],
        knowledge_cutoff=NOW,
    )["items"][0]
    assert restatement["status"] == "restatement"
    assert restatement["reason_code"] == "source_value_superseded"

    duplicate = reconcile_candidates(
        [
            _candidate(1, source_type="parsed"),
            _candidate(2, source_type="parsed"),
        ],
        knowledge_cutoff=NOW,
    )["items"][0]
    assert duplicate["status"] == "unresolved"
    assert duplicate["reason_code"] == "ambiguous_current_duplicate"

    missing = reconcile_candidates(
        [_candidate(1, source_type="sec")], knowledge_cutoff=NOW
    )["items"][0]
    assert missing["status"] == "unresolved"
    assert missing["reason_code"] == "single_source_only"
    assert missing["blocking"] is False

    excluded = reconcile_candidates(
        [
            _candidate(1, source_type="sec"),
            _candidate(
                2,
                source_type="parsed",
                known_at=NOW + timedelta(seconds=1),
            ),
            _candidate(
                3,
                source_type="manual",
                authorization_state="unauthorized",
            ),
        ],
        knowledge_cutoff=NOW,
    )
    assert excluded["eligible_fact_ids"] == [1]
    assert {row["reason_code"] for row in excluded["excluded"]} == {
        "fact_known_after_cutoff",
        "source_unauthorized",
    }


def test_selected_source_cannot_bypass_blocking_reconciliation():
    facts = [
        _candidate(1, source_type="sec", value="100"),
        _candidate(
            2,
            source_type="parsed",
            value="130",
            definition_basis="as_filed",
        ),
    ]

    with pytest.raises(CanonicalReconciliationError) as raised:
        guard_reconciled_source_selection(
            facts,
            consumer="formula",
            knowledge_cutoff=NOW,
            selected_source_type="sec",
        )

    assert raised.value.code == "unresolved_source_reconciliation"
    assert raised.value.blocking_items[0]["reason_code"] == "material_value_difference"

    expected_difference = [
        facts[0],
        _candidate(
            2,
            source_type="parsed",
            value="130",
            definition_basis="adjusted",
        ),
    ]
    assert guard_reconciled_source_selection(
        expected_difference,
        consumer="formula",
        knowledge_cutoff=NOW,
        selected_source_type="sec",
    ) == [expected_difference[0]]


def test_selected_source_cannot_bypass_fiscal_endpoint_mismatch():
    facts = [
        _candidate(1, source_type="sec"),
        _candidate(
            2,
            source_type="parsed",
            definition_basis="as_filed",
            period_end=date(2026, 1, 3),
            fiscal_year=2025,
        ),
    ]

    with pytest.raises(CanonicalReconciliationError) as raised:
        guard_reconciled_source_selection(
            facts,
            consumer="formula",
            knowledge_cutoff=NOW,
            selected_source_type="sec",
        )

    assert raised.value.blocking_items[0]["reason_code"] == "period_mismatch"


def test_disjoint_single_source_slots_remain_legal_without_global_precedence():
    facts = [
        _candidate(1, source_type="sec", metric_key="is.revenue"),
        _candidate(2, source_type="parsed", metric_key="is.net_income"),
    ]

    assert guard_reconciled_source_selection(
        facts,
        consumer="formula",
        knowledge_cutoff=NOW,
    ) == facts


@pytest.mark.parametrize(
    ("authorization_state", "reason_code"),
    [("retired", "source_retired"), ("revoked", "source_revoked")],
)
def test_retired_and_revoked_sources_are_distinct_typed_exclusions(
    authorization_state, reason_code
):
    report = reconcile_candidates(
        [
            _candidate(
                1,
                source_type="parsed",
                authorization_state=authorization_state,
            )
        ],
        knowledge_cutoff=NOW,
    )

    assert report["eligible_fact_ids"] == []
    assert report["excluded"][0]["reason_code"] == reason_code


def test_match_never_becomes_query_order_or_newest_row_precedence():
    facts = [
        _candidate(9, source_type="sec", value="100"),
        _candidate(
            99,
            source_type="parsed",
            value="100",
            definition_basis="adjusted",
        ),
    ]

    with pytest.raises(CanonicalSourceConflictError) as raised:
        guard_reconciled_source_selection(
            reversed(facts),
            consumer="screener",
            knowledge_cutoff=NOW,
        )

    assert raised.value.source_types == ("parsed", "sec")


def test_manual_correction_cannot_hide_conflict_between_other_sources():
    result = reconcile_candidates(
        [
            _candidate(1, source_type="sec", value="100"),
            _candidate(
                2,
                source_type="parsed",
                value="130",
                definition_basis="as_filed",
            ),
            _candidate(
                3,
                source_type="manual",
                value="125",
                fact_nature="manual",
                lineage_fact_ids=(2,),
            ),
        ],
        knowledge_cutoff=NOW,
    )

    assert len(result["items"]) == 3
    assert any(
        item["reason_code"] == "material_value_difference" and item["blocking"]
        for item in result["items"]
    )
