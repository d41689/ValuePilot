from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services.sec_financial_mapping import CanonicalCandidate, CanonicalSlotAuthority, MappingResult, TypedDisposition
from app.services.sec_metric_publication import (
    PublicationRequest,
    VerifiedPublicationSource,
    _identity,
)


def request() -> PublicationRequest:
    source = VerifiedPublicationSource(
        11, 12, "0000000000-26-000001", "sec-xbrl-v2", "a" * 64,
        datetime(2026, 8, 31, tzinfo=timezone.utc),
    )
    return PublicationRequest(
        1, 2, "sec-us-gaap-v1", datetime(2026, 9, 1, tzinfo=timezone.utc),
        "latest-known-v1", (source,), MappingResult((), (), 0),
    )


def test_publication_replay_identity_is_exact_and_order_sensitive():
    base = request()
    run_id, digest = _identity(base)
    assert _identity(base) == (run_id, digest)
    assert _identity(replace(base, requested_cutoff=datetime(2026, 9, 2, tzinfo=timezone.utc)))[0] != run_id
    assert _identity(replace(base, mapping_version_id="other"))[0] != run_id
    changed_parser = replace(base.sources[0], parser_version="sec-xbrl-v3")
    assert _identity(replace(base, sources=(changed_parser,)))[0] != run_id
    changed_manifest = replace(base.sources[0], input_manifest_hash="b" * 64)
    assert _identity(replace(base, sources=(changed_manifest,)))[0] != run_id
    assert _identity(replace(base, amendment_policy="original-only-v1"))[0] != run_id
    second = replace(base.sources[0], parse_run_id=13, filing_id=14, accession_no="0000000000-26-000002")
    assert _identity(replace(base, sources=(base.sources[0], second)))[0] != _identity(replace(base, sources=(second, base.sources[0])))[0]


def _rich_request():
    base = request()
    candidate = CanonicalCandidate(
        "sec.revenue", "is.revenue", Decimal("10.25"), "currency", "USD", "Q",
        date(2026, 1, 1), date(2026, 3, 31), 2026, 1, "ctx", ({"axis": "member"},),
        1, date(2026, 1, 1), "filing-authority", base.requested_cutoff,
        (11,), (21,), (31,), "direct",
    )
    slot = CanonicalSlotAuthority(
        1, "is.revenue", "sec.revenue", "Q", date(2026, 1, 1), date(2026, 3, 31),
        "duration", 2026, 1, "ctx", ({"axis": "member"},), (11,), (21,), base.requested_cutoff,
    )
    disposition = TypedDisposition("unresolved_conflicting_candidates", (21,), "sec.revenue", "detail", slot)
    return replace(base, outcome=MappingResult((candidate,), (disposition,), 1))


def test_replay_identity_binds_every_candidate_material_field_without_repr():
    base = _rich_request()
    candidate = base.outcome.candidates[0]
    mutations = (
        replace(candidate, mapping_rule_id="other"), replace(candidate, metric_key="other"),
        replace(candidate, value=Decimal("10.26")), replace(candidate, unit="shares"),
        replace(candidate, currency="EUR"), replace(candidate, period_type="FY"),
        replace(candidate, period_start=date(2025, 12, 31)), replace(candidate, period_end=date(2026, 4, 1)),
        replace(candidate, fiscal_year=2025), replace(candidate, fiscal_quarter_ordinal=2),
        replace(candidate, context_id="other"), replace(candidate, dimensions=()),
        replace(candidate, stock_id=2), replace(candidate, fiscal_year_start=date(2025, 12, 31)),
        replace(candidate, filing_authority_id="other"), replace(candidate, publication_cutoff=datetime(2026, 9, 3, tzinfo=timezone.utc)),
        replace(candidate, parse_run_ids=(12,)), replace(candidate, raw_fact_ids=(22,)),
        replace(candidate, normalization_ids=(32,)), replace(candidate, derivation_kind="current_ytd_minus_prior_ytd"),
    )
    original = _identity(base)[0]
    for mutation in mutations:
        changed = replace(base, outcome=replace(base.outcome, candidates=(mutation,)))
        assert _identity(changed)[0] != original


def test_replay_identity_binds_disposition_slot_detail_and_truncation():
    base = _rich_request()
    disposition = base.outcome.dispositions[0]
    slot = disposition.slot
    mutations = (
        replace(disposition, reason="unresolved_value"), replace(disposition, raw_fact_ids=(22,)),
        replace(disposition, mapping_rule_id="other"), replace(disposition, detail="other"),
        replace(disposition, slot=replace(slot, period_basis="instant")),
        replace(disposition, slot=replace(slot, raw_fact_ids=(22,))),
        replace(disposition, slot=replace(slot, parse_run_ids=(12,))),
    )
    original = _identity(base)[0]
    for mutation in mutations:
        assert _identity(replace(base, outcome=replace(base.outcome, dispositions=(mutation,))))[0] != original
    assert _identity(replace(base, outcome=replace(base.outcome, truncated_decision_count=2)))[0] != original


def test_identity_normalizes_aware_datetimes_to_one_utc_instant_and_rejects_naive():
    base = request()
    same_instant = replace(base, requested_cutoff=base.requested_cutoff.astimezone(timezone(timedelta(hours=-5))))
    same_source = replace(base.sources[0], available_at=base.sources[0].available_at.astimezone(timezone(timedelta(hours=9))))
    assert _identity(same_instant) == _identity(base)
    assert _identity(replace(base, sources=(same_source,))) == _identity(base)
    assert _identity(replace(base, requested_cutoff=base.requested_cutoff + timedelta(microseconds=1)))[0] != _identity(base)[0]
    with pytest.raises(Exception, match="timezone-aware"):
        _identity(replace(base, requested_cutoff=datetime(2026, 9, 1)))
