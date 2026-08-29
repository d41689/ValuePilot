"""Versioned SEC inline-XBRL to canonical metric_facts publication.

Raw SEC tables are lineage only. This module is the sole publication boundary;
product consumers continue to read metric_facts and never raw XBRL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import re
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session
import yaml

from app.models.facts import MetricFact
from app.models.sec_financials import (
    SecFinancialFiling,
    SecFinancialParseRun,
    SecIssuerIdentity,
    SecMetricPublication,
    SecRawXbrlFact,
)
from app.services.sec_financial_ingestion import (
    SecFinancialIngestionError,
    select_sec_financial_evidence_as_of,
)


SPEC_PATH = next(
    (
        parent / "docs" / "metric_facts_mapping_spec.yml"
        for parent in Path(__file__).resolve().parents
        if (parent / "docs" / "metric_facts_mapping_spec.yml").exists()
    ),
    Path("docs/metric_facts_mapping_spec.yml"),
)
_CURRENCY_MEASURE_RE = re.compile(r"^(?:iso4217:)?([A-Z]{3})$", re.IGNORECASE)


@dataclass(frozen=True)
class SecMetricPublicationReport:
    stock_id: int
    mapping_version: str
    eligible_filing_count: int
    created_count: int
    published_count: int
    unresolved_count: int
    rejected_count: int


@dataclass(frozen=True)
class _Rule:
    metric_key: str
    value_kind: str
    period_basis: str
    concept_priority: int


@dataclass
class _Decision:
    raw: SecRawXbrlFact
    filing: SecFinancialFiling
    run: SecFinancialParseRun
    knowledge_at: datetime
    status: str
    reason_code: str | None
    metric_key: str | None = None
    value_numeric: float | None = None
    unit: str | None = None
    currency: str | None = None
    period_type: str | None = None
    period_end_date: date | None = None
    period_start_date: date | None = None
    concept_priority: int = 0
    metric_fact_id: int | None = None


def _load_rules(mapping_version: str) -> tuple[dict[str, _Rule], dict[str, Any]]:
    payload = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8")) or {}
    sec = payload.get("sec_xbrl") or {}
    if sec.get("mapping_version") != mapping_version:
        raise SecFinancialIngestionError(
            f"unknown SEC mapping version: {mapping_version}"
        )
    rules: dict[str, _Rule] = {}
    for mapping in sec.get("mappings") or []:
        for priority, concept in enumerate(mapping.get("concepts") or []):
            if not isinstance(concept, str) or concept in rules:
                raise SecFinancialIngestionError(
                    "SEC mapping concepts must be unique non-empty strings"
                )
            rules[concept] = _Rule(
                metric_key=str(mapping["metric_key"]),
                value_kind=str(mapping["value_kind"]),
                period_basis=str(mapping["period_basis"]),
                concept_priority=priority,
            )
    return rules, sec


def _numeric_value(raw: SecRawXbrlFact) -> Decimal:
    if raw.is_nil or raw.raw_value is None:
        raise ValueError("nil_or_missing_value")
    value = raw.raw_value.strip().replace("\u00a0", "").replace(" ", "")
    negative_parentheses = value.startswith("(") and value.endswith(")")
    if negative_parentheses:
        value = value[1:-1]
    transform = str(raw.transformation_format or "").lower()
    if "comma-decimal" in transform or "num-comma" in transform:
        value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(",", "")
    value = value.replace("$", "").replace("€", "").replace("£", "")
    if value in {"", "-", "—"}:
        if "zero" in transform or "dash" in transform:
            value = "0"
        else:
            raise ValueError("non_numeric_value")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("non_numeric_value") from exc
    if negative_parentheses:
        number = -number
    if raw.sign == "-":
        number = -abs(number)
    if raw.scale:
        number *= Decimal(10) ** raw.scale
    if not number.is_finite():
        raise ValueError("non_finite_value")
    return number


def _normalized_unit(
    raw: SecRawXbrlFact,
    value_kind: str,
    currency_policy: dict[str, Any],
) -> tuple[str, str | None]:
    measure = str(raw.unit_measure or "").strip()
    if value_kind == "shares":
        if measure.lower() not in {"xbrli:shares", "shares"}:
            raise ValueError("unit_mismatch")
        return "shares", None
    if value_kind == "currency_per_share":
        numerator, separator, denominator = measure.partition("/")
        match = _CURRENCY_MEASURE_RE.fullmatch(numerator.upper())
        if not separator or not match or denominator.lower() not in {
            "xbrli:shares",
            "shares",
        }:
            raise ValueError("unit_mismatch")
        currency = match.group(1).upper()
        unit = (currency_policy.get("per_share_units") or {}).get(currency)
        if not unit:
            raise ValueError("unsupported_currency")
        return str(unit), currency
    if value_kind == "monetary":
        match = _CURRENCY_MEASURE_RE.fullmatch(measure.upper())
        if not match:
            raise ValueError("unit_mismatch")
        currency = match.group(1).upper()
        unit = (currency_policy.get("monetary_units") or {}).get(currency)
        if not unit:
            raise ValueError("unsupported_currency")
        return str(unit), currency
    raise ValueError("unsupported_value_kind")


def _period(
    raw: SecRawXbrlFact,
    filing: SecFinancialFiling,
    rule: _Rule,
    period_policy: dict[str, Any],
) -> tuple[str, date]:
    base_form = filing.form_type.removesuffix("/A")
    if base_form == "6-K":
        raise ValueError("unsupported_form_period")
    if rule.period_basis == "instant":
        if raw.period_instant is None:
            raise ValueError("period_missing")
        if base_form in {"10-K", "20-F"}:
            return "FY", raw.period_instant
        if base_form == "10-Q":
            return "Q", raw.period_instant
        raise ValueError("unsupported_form_period")
    if rule.period_basis != "duration" or raw.period_start is None or raw.period_end is None:
        raise ValueError("period_missing")
    duration_days = (raw.period_end - raw.period_start).days + 1
    annual_min, annual_max = period_policy["annual_duration_days"]
    quarter_min, quarter_max = period_policy["discrete_quarter_duration_days"]
    ytd_min, ytd_max = period_policy["ytd_duration_days"]
    if base_form in {"10-K", "20-F"} and annual_min <= duration_days <= annual_max:
        return "FY", raw.period_end
    if base_form == "10-Q" and quarter_min <= duration_days <= quarter_max:
        return "Q", raw.period_end
    if base_form == "10-Q" and ytd_min <= duration_days <= ytd_max:
        return "YTD", raw.period_end
    raise ValueError("unsupported_period_duration")


def _knowledge_at(
    raw: SecRawXbrlFact,
    run: SecFinancialParseRun,
    filing: SecFinancialFiling,
) -> datetime:
    values = [
        filing.accepted_at,
        filing.known_at,
        run.completed_at,
        run.known_at,
        run.created_at,
        raw.created_at,
    ]
    return max(value for value in values if value is not None)


def _input_provenance(fact: MetricFact) -> dict[str, Any]:
    payload = fact.value_json if isinstance(fact.value_json, dict) else {}
    return {
        "metric_fact_id": fact.id,
        "raw_fact_id": fact.source_ref_id,
        "artifact_id": payload.get("artifact_id"),
        "source_accession": payload.get("source_accession"),
        "filing_id": payload.get("filing_id"),
        "parse_run_id": payload.get("parse_run_id"),
        "parser_version": payload.get("parser_version"),
        "mapping_version": payload.get("mapping_version"),
        "mapping_known_at": payload.get("mapping_known_at"),
        "knowledge_at": payload.get("knowledge_at"),
        "period_start": payload.get("period_start"),
        "period_end": payload.get("period_end"),
        "context_id": payload.get("context_id"),
        "dimensions_policy": payload.get("dimensions_policy"),
        "dimensions": payload.get("dimensions"),
        "unit_measure": payload.get("unit_measure"),
        "decimals": payload.get("decimals"),
        "scale": payload.get("scale"),
        "locator": payload.get("locator"),
        "value_numeric": fact.value_numeric,
        "unit": fact.unit,
        "currency": fact.currency,
    }


def _decision_for_raw(
    *,
    raw: SecRawXbrlFact,
    filing: SecFinancialFiling,
    run: SecFinancialParseRun,
    rules: dict[str, _Rule],
    sec_policy: dict[str, Any],
) -> _Decision:
    knowledge_at = _knowledge_at(raw, run, filing)
    rule = rules.get(raw.concept)
    if rule is None:
        return _Decision(
            raw=raw,
            filing=filing,
            run=run,
            knowledge_at=knowledge_at,
            status="unresolved",
            reason_code="unmapped_concept",
        )
    if raw.dimensions_json:
        return _Decision(
            raw=raw,
            filing=filing,
            run=run,
            knowledge_at=knowledge_at,
            status="rejected",
            reason_code="dimensions_not_supported",
            metric_key=rule.metric_key,
        )
    try:
        number = _numeric_value(raw)
        unit, currency = _normalized_unit(
            raw,
            rule.value_kind,
            sec_policy["currency_policy"],
        )
        period_type, period_end_date = _period(
            raw,
            filing,
            rule,
            sec_policy["period_policy"],
        )
    except ValueError as exc:
        return _Decision(
            raw=raw,
            filing=filing,
            run=run,
            knowledge_at=knowledge_at,
            status="rejected",
            reason_code=str(exc),
            metric_key=rule.metric_key,
        )
    return _Decision(
        raw=raw,
        filing=filing,
        run=run,
        knowledge_at=knowledge_at,
        status="published",
        reason_code=None,
        metric_key=rule.metric_key,
        value_numeric=float(number),
        unit=unit,
        currency=currency,
        period_type=period_type,
        period_end_date=period_end_date,
        period_start_date=raw.period_start,
        concept_priority=rule.concept_priority,
    )


def _demote_derived_facts_using_inputs(
    session: Session,
    *,
    stock_id: int,
    mapping_version: str,
    input_fact_ids: set[int],
) -> None:
    """Retire every current derivation that names a retired exact input."""
    if not input_fact_ids:
        return
    derived_facts = session.scalars(
        select(MetricFact).where(
            MetricFact.user_id.is_(None),
            MetricFact.stock_id == stock_id,
            MetricFact.source_type == "sec",
            MetricFact.is_current.is_(True),
            MetricFact.value_json["mapping_version"].as_string()
            == mapping_version,
            MetricFact.value_json["value_basis"].as_string()
            == "derived_discrete_quarter",
        )
    ).all()
    for fact in derived_facts:
        payload = fact.value_json if isinstance(fact.value_json, dict) else {}
        recorded_inputs = payload.get("input_metric_fact_ids")
        if not isinstance(recorded_inputs, list):
            continue
        if input_fact_ids.intersection(
            item for item in recorded_inputs if isinstance(item, int)
        ):
            fact.is_current = False
            session.add(fact)


def publish_sec_metric_facts(
    session: Session,
    *,
    stock_id: int,
    cutoff: datetime,
    mapping_version: str,
) -> SecMetricPublicationReport:
    if cutoff.tzinfo is None:
        raise SecFinancialIngestionError("cutoff must be timezone-aware")
    rules, sec_policy = _load_rules(mapping_version)
    mapping_known_at_raw = sec_policy.get("known_at")
    if not isinstance(mapping_known_at_raw, str):
        raise SecFinancialIngestionError("SEC mapping known_at is required")
    mapping_known_at = datetime.fromisoformat(
        mapping_known_at_raw.replace("Z", "+00:00")
    )
    if mapping_known_at.tzinfo is None:
        mapping_known_at = mapping_known_at.replace(tzinfo=timezone.utc)
    if mapping_known_at > cutoff:
        raise SecFinancialIngestionError("mapping_not_known_at_cutoff")
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"sec-metric-publication:{stock_id}:{mapping_version}"},
    )
    evidence = select_sec_financial_evidence_as_of(
        session, stock_id=stock_id, cutoff=cutoff
    )
    database_now = session.scalar(select(func.clock_timestamp()))
    if database_now is None:
        raise SecFinancialIngestionError("database_time_unavailable")
    current_evidence = select_sec_financial_evidence_as_of(
        session,
        stock_id=stock_id,
        cutoff=database_now,
    )
    if {item.parse_run_id for item in evidence} != {
        item.parse_run_id for item in current_evidence
    }:
        raise SecFinancialIngestionError("historical_publication_not_allowed")
    run_ids = [item.parse_run_id for item in evidence]
    if not run_ids:
        return SecMetricPublicationReport(
            stock_id=stock_id,
            mapping_version=mapping_version,
            eligible_filing_count=0,
            created_count=0,
            published_count=0,
            unresolved_count=0,
            rejected_count=0,
        )
    existing_raw_ids = set(
        session.scalars(
            select(SecMetricPublication.raw_fact_id).where(
                SecMetricPublication.mapping_version == mapping_version,
                SecMetricPublication.publication_role == "direct",
                SecMetricPublication.raw_fact_id.in_(
                    select(SecRawXbrlFact.id).where(
                        SecRawXbrlFact.parse_run_id.in_(run_ids)
                    )
                ),
            )
        ).all()
    )
    rows = session.execute(
        select(SecRawXbrlFact, SecFinancialParseRun, SecFinancialFiling)
        .join(
            SecFinancialParseRun,
            SecFinancialParseRun.id == SecRawXbrlFact.parse_run_id,
        )
        .join(
            SecFinancialFiling,
            SecFinancialFiling.id == SecFinancialParseRun.filing_id,
        )
        .join(
            SecIssuerIdentity,
            SecIssuerIdentity.id == SecFinancialFiling.issuer_identity_id,
        )
        .where(
            SecRawXbrlFact.parse_run_id.in_(run_ids),
            SecRawXbrlFact.created_at <= cutoff,
            SecIssuerIdentity.stock_id == stock_id,
        )
        .order_by(
            SecFinancialFiling.accepted_at.asc(),
            SecFinancialFiling.id.asc(),
            SecRawXbrlFact.id.asc(),
        )
    ).all()
    decisions = [
        _decision_for_raw(
            raw=raw,
            run=run,
            filing=filing,
            rules=rules,
            sec_policy=sec_policy,
        )
        for raw, run, filing in rows
        if raw.id not in existing_raw_ids
    ]

    candidates_by_slot: dict[tuple[Any, ...], list[_Decision]] = {}
    for decision in decisions:
        if decision.status != "published":
            continue
        slot = (
            decision.run.id,
            decision.metric_key,
            decision.period_type,
            decision.period_end_date,
            decision.currency,
        )
        candidates_by_slot.setdefault(slot, []).append(decision)
    for candidates in candidates_by_slot.values():
        winner = min(
            candidates,
            key=lambda item: (
                item.concept_priority,
                item.raw.id,
            ),
        )
        for candidate in candidates:
            if candidate is not winner:
                candidate.status = "rejected"
                candidate.reason_code = "duplicate_canonical_slot"

    counts = {"published": 0, "unresolved": 0, "rejected": 0}
    demoted_direct_input_ids: set[int] = set()
    for decision in decisions:
        metric_fact: MetricFact | None = None
        if decision.status == "published":
            demoted_direct_input_ids.update(
                session.scalars(
                    select(MetricFact.id)
                    .join(
                        SecMetricPublication,
                        SecMetricPublication.metric_fact_id == MetricFact.id,
                    )
                    .where(
                        MetricFact.user_id.is_(None),
                        MetricFact.stock_id == stock_id,
                        MetricFact.metric_key == decision.metric_key,
                        MetricFact.period_type == decision.period_type,
                        MetricFact.period_end_date == decision.period_end_date,
                        MetricFact.source_type == "sec",
                        MetricFact.is_current.is_(True),
                        MetricFact.value_json["mapping_version"].as_string()
                        == mapping_version,
                        SecMetricPublication.mapping_version == mapping_version,
                        SecMetricPublication.publication_role == "direct",
                        SecMetricPublication.status == "published",
                    )
                ).all()
            )
            session.execute(
                update(MetricFact)
                .where(
                    MetricFact.user_id.is_(None),
                    MetricFact.stock_id == stock_id,
                    MetricFact.metric_key == decision.metric_key,
                    MetricFact.period_type == decision.period_type,
                    MetricFact.period_end_date == decision.period_end_date,
                    MetricFact.source_type == "sec",
                    MetricFact.is_current.is_(True),
                    MetricFact.value_json["mapping_version"].as_string()
                    == mapping_version,
                )
                .values(is_current=False)
            )
            metric_fact = MetricFact(
                user_id=None,
                stock_id=stock_id,
                metric_key=decision.metric_key,
                value_numeric=decision.value_numeric,
                value_json={
                    "fact_nature": sec_policy["fact_nature"],
                    "source_role": sec_policy["source_role"],
                    "source_accession": decision.filing.accession_no,
                    "filing_form": decision.filing.form_type,
                    "filing_id": decision.filing.id,
                    "parse_run_id": decision.run.id,
                    "parser_version": decision.run.parser_version,
                    "raw_fact_id": decision.raw.id,
                    "artifact_id": decision.raw.artifact_id,
                    "mapping_version": mapping_version,
                    "mapping_known_at": mapping_known_at.isoformat(),
                    "knowledge_at": decision.knowledge_at.isoformat(),
                    "period_start": (
                        decision.period_start_date.isoformat()
                        if decision.period_start_date
                        else None
                    ),
                    "period_end": decision.period_end_date.isoformat(),
                    "context_id": decision.raw.context_id,
                    "dimensions_policy": sec_policy["dimensions_policy"],
                    "dimensions": decision.raw.dimensions_json,
                    "unit_measure": decision.raw.unit_measure,
                    "decimals": decision.raw.decimals,
                    "scale": decision.raw.scale,
                    "locator": decision.raw.locator_json,
                    "value_basis": "as_filed",
                },
                unit=decision.unit,
                currency=decision.currency,
                period_type=decision.period_type,
                period_end_date=decision.period_end_date,
                as_of_date=decision.knowledge_at.date(),
                source_type="sec",
                source_ref_id=decision.raw.id,
                is_current=True,
            )
            session.add(metric_fact)
            session.flush()
            decision.metric_fact_id = metric_fact.id
        session.add(
            SecMetricPublication(
                raw_fact_id=decision.raw.id,
                metric_fact_id=metric_fact.id if metric_fact else None,
                mapping_version=mapping_version,
                publication_role="direct",
                derivation_key="direct",
                status=decision.status,
                reason_code=decision.reason_code,
                canonical_metric_key=decision.metric_key,
                canonical_unit=decision.unit,
                period_type=decision.period_type,
                period_end_date=decision.period_end_date,
                knowledge_at=decision.knowledge_at,
                decision_json={
                    "concept": decision.raw.concept,
                    "context_id": decision.raw.context_id,
                    "unit_measure": decision.raw.unit_measure,
                    "dimensions": decision.raw.dimensions_json,
                    "filing_id": decision.filing.id,
                    "parse_run_id": decision.run.id,
                },
            )
        )
        counts[decision.status] += 1

    # A successful newer parse is authoritative for its filing even when it
    # omits or rejects a concept that an older parser published. Preserve the
    # prior fact as history, but remove it from the current projection before
    # rebuilding any downstream derivations.
    for item in evidence:
        demoted_direct_input_ids.update(
            session.scalars(
                select(MetricFact.id)
                .join(
                    SecRawXbrlFact,
                    SecRawXbrlFact.id == MetricFact.source_ref_id,
                )
                .join(
                    SecFinancialParseRun,
                    SecFinancialParseRun.id == SecRawXbrlFact.parse_run_id,
                )
                .join(
                    SecMetricPublication,
                    SecMetricPublication.metric_fact_id == MetricFact.id,
                )
                .where(
                    MetricFact.user_id.is_(None),
                    MetricFact.stock_id == stock_id,
                    MetricFact.source_type == "sec",
                    MetricFact.is_current.is_(True),
                    MetricFact.value_json["mapping_version"].as_string()
                    == mapping_version,
                    SecFinancialParseRun.filing_id == item.filing_id,
                    SecFinancialParseRun.id != item.parse_run_id,
                    SecMetricPublication.mapping_version == mapping_version,
                    SecMetricPublication.publication_role == "direct",
                    SecMetricPublication.status == "published",
                )
            ).all()
        )
        session.execute(
            update(MetricFact)
            .where(
                MetricFact.user_id.is_(None),
                MetricFact.stock_id == stock_id,
                MetricFact.source_type == "sec",
                MetricFact.is_current.is_(True),
                MetricFact.value_json["mapping_version"].as_string()
                == mapping_version,
                MetricFact.source_ref_id.in_(
                    select(SecRawXbrlFact.id)
                    .join(
                        SecFinancialParseRun,
                        SecFinancialParseRun.id == SecRawXbrlFact.parse_run_id,
                    )
                    .where(
                        SecFinancialParseRun.filing_id == item.filing_id,
                        SecFinancialParseRun.id != item.parse_run_id,
                    )
                ),
            )
            .values(is_current=False)
        )
    _demote_derived_facts_using_inputs(
        session,
        stock_id=stock_id,
        mapping_version=mapping_version,
        input_fact_ids=demoted_direct_input_ids,
    )
    session.flush()

    # Re-evaluate every current YTD input, not merely raw facts first seen in
    # this call. An amendment to an earlier YTD changes the input signature of
    # later discrete quarters and must append a corrected result.
    ytd_rows = session.execute(
        select(
            MetricFact,
            SecRawXbrlFact,
            SecFinancialParseRun,
            SecFinancialFiling,
        )
        .join(SecRawXbrlFact, SecRawXbrlFact.id == MetricFact.source_ref_id)
        .join(
            SecFinancialParseRun,
            SecFinancialParseRun.id == SecRawXbrlFact.parse_run_id,
        )
        .join(
            SecFinancialFiling,
            SecFinancialFiling.id == SecFinancialParseRun.filing_id,
        )
        .join(
            SecMetricPublication,
            SecMetricPublication.metric_fact_id == MetricFact.id,
        )
        .where(
            MetricFact.user_id.is_(None),
            MetricFact.stock_id == stock_id,
            MetricFact.source_type == "sec",
            MetricFact.period_type == "YTD",
            MetricFact.is_current.is_(True),
            MetricFact.value_json["value_basis"].as_string() == "as_filed",
            SecRawXbrlFact.parse_run_id.in_(run_ids),
            SecMetricPublication.mapping_version == mapping_version,
            SecMetricPublication.publication_role == "direct",
            SecMetricPublication.status == "published",
        )
        .order_by(MetricFact.period_end_date.asc(), MetricFact.id.asc())
    ).all()
    ytd_decisions = [
        _Decision(
            raw=raw,
            filing=filing,
            run=run,
            knowledge_at=_knowledge_at(raw, run, filing),
            status="published",
            reason_code=None,
            metric_key=fact.metric_key,
            value_numeric=fact.value_numeric,
            unit=fact.unit,
            currency=fact.currency,
            period_type=fact.period_type,
            period_end_date=fact.period_end_date,
            period_start_date=raw.period_start,
            metric_fact_id=fact.id,
        )
        for fact, raw, run, filing in ytd_rows
        if fact.value_numeric is not None and fact.period_end_date is not None
    ]

    derived_created_count = 0
    for decision in ytd_decisions:
        derived_status = "rejected"
        derived_reason = "prior_ytd_missing"
        derived_fact: MetricFact | None = None
        direct_quarter = session.scalar(
            select(MetricFact)
            .join(
                SecMetricPublication,
                SecMetricPublication.metric_fact_id == MetricFact.id,
            )
            .where(
                MetricFact.user_id.is_(None),
                MetricFact.stock_id == stock_id,
                MetricFact.metric_key == decision.metric_key,
                MetricFact.period_type == "Q",
                MetricFact.period_end_date == decision.period_end_date,
                MetricFact.currency == decision.currency,
                MetricFact.source_type == "sec",
                MetricFact.is_current.is_(True),
                MetricFact.value_json["value_basis"].as_string() == "as_filed",
                SecMetricPublication.mapping_version == mapping_version,
                SecMetricPublication.publication_role == "direct",
                SecMetricPublication.status == "published",
            )
            .limit(1)
        )
        prior_ytd: MetricFact | None = None
        if direct_quarter is not None:
            derived_reason = "direct_quarter_available"
        elif decision.period_start_date is not None:
            prior_rows = session.scalars(
                select(MetricFact)
                .join(
                    SecMetricPublication,
                    SecMetricPublication.metric_fact_id == MetricFact.id,
                )
                .where(
                    MetricFact.user_id.is_(None),
                    MetricFact.stock_id == stock_id,
                    MetricFact.metric_key == decision.metric_key,
                    MetricFact.period_type == "YTD",
                    MetricFact.period_end_date < decision.period_end_date,
                    MetricFact.currency == decision.currency,
                    MetricFact.source_type == "sec",
                    MetricFact.is_current.is_(True),
                    SecMetricPublication.mapping_version == mapping_version,
                    SecMetricPublication.publication_role == "direct",
                    SecMetricPublication.status == "published",
                )
                .order_by(MetricFact.period_end_date.desc(), MetricFact.id.desc())
            ).all()
            prior_ytd = next(
                (
                    item
                    for item in prior_rows
                    if isinstance(item.value_json, dict)
                    and item.value_json.get("period_start")
                    == decision.period_start_date.isoformat()
                ),
                None,
            )
        derived_value: float | None = None
        derived_knowledge_at = decision.knowledge_at
        if prior_ytd is not None and prior_ytd.value_numeric is not None:
            delta_days = (decision.period_end_date - prior_ytd.period_end_date).days
            quarter_min, quarter_max = sec_policy["period_policy"][
                "discrete_quarter_duration_days"
            ]
            if quarter_min <= delta_days <= quarter_max:
                derived_status = "published"
                derived_reason = None
                derived_value = decision.value_numeric - prior_ytd.value_numeric
                prior_knowledge_raw = (
                    prior_ytd.value_json.get("knowledge_at")
                    if isinstance(prior_ytd.value_json, dict)
                    else None
                )
                if isinstance(prior_knowledge_raw, str):
                    prior_knowledge_at = datetime.fromisoformat(
                        prior_knowledge_raw.replace("Z", "+00:00")
                    )
                    derived_knowledge_at = max(
                        derived_knowledge_at,
                        prior_knowledge_at,
                    )
            else:
                derived_reason = "prior_ytd_interval_invalid"
        elif prior_ytd is not None:
            derived_reason = "prior_ytd_value_missing"

        derivation_key = hashlib.sha256(
            (
                f"current={decision.metric_fact_id};"
                f"prior={prior_ytd.id if prior_ytd else 'none'};"
                f"direct={direct_quarter.id if direct_quarter else 'none'};"
                f"status={derived_status};reason={derived_reason or 'none'}"
            ).encode("utf-8")
        ).hexdigest()
        if session.scalar(
            select(SecMetricPublication.id).where(
                SecMetricPublication.raw_fact_id == decision.raw.id,
                SecMetricPublication.mapping_version == mapping_version,
                SecMetricPublication.publication_role
                == "derived_discrete_quarter",
                SecMetricPublication.derivation_key == derivation_key,
            )
        ):
            continue

        if derived_status == "published" and derived_value is not None:
            session.execute(
                update(MetricFact)
                .where(
                    MetricFact.user_id.is_(None),
                    MetricFact.stock_id == stock_id,
                    MetricFact.metric_key == decision.metric_key,
                    MetricFact.period_type == "Q",
                    MetricFact.period_end_date == decision.period_end_date,
                    MetricFact.source_type == "sec",
                    MetricFact.is_current.is_(True),
                    MetricFact.value_json["mapping_version"].as_string()
                    == mapping_version,
                )
                .values(is_current=False)
            )
            current_ytd = session.get(MetricFact, decision.metric_fact_id)
            if current_ytd is None or prior_ytd is None:
                raise SecFinancialIngestionError(
                    "derived quarter inputs disappeared during publication"
                )
            derived_fact = MetricFact(
                user_id=None,
                stock_id=stock_id,
                metric_key=decision.metric_key,
                value_numeric=derived_value,
                value_json={
                    "fact_nature": sec_policy["fact_nature"],
                    "source_role": sec_policy["source_role"],
                    "source_accession": decision.filing.accession_no,
                    "filing_form": decision.filing.form_type,
                    "filing_id": decision.filing.id,
                    "parse_run_id": decision.run.id,
                    "parser_version": decision.run.parser_version,
                    "raw_fact_id": decision.raw.id,
                    "artifact_id": decision.raw.artifact_id,
                    "mapping_version": mapping_version,
                    "mapping_known_at": mapping_known_at.isoformat(),
                    "knowledge_at": derived_knowledge_at.isoformat(),
                    "period_start": (
                        (prior_ytd.period_end_date + timedelta(days=1)).isoformat()
                    ),
                    "period_end": decision.period_end_date.isoformat(),
                    "context_id": decision.raw.context_id,
                    "dimensions_policy": sec_policy["dimensions_policy"],
                    "dimensions": decision.raw.dimensions_json,
                    "unit_measure": decision.raw.unit_measure,
                    "decimals": decision.raw.decimals,
                    "scale": decision.raw.scale,
                    "value_basis": "derived_discrete_quarter",
                    "derivation": "current_ytd_minus_prior_ytd",
                    "input_metric_fact_ids": [
                        prior_ytd.id,
                        decision.metric_fact_id,
                    ],
                    "input_raw_fact_ids": [
                        prior_ytd.source_ref_id,
                        decision.raw.id,
                    ],
                    "input_provenance": [
                        _input_provenance(prior_ytd),
                        _input_provenance(current_ytd),
                    ],
                    "locator": decision.raw.locator_json,
                },
                unit=decision.unit,
                currency=decision.currency,
                period_type="Q",
                period_end_date=decision.period_end_date,
                as_of_date=derived_knowledge_at.date(),
                source_type="sec",
                source_ref_id=decision.raw.id,
                is_current=True,
            )
            session.add(derived_fact)
            session.flush()
        session.add(
            SecMetricPublication(
                raw_fact_id=decision.raw.id,
                metric_fact_id=derived_fact.id if derived_fact else None,
                mapping_version=mapping_version,
                publication_role="derived_discrete_quarter",
                derivation_key=derivation_key,
                status=derived_status,
                reason_code=derived_reason,
                canonical_metric_key=decision.metric_key,
                canonical_unit=decision.unit,
                period_type="Q" if derived_fact else None,
                period_end_date=(decision.period_end_date if derived_fact else None),
                knowledge_at=derived_knowledge_at,
                decision_json={
                    "concept": decision.raw.concept,
                    "filing_id": decision.filing.id,
                    "parse_run_id": decision.run.id,
                    "prior_ytd_metric_fact_id": prior_ytd.id if prior_ytd else None,
                },
            )
        )
        counts[derived_status] += 1
        derived_created_count += 1

    session.commit()
    return SecMetricPublicationReport(
        stock_id=stock_id,
        mapping_version=mapping_version,
        eligible_filing_count=len(evidence),
        created_count=len(decisions) + derived_created_count,
        published_count=counts["published"],
        unresolved_count=counts["unresolved"],
        rejected_count=counts["rejected"],
    )
