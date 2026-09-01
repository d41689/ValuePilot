"""Pure deterministic SEC parser-v2 to canonical-candidate mapping.

This module consumes explicit immutable snapshots only. It performs no database,
network, retention, publication, or runtime-current-state reads.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping, Sequence

from app.services.numeric_persistence import persist_numeric_38_12


US_GAAP_URIS = tuple(
    [f"http://fasb.org/us-gaap/{year}-01-31" for year in range(2014, 2022)]
    + [f"http://fasb.org/us-gaap/{year}" for year in range(2022, 2027)]
)
DEI_URIS = (
    "http://xbrl.sec.gov/dei/2014-01-31", "http://xbrl.sec.gov/dei/2018-01-31",
    "http://xbrl.sec.gov/dei/2019-01-31", "http://xbrl.sec.gov/dei/2020-01-31",
    "http://xbrl.sec.gov/dei/2021", "http://xbrl.sec.gov/dei/2021q4",
    "http://xbrl.sec.gov/dei/2022", "http://xbrl.sec.gov/dei/2023",
    "http://xbrl.sec.gov/dei/2024", "http://xbrl.sec.gov/dei/2025",
    "http://xbrl.sec.gov/dei/2026",
)
ISO4217_URI = "http://www.xbrl.org/2003/iso4217"
XBRLI_URI = "http://www.xbrl.org/2003/instance"


@dataclass(frozen=True)
class ConceptRule:
    authority: str
    local_name: str
    priority: int


@dataclass(frozen=True)
class MappingRule:
    rule_id: str
    metric_key: str
    value_kind: str
    period_basis: str
    concepts: tuple[ConceptRule, ...]


@dataclass(frozen=True)
class MappingSnapshot:
    mapping_version_id: str
    spec_sha256: str
    known_at: datetime
    effective_at: datetime
    namespaces: Mapping[str, tuple[str, ...]]
    currency_codes: tuple[str, ...]
    rules: tuple[MappingRule, ...]


@dataclass(frozen=True)
class RawFactSnapshot:
    raw_fact_id: int
    parse_run_id: int
    normalization_id: int | None
    namespace_uri: str | None
    local_name: str
    normalized_value: Decimal | None
    unit_numerator: tuple[Mapping[str, str], ...]
    unit_denominator: tuple[Mapping[str, str], ...]
    context_id: str
    dimensions: tuple[object, ...]
    form: str
    period_start: date | None
    period_end: date
    statement_period_end: date
    fiscal_year: int
    fiscal_quarter_ordinal: int | None
    fiscal_year_start: date
    stock_id: int
    filing_authority_id: str
    publication_cutoff: datetime
    fiscal_cycle: str
    amendment_policy_id: str
    known_at: datetime
    is_nil: bool
    occurrence_authorities: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True)
class CanonicalCandidate:
    mapping_rule_id: str
    metric_key: str
    value: Decimal
    unit: str
    currency: str | None
    period_type: str
    period_start: date | None
    period_end: date
    fiscal_year: int
    fiscal_quarter_ordinal: int | None
    context_id: str
    dimensions: tuple[object, ...]
    stock_id: int
    fiscal_year_start: date
    filing_authority_id: str
    publication_cutoff: datetime
    parse_run_ids: tuple[int, ...]
    raw_fact_ids: tuple[int, ...]
    normalization_ids: tuple[int, ...]
    derivation_kind: str
    occurrence_authorities: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True)
class CanonicalSlotAuthority:
    stock_id: int
    metric_key: str
    mapping_rule_id: str
    period_type: str
    period_start: date | None
    period_end: date
    period_basis: str
    fiscal_year: int
    fiscal_quarter_ordinal: int | None
    context_id: str
    dimensions: tuple[object, ...]
    parse_run_ids: tuple[int, ...]
    raw_fact_ids: tuple[int, ...]
    publication_cutoff: datetime
    occurrence_authorities: tuple[Mapping[str, object], ...] = ()
    filing_authority_id: str | None = None


@dataclass(frozen=True)
class TypedDisposition:
    reason: str
    raw_fact_ids: tuple[int, ...]
    mapping_rule_id: str | None = None
    detail: str | None = None
    slot: CanonicalSlotAuthority | None = None


@dataclass(frozen=True)
class MappingResult:
    candidates: tuple[CanonicalCandidate, ...]
    dispositions: tuple[TypedDisposition, ...]
    truncated_decision_count: int


@dataclass(frozen=True)
class MappingRunAuthority:
    publication_cutoff: datetime
    selected_filing_authority_ids: tuple[str, ...]
    amendment_policy_id: str
    filing_cycle_sources: tuple["FilingCycleSourceAuthority", ...] = ()


@dataclass(frozen=True)
class FilingCycleSourceAuthority:
    """Database-selected filing-cycle order consumed by the pure mapper."""

    filing_authority_id: str
    parse_run_id: int
    base_form: str
    report_date: date
    accepted_at: datetime
    is_amendment: bool
    parse_status: str = "succeeded"


_RULE_DATA = (
    ("sec.revenue", "is.revenue", "monetary", "duration", (("us_gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", 1), ("us_gaap", "SalesRevenueNet", 2), ("us_gaap", "Revenues", 3))),
    ("sec.gross_profit", "is.gross_profit", "monetary", "duration", (("us_gaap", "GrossProfit", 1),)),
    ("sec.operating_income", "is.operating_income", "monetary", "duration", (("us_gaap", "OperatingIncomeLoss", 1),)),
    ("sec.net_income", "is.net_income", "monetary", "duration", (("us_gaap", "NetIncomeLoss", 1),)),
    ("sec.operating_cash_flow", "is.operating_cash_flow", "monetary", "duration", (("us_gaap", "NetCashProvidedByUsedInOperatingActivities", 1),)),
    ("sec.capital_expenditures", "cf.capital_expenditures", "monetary", "duration", (("us_gaap", "PaymentsToAcquirePropertyPlantAndEquipment", 1),)),
    ("sec.stock_based_compensation", "cf.stock_based_compensation", "monetary", "duration", (("us_gaap", "ShareBasedCompensation", 1),)),
    ("sec.cash_and_equivalents", "bs.cash_and_equivalents", "monetary", "instant", (("us_gaap", "CashAndCashEquivalentsAtCarryingValue", 1),)),
    ("sec.cash_and_restricted_cash", "bs.cash_and_restricted_cash", "monetary", "instant", (("us_gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", 1),)),
    ("sec.total_assets", "bs.total_assets", "monetary", "instant", (("us_gaap", "Assets", 1),)),
    ("sec.current_assets", "bs.current_assets", "monetary", "instant", (("us_gaap", "AssetsCurrent", 1),)),
    ("sec.total_liabilities", "bs.total_liabilities", "monetary", "instant", (("us_gaap", "Liabilities", 1),)),
    ("sec.current_liabilities", "bs.current_liabilities", "monetary", "instant", (("us_gaap", "LiabilitiesCurrent", 1),)),
    ("sec.stockholders_equity", "bs.stockholders_equity", "monetary", "instant", (("us_gaap", "StockholdersEquity", 1),)),
    ("sec.equity_including_noncontrolling_interest", "bs.equity_including_noncontrolling_interest", "monetary", "instant", (("us_gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", 1),)),
    ("sec.long_term_debt_current", "cap.long_term_debt_current", "monetary", "instant", (("us_gaap", "LongTermDebtCurrent", 1),)),
    ("sec.short_term_borrowings", "cap.short_term_borrowings", "monetary", "instant", (("us_gaap", "ShortTermBorrowings", 1),)),
    ("sec.long_term_debt_noncurrent", "cap.long_term_debt_noncurrent", "monetary", "instant", (("us_gaap", "LongTermDebtNoncurrent", 1),)),
    ("sec.diluted_eps", "per_share.eps", "currency_per_share", "duration", (("us_gaap", "EarningsPerShareDiluted", 1),)),
    ("sec.shares_outstanding", "equity.shares_outstanding", "shares", "instant", (("us_gaap", "CommonStockSharesOutstanding", 1), ("dei", "EntityCommonStockSharesOutstanding", 2))),
    ("sec.weighted_average_diluted_shares", "equity.weighted_average_diluted_shares", "shares", "duration", (("us_gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", 1),)),
)


def canonical_sec_mapping_v1() -> MappingSnapshot:
    rules = tuple(MappingRule(a, b, c, d, tuple(ConceptRule(*item) for item in concepts)) for a, b, c, d, concepts in _RULE_DATA)
    return MappingSnapshot(
        "sec-us-gaap-v1", "01b828534060e04439103c935842c1a9cf42d3f5a2311934c99bef81bdcc073d",
        datetime(2026, 8, 31, tzinfo=timezone.utc),
        datetime(2026, 8, 31, tzinfo=timezone.utc),
        MappingProxyType({"us_gaap": US_GAAP_URIS, "dei": DEI_URIS}),
        ("DKK", "EUR", "TWD", "USD"), rules,
    )


def validate_sec_mapping_snapshot(mapping: MappingSnapshot) -> None:
    """Validate the immutable V1 contract without selecting runtime authority."""
    if mapping.mapping_version_id != "sec-us-gaap-v1" or mapping.spec_sha256 != "01b828534060e04439103c935842c1a9cf42d3f5a2311934c99bef81bdcc073d":
        raise ValueError("unsupported mapping snapshot")
    if set(mapping.namespaces) != {"us_gaap","dei"} or any(not values for values in mapping.namespaces.values()):
        raise ValueError("unsupported mapping snapshot")
    if mapping.currency_codes != ("DKK","EUR","TWD","USD") or len(mapping.rules) != 21:
        raise ValueError("unsupported mapping snapshot")
    identities=set()
    for rule in mapping.rules:
        if not rule.rule_id or not rule.metric_key or not rule.concepts or [c.priority for c in rule.concepts] != list(range(1,len(rule.concepts)+1)):
            raise ValueError("unsupported mapping snapshot")
        if any(c.authority not in mapping.namespaces or not c.local_name for c in rule.concepts):
            raise ValueError("unsupported mapping snapshot")
        identities.add((rule.rule_id,rule.metric_key))
    if len(identities) != len(mapping.rules): raise ValueError("unsupported mapping snapshot")


def map_sec_financial_snapshot(mapping: MappingSnapshot, facts: Sequence[RawFactSnapshot], authority: MappingRunAuthority, *, max_decisions: int = 512) -> MappingResult:
    validate_sec_mapping_snapshot(mapping)
    if max_decisions < 0 or len(facts) > 10_000:
        raise ValueError("mapping input exceeds bounded contract")
    dispositions: list[TypedDisposition] = []
    candidates: list[CanonicalCandidate] = []
    matched_ids: set[int] = set()
    rejected: set[int] = set()
    _validate_filing_cycle_authority(facts, authority)
    mapping_late = mapping.known_at > authority.publication_cutoff or mapping.effective_at > authority.publication_cutoff
    for fact in facts:
        if mapping_late or fact.known_at > authority.publication_cutoff:
            dispositions.append(TypedDisposition("unresolved_derived_input_after_cutoff", (fact.raw_fact_id,)))
            rejected.add(fact.raw_fact_id)
        elif fact.publication_cutoff != authority.publication_cutoff or fact.filing_authority_id not in authority.selected_filing_authority_ids or fact.amendment_policy_id != authority.amendment_policy_id:
            dispositions.append(TypedDisposition("unresolved_derived_filing_authority_mismatch", (fact.raw_fact_id,)))
            rejected.add(fact.raw_fact_id)
    for rule in mapping.rules:
        concept_by_local = {concept.local_name: concept for concept in rule.concepts}
        rule_facts = [fact for fact in facts if fact.raw_fact_id not in rejected and fact.local_name in concept_by_local]
        matched_ids.update(fact.raw_fact_id for fact in rule_facts)
        slots: dict[tuple[object, ...], list[tuple[RawFactSnapshot, ConceptRule]]] = {}
        for fact in rule_facts:
            slots.setdefault(_raw_priority_slot(fact), []).append((fact, concept_by_local[fact.local_name]))
        for raw_items in slots.values():
            priorities = sorted({item[1].priority for item in raw_items})
            chosen_priority = None
            group = []
            for priority in priorities:
                tested = []
                for fact, concept in sorted((item for item in raw_items if item[1].priority == priority), key=lambda item: item[0].raw_fact_id):
                    reason, unit, currency, period_type, persisted_value = _validate_fact(mapping, rule, concept, fact)
                    if reason:
                        # A bad value/unit is allowed to affect canonical truth only
                        # after the exact concept and presentation period independently
                        # establish a slot.  Structural/raw audit failures remain
                        # deliberately slotless.
                        slot = None
                        if reason in ("unresolved_value", "unresolved_unit", "unresolved_currency"):
                            proved_period, period_reason = _period(rule.period_basis, fact)
                            if period_reason is None and fact.namespace_uri in mapping.namespaces[concept.authority] and not fact.dimensions and fact.context_id:
                                slot = _slot_from_raw(rule, fact, proved_period)
                        dispositions.append(TypedDisposition(reason, (fact.raw_fact_id,), rule.rule_id, slot=slot))
                    else: tested.append((fact, concept, unit, currency, period_type, persisted_value))
                if tested:
                    chosen_priority, group = priority, tested
                    break
            if chosen_priority is None:
                continue
            lower = [item for item in raw_items if item[1].priority > chosen_priority]
            distinct_values = {(item[5], item[2], item[3]) for item in group}
            if len(distinct_values) > 1:
                ordered_group = sorted(group, key=lambda item: item[0].raw_fact_id)
                slot = _slot_from_item(rule, ordered_group[0])
                slot = replace(slot, raw_fact_ids=tuple(item[0].raw_fact_id for item in ordered_group), parse_run_ids=tuple(item[0].parse_run_id for item in ordered_group), occurrence_authorities=tuple(authority for item in ordered_group for authority in item[0].occurrence_authorities))
                dispositions.append(TypedDisposition("unresolved_conflicting_candidates", slot.raw_fact_ids, rule.rule_id, slot=slot))
            else:
                selected = min(group, key=lambda item: item[0].raw_fact_id)
                try:
                    candidates.append(_candidate(rule, selected))
                except (ArithmeticError, ValueError):
                    dispositions.append(TypedDisposition("unresolved_value", (selected[0].raw_fact_id,), rule.rule_id))
                for duplicate in group:
                    if duplicate is not selected:
                        dispositions.append(TypedDisposition("duplicate_identical_candidate_not_selected", (duplicate[0].raw_fact_id,), rule.rule_id))
            for item in lower:
                dispositions.append(TypedDisposition("lower_priority_concept_not_selected", (item[0].raw_fact_id,), rule.rule_id))
    for fact in sorted(facts, key=lambda item: item.raw_fact_id):
        if fact.raw_fact_id not in matched_ids and fact.raw_fact_id not in rejected:
            dispositions.append(TypedDisposition("unresolved_custom_concept", (fact.raw_fact_id,)))
    if authority.filing_cycle_sources:
        candidates, dispositions = _apply_amendment_slot_authority(
            mapping,
            candidates,
            dispositions,
            facts,
            authority.filing_cycle_sources,
        )
    derived, derived_dispositions = _derive_quarters(candidates)
    candidates.extend(derived)
    dispositions.extend(derived_dispositions)
    candidates = _apply_direct_precedence(candidates)
    dispositions.sort(key=lambda item: (item.raw_fact_ids, item.reason))
    truncated = max(0, len(dispositions) - max_decisions)
    return MappingResult(tuple(sorted(candidates, key=_candidate_sort_key)), tuple(dispositions[:max_decisions]), truncated)


def _raw_priority_slot(fact):
    return (
        fact.stock_id, fact.period_start, fact.period_end, fact.statement_period_end,
        fact.fiscal_year, fact.fiscal_quarter_ordinal, fact.fiscal_year_start,
        fact.form, fact.fiscal_cycle, fact.publication_cutoff,
        fact.filing_authority_id,
    )


def _validate_filing_cycle_authority(facts, authority):
    if not authority.filing_cycle_sources:
        return
    source_ids = tuple(item.filing_authority_id for item in authority.filing_cycle_sources)
    if source_ids != authority.selected_filing_authority_ids or len(source_ids) != len(set(source_ids)):
        raise ValueError("filing cycle authority does not match selected source order")
    by_filing = {item.filing_authority_id: item for item in authority.filing_cycle_sources}
    if len({item.parse_run_id for item in authority.filing_cycle_sources}) != len(by_filing):
        raise ValueError("filing cycle authority parse identity is not unique")
    for source in authority.filing_cycle_sources:
        if source.base_form not in ("10-K", "10-Q", "20-F", "6-K"):
            raise ValueError("filing cycle authority has unsupported base form")
        if source.accepted_at.tzinfo is None or source.accepted_at.utcoffset() is None:
            raise ValueError("filing cycle authority acceptance must be timezone-aware")
        if source.parse_status not in ("succeeded", "failed"):
            raise ValueError("filing cycle authority parse status is invalid")
    for fact in facts:
        source = by_filing.get(fact.filing_authority_id)
        if source is None or source.parse_run_id != fact.parse_run_id:
            raise ValueError("raw fact is outside filing cycle authority")
        expected_form = source.base_form + ("/A" if source.is_amendment else "")
        if fact.form != expected_form:
            raise ValueError("raw fact form differs from filing cycle authority")


def _apply_amendment_slot_authority(mapping, candidates, dispositions, facts, sources):
    """Select a filing-cycle effect independently for each canonical slot.

    Omission is not an effect.  Within one ``(base form, report date)`` cycle,
    the latest amendment that actually carries a candidate or a slot-aware
    typed decision supersedes the earlier effect for only that slot.
    """

    source_by_filing = {item.filing_authority_id: item for item in sources}
    slotless = [item for item in dispositions if item.slot is None]
    slot_dispositions = [item for item in dispositions if item.slot is not None]

    effects: dict[tuple[object, ...], list[tuple[FilingCycleSourceAuthority, str, object]]] = {}
    for candidate in candidates:
        source = source_by_filing[candidate.filing_authority_id]
        key = (
            source.base_form,
            source.report_date,
            candidate.stock_id,
            candidate.metric_key,
            candidate.period_type,
            candidate.period_end,
        )
        effects.setdefault(key, []).append((source, "candidate", candidate))
    for disposition in slot_dispositions:
        source = source_by_filing[disposition.slot.filing_authority_id]
        key = (
            source.base_form,
            source.report_date,
            disposition.slot.stock_id,
            disposition.slot.metric_key,
            disposition.slot.period_type,
            disposition.slot.period_end,
        )
        effects.setdefault(key, []).append((source, "disposition", disposition))

    selected_candidates = []
    selected_dispositions = list(slotless)
    for grouped in effects.values():
        winning_source = max(
            (item[0] for item in grouped),
            key=lambda item: (
                item.is_amendment,
                item.accepted_at,
                item.filing_authority_id,
            ),
        )
        for source, effect_kind, effect in grouped:
            if source != winning_source:
                continue
            if effect_kind == "candidate":
                selected_candidates.append(effect)
            else:
                selected_dispositions.append(effect)

    registered_raw_ids = {
        fact.raw_fact_id
        for fact in facts
        if any(
            fact.local_name == concept.local_name
            and fact.namespace_uri in mapping.namespaces[concept.authority]
            for rule in mapping.rules
            for concept in rule.concepts
        )
    }
    mapped_filing_ids = {
        candidate.filing_authority_id for candidate in candidates
    } | {
        item.slot.filing_authority_id
        for item in slot_dispositions
        if item.slot is not None
    } | {
        fact.filing_authority_id
        for fact in facts
        if fact.raw_fact_id in registered_raw_ids
        and any(
            disposition.mapping_rule_id is not None
            and fact.raw_fact_id in disposition.raw_fact_ids
            for disposition in dispositions
        )
    }
    for source in sources:
        if (
            source.is_amendment
            and source.parse_status == "succeeded"
            and source.filing_authority_id not in mapped_filing_ids
        ):
            selected_dispositions.append(
                TypedDisposition(
                    "nonfinancial_amendment_no_slot_effect",
                    (),
                    detail="filing_authority_id=" + source.filing_authority_id,
                )
            )
    return selected_candidates, selected_dispositions


def _validate_fact(mapping, rule, concept, fact):
    if fact.namespace_uri not in mapping.namespaces[concept.authority]: return "unresolved_custom_concept", "", None, "", None
    if fact.dimensions: return "unresolved_dimensions", "", None, "", None
    if not fact.context_id: return "unresolved_context", "", None, "", None
    if fact.is_nil or fact.normalized_value is None or fact.normalization_id is None: return "unresolved_value", "", None, "", None
    if not fact.normalized_value.is_finite(): return "unresolved_value", "", None, "", None
    try: persisted_value = persist_numeric_38_12(fact.normalized_value)
    except (ArithmeticError, ValueError): return "unresolved_value", "", None, "", None
    unit, currency, reason = _unit(rule.value_kind, fact, mapping.currency_codes)
    if reason: return reason, "", None, "", None
    period_type, reason = _period(rule.period_basis, fact)
    if reason: return reason, "", None, "", None
    return None, unit, currency, period_type, persisted_value


def _unit(kind, fact, currencies):
    numerator, denominator = fact.unit_numerator, fact.unit_denominator
    if kind in ("monetary", "currency_per_share"):
        if len(numerator) != 1 or numerator[0].get("namespace_uri") != ISO4217_URI: return "", None, "unresolved_unit"
        currency = numerator[0].get("local_name")
        if currency not in currencies: return "", None, "unresolved_currency"
        if kind == "monetary" and denominator: return "", None, "unresolved_unit"
        if kind == "currency_per_share" and (len(denominator) != 1 or denominator[0].get("namespace_uri") != XBRLI_URI or denominator[0].get("local_name") != "shares"): return "", None, "unresolved_unit"
        return ("currency" if kind == "monetary" else "currency_per_share"), currency, None
    if len(numerator) != 1 or numerator[0].get("namespace_uri") != XBRLI_URI or numerator[0].get("local_name") != "shares" or denominator: return "", None, "unresolved_unit"
    return "shares", None, None


def _period(basis, fact):
    if fact.form in ("6-K", "6-K/A"): return "", "unresolved_unsupported_form_semantics"
    if fact.period_end != fact.statement_period_end: return "", "unresolved_period_filing_cycle_mismatch"
    if basis == "instant":
        if fact.period_start is not None: return "", "unresolved_period"
        if fact.form in ("10-K", "10-K/A", "20-F", "20-F/A"):
            return ("FY", None) if fact.fiscal_cycle in ("filing_fiscal_year_end", "explicit_prior_fiscal_year_comparative") else ("", "unresolved_period_filing_cycle_mismatch")
        if fact.form in ("10-Q", "10-Q/A"):
            if fact.fiscal_cycle in ("filing_quarter_end", "explicit_prior_same_fiscal_quarter_comparative"): return "Q", None
            if fact.fiscal_cycle == "explicit_prior_fiscal_year_end_balance_sheet": return "FY", None
            return "", "unresolved_period_filing_cycle_mismatch"
        return "", "unresolved_unsupported_form_semantics"
    if fact.period_start is None: return "", "unresolved_period"
    days = (fact.period_end - fact.period_start).days + 1
    if fact.form in ("10-K", "10-K/A", "20-F", "20-F/A"):
        if fact.fiscal_cycle not in ("filing_fiscal_year_end", "explicit_prior_fiscal_year_comparative"): return "", "unresolved_period_filing_cycle_mismatch"
        if fact.period_start != fact.fiscal_year_start: return "", "unresolved_period_filing_cycle_mismatch"
        return ("FY", None) if 300 <= days <= 380 else ("", "unresolved_period_filing_cycle_mismatch")
    if fact.form not in ("10-Q", "10-Q/A"): return "", "unresolved_unsupported_form_semantics"
    if fact.fiscal_cycle not in ("filing_quarter_end", "explicit_prior_same_fiscal_quarter_comparative"): return "", "unresolved_period_filing_cycle_mismatch"
    if 70 <= days <= 110: return "Q", None
    if 150 <= days <= 210 or 240 <= days <= 300:
        return ("YTD", None) if fact.period_start == fact.fiscal_year_start else ("", "unresolved_period_filing_cycle_mismatch")
    return "", "unresolved_period_filing_cycle_mismatch"


def _candidate(rule, item):
    fact, _, unit, currency, period_type, persisted_value = item
    return CanonicalCandidate(rule.rule_id, rule.metric_key, persisted_value, unit, currency, period_type, fact.period_start, fact.period_end, fact.fiscal_year, fact.fiscal_quarter_ordinal, fact.context_id, fact.dimensions, fact.stock_id, fact.fiscal_year_start, fact.filing_authority_id, fact.publication_cutoff, (fact.parse_run_id,), (fact.raw_fact_id,), (fact.normalization_id,), "direct", fact.occurrence_authorities)


def _slot_from_item(rule, item):
    fact, _, _, _, period_type, _ = item
    return CanonicalSlotAuthority(fact.stock_id, rule.metric_key, rule.rule_id, period_type, fact.period_start, fact.period_end,
                                  "instant" if fact.period_start is None else "duration", fact.fiscal_year,
                                  fact.fiscal_quarter_ordinal, fact.context_id, fact.dimensions, (fact.parse_run_id,),
                                  (fact.raw_fact_id,), fact.publication_cutoff, fact.occurrence_authorities,
                                  fact.filing_authority_id)


def _slot_from_raw(rule, fact, period_type):
    return CanonicalSlotAuthority(
        fact.stock_id, rule.metric_key, rule.rule_id, period_type,
        fact.period_start, fact.period_end, rule.period_basis, fact.fiscal_year,
        fact.fiscal_quarter_ordinal, fact.context_id, fact.dimensions,
        (fact.parse_run_id,), (fact.raw_fact_id,), fact.publication_cutoff,
        fact.occurrence_authorities, fact.filing_authority_id,
    )


def _derive_quarters(candidates):
    derived = []
    dispositions = []
    groups: dict[tuple[object, ...], list[CanonicalCandidate]] = {}
    for item in candidates:
        groups.setdefault((item.mapping_rule_id, item.metric_key, item.stock_id, item.fiscal_year), []).append(item)
    for items in groups.values():
        for ordinal in (2, 3):
            lefts = [item for item in items if (item.period_type, item.fiscal_quarter_ordinal) == ("YTD", ordinal)]
            right_shape = ("Q", 1) if ordinal == 2 else ("YTD", 2)
            rights = [item for item in items if (item.period_type, item.fiscal_quarter_ordinal) == right_shape]
            _derive_each(lefts, rights, ordinal, "current_ytd_minus_prior_ytd", derived, dispositions)
        lefts = [item for item in items if (item.period_type, item.fiscal_quarter_ordinal) == ("FY", None)]
        rights = [item for item in items if (item.period_type, item.fiscal_quarter_ordinal) == ("YTD", 3)]
        _derive_each(lefts, rights, 4, "fiscal_year_minus_nine_month_ytd", derived, dispositions)
    return derived, dispositions


def _derive_each(lefts, rights, ordinal, kind, derived, dispositions):
    for left in sorted(lefts, key=lambda item: item.raw_fact_ids):
        if not rights:
            dispositions.append(TypedDisposition("unresolved_missing_derived_quarter_input", left.raw_fact_ids, left.mapping_rule_id))
            continue
        ordered = sorted(rights, key=lambda item: item.raw_fact_ids)
        compatible = [right for right in ordered if _operand_mismatch(left, right) is None]
        if not compatible:
            mismatch_order = {
                "unresolved_derived_fiscal_year_mismatch": 0, "unresolved_derived_unit_mismatch": 1,
                "unresolved_derived_currency_mismatch": 2, "unresolved_derived_context_mismatch": 3,
                "unresolved_derived_filing_authority_mismatch": 4, "unresolved_derived_input_after_cutoff": 5,
                "unresolved_derived_period_identity": 6,
            }
            right = min(ordered, key=lambda item: (mismatch_order[_operand_mismatch(left, item)], item.raw_fact_ids))
            output_slot = _derived_output_slot(left, right, ordinal)
            dispositions.append(TypedDisposition(_operand_mismatch(left, right), left.raw_fact_ids + right.raw_fact_ids, left.mapping_rule_id, slot=output_slot))
            continue
        right = compatible[0]
        output_slot = _derived_output_slot(left, right, ordinal)
        if not 70 <= (left.period_end - right.period_end).days <= 110:
            dispositions.append(TypedDisposition("unresolved_derived_period_identity", left.raw_fact_ids + right.raw_fact_ids, left.mapping_rule_id, slot=output_slot))
            continue
        try: derived.append(_derived(left, right, ordinal, kind))
        except (ArithmeticError, ValueError): dispositions.append(TypedDisposition("unresolved_value", left.raw_fact_ids + right.raw_fact_ids, left.mapping_rule_id, slot=output_slot))


def _derived_output_slot(left, right, ordinal):
    # Both presentation periods uniquely establish the derived output slot,
    # independently of the later compatibility/arithmetic decision.
    return CanonicalSlotAuthority(
        left.stock_id, left.metric_key, left.mapping_rule_id, "Q", right.period_end + timedelta(days=1),
        left.period_end, "duration", left.fiscal_year, ordinal, left.context_id,
        left.dimensions, left.parse_run_ids + right.parse_run_ids,
        left.raw_fact_ids + right.raw_fact_ids,
        left.publication_cutoff, left.occurrence_authorities + right.occurrence_authorities,
        left.filing_authority_id,
    )


def _operand_mismatch(left, right):
    if left.stock_id != right.stock_id: return "unresolved_derived_cross_stock"
    if left.fiscal_year_start != right.fiscal_year_start or left.fiscal_year != right.fiscal_year: return "unresolved_derived_fiscal_year_mismatch"
    if left.unit != right.unit: return "unresolved_derived_unit_mismatch"
    if left.currency != right.currency: return "unresolved_derived_currency_mismatch"
    if left.context_id != right.context_id or left.dimensions != right.dimensions: return "unresolved_derived_context_mismatch"
    if left.publication_cutoff != right.publication_cutoff: return "unresolved_derived_input_after_cutoff"
    if left.period_start != right.period_start: return "unresolved_derived_period_identity"
    return None


def _derived(left, right, ordinal, kind):
    return CanonicalCandidate(left.mapping_rule_id, left.metric_key, persist_numeric_38_12(left.value-right.value), left.unit, left.currency, "Q", right.period_end+timedelta(days=1), left.period_end, left.fiscal_year, ordinal, left.context_id, left.dimensions, left.stock_id, left.fiscal_year_start, left.filing_authority_id, left.publication_cutoff, left.parse_run_ids+right.parse_run_ids, left.raw_fact_ids+right.raw_fact_ids, left.normalization_ids+right.normalization_ids, kind, left.occurrence_authorities+right.occurrence_authorities)


def _apply_direct_precedence(candidates):
    def identity(item):
        return (item.mapping_rule_id, item.stock_id, item.fiscal_year, item.fiscal_quarter_ordinal, item.unit, item.currency, item.context_id, item.dimensions, item.fiscal_year_start, item.publication_cutoff)
    direct_slots = {identity(item) for item in candidates if item.derivation_kind == "direct" and item.period_type == "Q"}
    return [item for item in candidates if item.derivation_kind == "direct" or identity(item) not in direct_slots]


def _candidate_sort_key(item):
    return (item.metric_key, item.period_end, item.period_type, item.fiscal_quarter_ordinal or 0, item.derivation_kind, item.raw_fact_ids)
