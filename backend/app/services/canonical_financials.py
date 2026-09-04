"""Shared canonical-financial visibility, source, method, and evidence guards.

Fundamental values are always read from ``metric_facts``.  SEC lineage tables
are used only to resolve bounded evidence for a selected canonical fact or a
typed unavailable publication decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import re
from typing import Any, Iterable

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from app.models.facts import MetricFact


CANONICAL_SOURCE_TYPES = frozenset({"sec", "parsed", "manual", "calculated"})
SYSTEM_METHOD_KEYS = frozenset(
    {"owner_earnings", "roic", "per_share_trend", "system_valuation"}
)


class CanonicalSourceConflictError(ValueError):
    code = "source_conflict"

    def __init__(self, *, consumer: str, source_types: Iterable[str]):
        self.consumer = consumer
        self.source_types = tuple(sorted(set(source_types)))
        super().__init__(
            f"{consumer} requires an explicit source selection; available sources: "
            + ", ".join(self.source_types)
        )


class UnsupportedSystemMethodError(ValueError):
    code = "unsupported"

    def __init__(self, decision: "MethodGateDecision"):
        self.decision = decision
        super().__init__(f"{decision.method_key} is unsupported: {decision.reason_code}")


class CanonicalUnavailableError(ValueError):
    def __init__(self, state: dict[str, Any]):
        self.state = state
        self.code = str(state["reason_code"])
        super().__init__(f"canonical SEC facts are unavailable: {self.code}")


@dataclass(frozen=True)
class MethodGateDecision:
    method_key: str
    status: str
    reason_code: str
    method_policy_version_id: str | None
    economic_class: str
    classification_review_id: int | None
    effective_as_of: date
    knowledge_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "method_key": self.method_key,
            "status": self.status,
            "reason_code": self.reason_code,
            "method_policy_version_id": self.method_policy_version_id,
            "economic_class": self.economic_class,
            "classification_review_id": self.classification_review_id,
            "effective_as_of": self.effective_as_of.isoformat(),
            "knowledge_at": self.knowledge_at.isoformat(),
        }


def visible_metric_fact_predicate(fact_entity: Any, *, user_id: int):
    """SEC is shared; every non-SEC fact remains owned by the requesting user."""

    return or_(
        and_(fact_entity.source_type == "sec", fact_entity.user_id.is_(None)),
        and_(fact_entity.source_type != "sec", fact_entity.user_id == user_id),
    )


def _fact_source_type(fact: Any) -> str | None:
    """Return the fact's canonical role without interpreting lineage metadata."""

    source_type = (
        fact.get("source_type") if isinstance(fact, dict) else getattr(fact, "source_type", None)
    )
    return source_type if isinstance(source_type, str) and source_type else None


def guard_source_selection(
    facts: Iterable[Any],
    *,
    consumer: str,
    selected_source_type: str | None = None,
) -> list[Any]:
    """Reject implicit cross-source precedence and return the bounded selection."""

    materialized = list(facts)
    if selected_source_type is not None:
        if selected_source_type not in CANONICAL_SOURCE_TYPES:
            raise ValueError("unsupported source_type selection")
        return [
            fact
            for fact in materialized
            if selected_source_type == _fact_source_type(fact)
        ]
    source_types = {
        source_type
        for fact in materialized
        if (source_type := _fact_source_type(fact)) is not None
    }
    if len(source_types) > 1:
        raise CanonicalSourceConflictError(consumer=consumer, source_types=source_types)
    return materialized


def reviewed_method_gate(
    session: Session,
    *,
    stock_id: int,
    method_key: str,
    effective_as_of: date,
    knowledge_at: datetime | None = None,
) -> MethodGateDecision:
    """Resolve the reviewed effective/knowledge-dated method authority."""

    if method_key not in SYSTEM_METHOD_KEYS:
        raise ValueError("unsupported method_key")
    cutoff = knowledge_at or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        raise ValueError("knowledge_at must be timezone-aware")
    policy = session.execute(
        text(
            """
            SELECT id
            FROM sec_method_policy_versions
            WHERE status='approved' AND effective_from<=:cutoff AND known_at<=:cutoff
              AND NOT EXISTS (
                SELECT 1 FROM sec_method_policy_versions later
                WHERE later.status='approved' AND later.effective_from<=:cutoff
                  AND later.known_at<=:cutoff
                  AND (later.effective_from, later.known_at, later.id)>
                      (sec_method_policy_versions.effective_from,
                       sec_method_policy_versions.known_at,
                       sec_method_policy_versions.id)
              )
            LIMIT 1
            """
        ),
        {"cutoff": cutoff},
    ).mappings().first()
    if policy is None:
        return MethodGateDecision(
            method_key, "unsupported", "method_policy_unavailable", None,
            "unclassified", None, effective_as_of, cutoff,
        )
    classification = session.execute(
        text(
            """
            SELECT r.id, r.economic_class
            FROM sec_economic_classification_reviews r
            WHERE r.stock_id=:stock_id AND r.effective_from<=:as_of
              AND (r.effective_to IS NULL OR r.effective_to>=:as_of)
              AND r.known_at<=:cutoff
              AND NOT EXISTS (
                SELECT 1 FROM sec_economic_classification_reviews later
                WHERE later.supersedes_review_id=r.id AND later.known_at<=:cutoff
              )
            ORDER BY r.known_at DESC, r.id DESC
            LIMIT 1
            """
        ),
        {"stock_id": stock_id, "as_of": effective_as_of, "cutoff": cutoff},
    ).mappings().first()
    economic_class = classification.economic_class if classification else "unclassified"
    rule = session.execute(
        text(
            """
            SELECT applicability
            FROM sec_method_policy_rules
            WHERE method_policy_version_id=:policy_id
              AND method_key=:method_key AND economic_class=:economic_class
            """
        ),
        {
            "policy_id": policy.id,
            "method_key": method_key,
            "economic_class": economic_class,
        },
    ).mappings().first()
    approved = bool(rule and rule.applicability == "approved" and classification)
    reason = (
        "approved"
        if approved
        else "classification_unreviewed"
        if classification is None
        else "method_not_approved"
        if rule is None
        else "method_unsupported"
    )
    return MethodGateDecision(
        method_key=method_key,
        status="approved" if approved else "unsupported",
        reason_code=reason,
        method_policy_version_id=policy.id,
        economic_class=economic_class,
        classification_review_id=classification.id if classification else None,
        effective_as_of=effective_as_of,
        knowledge_at=cutoff,
    )


def require_reviewed_method(*args: Any, **kwargs: Any) -> MethodGateDecision:
    decision = reviewed_method_gate(*args, **kwargs)
    if decision.status != "approved":
        raise UnsupportedSystemMethodError(decision)
    return decision


def _system_method_for_fact(fact: MetricFact) -> str | None:
    metadata = fact.value_json if isinstance(fact.value_json, dict) else {}
    if metadata.get("user_authored_formula") is True:
        return None
    key = fact.metric_key
    if key.startswith("owners_earnings_per_share"):
        return "owner_earnings"
    if key in {"returns.roic", "roic"} or key.startswith("returns.roic."):
        return "roic"
    if key.startswith("per_share_trend.") or key.startswith("trend.per_share."):
        return "per_share_trend"
    if key.startswith("system_valuation."):
        return "system_valuation"
    return None


def apply_reviewed_method_gates(
    session: Session,
    *,
    stock_id: int,
    facts: Iterable[MetricFact],
    effective_as_of: date,
    knowledge_at: datetime | None = None,
    precomputed_decisions: dict[str, MethodGateDecision] | None = None,
) -> tuple[list[MetricFact], list[dict[str, Any]], dict[str, MethodGateDecision]]:
    """Remove unsupported system outputs while preserving raw and user-authored facts."""

    materialized = list(facts)
    required_methods = {
        method for fact in materialized if (method := _system_method_for_fact(fact))
    }
    decisions = {
        method: (
            precomputed_decisions[method]
            if precomputed_decisions is not None and method in precomputed_decisions
            else reviewed_method_gate(
                session,
                stock_id=stock_id,
                method_key=method,
                effective_as_of=effective_as_of,
                knowledge_at=knowledge_at,
            )
        )
        for method in sorted(required_methods)
    }
    kept: list[MetricFact] = []
    blocked: list[dict[str, Any]] = []
    for fact in materialized:
        method = _system_method_for_fact(fact)
        decision = decisions.get(method) if method else None
        if decision is None or decision.status == "approved":
            kept.append(fact)
            continue
        blocked.append(
            {
                "id": None,
                "status": "unsupported",
                "reason_code": decision.reason_code,
                "method_key": method,
                "metric_key": fact.metric_key,
                "value_numeric": None,
                "unit": None,
                "period": fact.period_type,
                "period_end_date": fact.period_end_date,
                "source_type": fact.source_type,
                "method_gate": decision.as_dict(),
                "evidence_route": None,
            }
        )
    return kept, blocked, decisions


def current_visible_facts(
    session: Session, *, stock_id: int, user_id: int
) -> list[MetricFact]:
    return list(
        session.scalars(
            select(MetricFact).where(
                MetricFact.stock_id == stock_id,
                MetricFact.is_current.is_(True),
                visible_metric_fact_predicate(MetricFact, user_id=user_id),
            )
        ).all()
    )


def active_sec_run_unresolved_states(
    session: Session, *, stock_id: int
) -> list[dict[str, Any]]:
    """Return unresolved amendment states bounded by filing-cycle authority."""

    rows = session.execute(
        text(
            """
            SELECT DISTINCT ON (failed_filing.id)
                   r.id, r.mapping_version_id,
                   r.requested_cutoff, availability.available_at,
                   audit.reason_code, audit.known_at,
                   failed_filing.report_date, failed_filing.form_type,
                   failed_filing.accession_no
            FROM sec_metric_publication_audits audit
            JOIN sec_metric_publication_runs r ON r.id=audit.publication_run_id
            JOIN sec_metric_publication_availabilities availability
              ON availability.publication_run_id=r.id
            JOIN sec_metric_publication_run_sources failed_source
              ON failed_source.publication_run_id=r.id
            JOIN sec_financial_parse_runs failed_parse
              ON failed_parse.id=failed_source.parse_run_id
            JOIN sec_financial_filings failed_filing
              ON failed_filing.id=failed_source.filing_id
            WHERE r.stock_id=:stock_id AND r.status='succeeded'
              AND audit.reason_code='unresolved_amendment_parse_failure'
              AND failed_parse.status='failed' AND failed_filing.is_amendment
              AND NOT EXISTS (
                SELECT 1
                FROM sec_metric_publication_run_sources later_source
                JOIN sec_metric_publication_runs later_run
                  ON later_run.id=later_source.publication_run_id
                JOIN sec_metric_publication_availabilities later_available
                  ON later_available.publication_run_id=later_run.id
                JOIN sec_financial_parse_runs later_parse
                  ON later_parse.id=later_source.parse_run_id
                WHERE later_source.filing_id=failed_source.filing_id
                  AND later_parse.status='succeeded'
                  AND later_run.status='succeeded'
                  AND later_run.requested_cutoff>=r.requested_cutoff
                  AND later_available.available_at>=availability.available_at
              )
            ORDER BY failed_filing.id, availability.available_at DESC, audit.id DESC
            """
        ),
        {"stock_id": stock_id},
    ).mappings().all()
    return [
        {
            "id": None,
            "status": "unresolved",
            "reason_code": row.reason_code,
            "metric_key": None,
            "value_numeric": None,
            "unit": None,
            "period": "FILING_CYCLE",
            "period_end_date": row.report_date,
            "source_type": "sec",
            "mapping_version": row.mapping_version_id,
            "known_at": row.known_at,
            "requested_knowledge_cutoff": row.requested_cutoff,
            "filing": {
                "accession": row.accession_no,
                "form": row.form_type,
            },
            "filing_cycle": {
                "base_form": row.form_type.removesuffix("/A"),
                "report_date": row.report_date,
            },
            "evidence_route": None,
        }
        for row in rows
    ]


def active_sec_run_unresolved_state(
    session: Session, *, stock_id: int, period_end_date: date | None = None
) -> dict[str, Any] | None:
    """Compatibility accessor, optionally bounded to a requested filing cycle."""

    states = active_sec_run_unresolved_states(session, stock_id=stock_id)
    if period_end_date is not None:
        states = [state for state in states if state["period_end_date"] == period_end_date]
    return states[0] if states else None


def guard_sec_run_availability(
    session: Session, *, stock_id: int, facts: Iterable[Any]
) -> list[Any]:
    materialized, states = partition_sec_run_availability(
        session, stock_id=stock_id, facts=facts
    )
    if states:
        raise CanonicalUnavailableError(states[0])
    return materialized


def sec_fact_filing_cycles(
    session: Session, *, facts: Iterable[Any]
) -> dict[int, set[tuple[str, date]]]:
    """Resolve each SEC publication to every filing cycle used by its inputs."""

    publication_ids = sorted(
        {
            source_ref_id
            for fact in facts
            if _fact_source_type(fact) == "sec"
            and isinstance(
                source_ref_id := (
                    fact.get("source_ref_id")
                    if isinstance(fact, dict)
                    else getattr(fact, "source_ref_id", None)
                ),
                int,
            )
        }
    )
    cycles: dict[int, set[tuple[str, date]]] = {
        publication_id: set() for publication_id in publication_ids
    }
    if not publication_ids:
        return cycles
    rows = session.execute(
        text(
            """
            WITH RECURSIVE lineage(root_publication_id, publication_id) AS (
              SELECT p.id, p.id
              FROM sec_metric_publications p
              WHERE p.id=ANY(:publication_ids)
              UNION
              SELECT lineage.root_publication_id, input.source_publication_id
              FROM lineage
              JOIN sec_metric_publication_inputs input
                ON input.publication_id=lineage.publication_id
              WHERE input.source_publication_id IS NOT NULL
            ), evidence_sources AS (
              SELECT publication_id, run_source_id
              FROM sec_metric_publication_inputs
              WHERE run_source_id IS NOT NULL
              UNION ALL
              SELECT publication_id, run_source_id
              FROM sec_metric_publication_unresolved_inputs
            )
            SELECT DISTINCT lineage.root_publication_id,
                   replace(filing.form_type, '/A', '') AS base_form,
                   filing.report_date
            FROM lineage
            JOIN evidence_sources evidence
              ON evidence.publication_id=lineage.publication_id
            JOIN sec_metric_publication_run_sources source
              ON source.id=evidence.run_source_id
            JOIN sec_financial_filings filing ON filing.id=source.filing_id
            WHERE filing.report_date IS NOT NULL
            """
        ),
        {"publication_ids": publication_ids},
    ).mappings().all()
    for row in rows:
        cycles[row.root_publication_id].add((row.base_form, row.report_date))
    return cycles


def partition_sec_run_availability(
    session: Session, *, stock_id: int, facts: Iterable[Any]
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Exclude only SEC facts in filing cycles with unresolved amendments."""

    materialized = list(facts)
    sec_facts = [fact for fact in materialized if _fact_source_type(fact) == "sec"]
    if not sec_facts:
        return materialized, []
    active_states = active_sec_run_unresolved_states(session, stock_id=stock_id)
    if not active_states:
        return materialized, []
    state_by_cycle = {
        (
            state["filing_cycle"]["base_form"],
            state["filing_cycle"]["report_date"],
        ): state
        for state in active_states
        if state.get("filing_cycle")
        and state["filing_cycle"].get("report_date") is not None
    }
    fact_cycles = sec_fact_filing_cycles(session, facts=sec_facts)
    blocked_fact_ids: set[int] = set()
    states: list[dict[str, Any]] = []
    for fact in sec_facts:
        source_ref_id = (
            fact.get("source_ref_id")
            if isinstance(fact, dict)
            else getattr(fact, "source_ref_id", None)
        )
        cycles = fact_cycles.get(source_ref_id, set())
        matched = [state_by_cycle[cycle] for cycle in cycles if cycle in state_by_cycle]
        if not cycles:
            # A selected SEC fact without canonical publication/input authority
            # cannot prove that it is outside the unresolved amendment cycle.
            matched = active_states
        if matched:
            blocked_fact_ids.add(id(fact))
            for state in matched:
                if state not in states:
                    states.append(state)
    available = [
        fact
        for fact in materialized
        if id(fact) not in blocked_fact_ids
    ]
    return available, states


_SAFE_OCCURRENCE_KEYS = (
    "report_ordinal",
    "occurrence_ordinal",
    "row_ordinal",
    "column_ordinal",
)


def _safe_locator(locator: Any) -> dict[str, Any]:
    if not isinstance(locator, dict):
        return {"kind": "unavailable"}
    occurrences = locator.get("ordered_input_occurrences")
    if not isinstance(occurrences, list):
        occurrences = [locator]
    safe = []
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            continue
        item = {key: occurrence.get(key) for key in _SAFE_OCCURRENCE_KEYS}
        safe.append(item)
    return {
        "kind": "derived_statement_occurrences" if len(safe) > 1 else "statement_occurrence",
        "occurrences": safe,
    }


def _concept_local_name(concept: str | None) -> str | None:
    if not concept:
        return None
    return concept.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _canonical_sec_url(*, cik: str, accession: str, primary_document: str) -> str | None:
    if not re.fullmatch(r"[0-9]{10}", cik):
        return None
    if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession):
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", primary_document):
        return None
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik.lstrip('0')}/{accession.replace('-', '')}/{primary_document}"
    )


def resolve_sec_publication_evidence(
    session: Session, *, stock_id: int, publication_id: int
) -> dict[str, Any] | None:
    decision = session.execute(
        text(
            """
            SELECT p.id, p.status, p.reason_code, p.metric_key, p.period_type,
                   p.period_start_date, p.period_end_date, p.period_basis,
                   p.fiscal_year, p.fiscal_quarter_ordinal,
                   fact.value_numeric AS canonical_value_numeric,
                   p.unit, p.currency, p.source_role, p.fact_nature,
                   p.derivation_kind, p.context_id, p.dimensions_policy,
                   p.locator_json, p.known_at, p.metric_fact_id,
                   r.mapping_version_id, r.requested_cutoff
            FROM sec_metric_publications p
            JOIN sec_metric_publication_runs r ON r.id=p.publication_run_id
            JOIN sec_metric_publication_availabilities a ON a.publication_run_id=r.id
            LEFT JOIN metric_facts fact ON fact.id=p.metric_fact_id
            WHERE p.id=:publication_id AND p.stock_id=:stock_id
              AND r.status='succeeded'
            """
        ),
        {"publication_id": publication_id, "stock_id": stock_id},
    ).mappings().first()
    if decision is None:
        return None
    sources = session.execute(
        text(
            """
            SELECT rs.id AS run_source_id, rs.source_ordinal, rs.parser_version,
                   f.accession_no, f.form_type, f.accepted_at, f.known_at,
                   f.primary_document, issuer.cik
            FROM sec_metric_publications p
            JOIN sec_metric_publication_run_sources rs
              ON rs.publication_run_id=p.publication_run_id
            JOIN sec_financial_filings f ON f.id=rs.filing_id
            JOIN sec_issuer_identities issuer ON issuer.id=f.issuer_identity_id
            WHERE p.id=:publication_id
            ORDER BY rs.source_ordinal
            """
        ),
        {"publication_id": publication_id},
    ).mappings().all()
    filings = [
        {
            "source_ordinal": row.source_ordinal,
            "accession": row.accession_no,
            "form": row.form_type,
            "accepted_at": row.accepted_at.isoformat(),
            "known_at": row.known_at.isoformat(),
            "parser_version": row.parser_version,
            "sec_url": _canonical_sec_url(
                cik=row.cik,
                accession=row.accession_no,
                primary_document=row.primary_document,
            ),
        }
        for row in sources
    ]
    source_by_id = {row.run_source_id: row for row in sources}
    raw_inputs = session.execute(
        text(
            """
            SELECT i.input_ordinal, i.input_role, i.arithmetic_sign,
                   i.run_source_id, i.source_publication_id,
                   raw.concept, raw.concept_namespace_uri, raw.context_id,
                   raw.period_instant, raw.period_start, raw.period_end,
                   raw.unit_numerator_json, raw.unit_denominator_json,
                   n.normalization_version,
                   source.metric_key AS source_metric_key,
                   source.period_type AS source_period_type,
                   source.period_end_date AS source_period_end_date,
                   source_fact.value_numeric AS source_value_numeric,
                   source_fact.unit AS source_unit,
                   source_fact.currency AS source_currency
            FROM sec_metric_publication_inputs i
            LEFT JOIN sec_raw_xbrl_facts raw ON raw.id=i.raw_fact_id
            LEFT JOIN sec_raw_numeric_normalizations n ON n.id=i.normalization_id
            LEFT JOIN sec_metric_publications source ON source.id=i.source_publication_id
            LEFT JOIN metric_facts source_fact ON source_fact.id=source.metric_fact_id
            WHERE i.publication_id=:publication_id
            ORDER BY i.input_ordinal
            """
        ),
        {"publication_id": publication_id},
    ).mappings().all()
    if not raw_inputs and decision.status == "unresolved":
        raw_inputs = session.execute(
            text(
                """
                SELECT i.input_ordinal, 'unresolved_evidence' AS input_role,
                       1 AS arithmetic_sign, i.run_source_id,
                       NULL::bigint AS source_publication_id,
                       raw.concept, raw.concept_namespace_uri, raw.context_id,
                       raw.period_instant, raw.period_start, raw.period_end,
                       raw.unit_numerator_json, raw.unit_denominator_json,
                       n.normalization_version,
                       NULL::text AS source_metric_key,
                       NULL::text AS source_period_type,
                       NULL::date AS source_period_end_date,
                       NULL::numeric AS source_value_numeric,
                       NULL::text AS source_unit, NULL::text AS source_currency
                FROM sec_metric_publication_unresolved_inputs i
                JOIN sec_raw_xbrl_facts raw ON raw.id=i.raw_fact_id
                LEFT JOIN sec_raw_numeric_normalizations n ON n.id=i.normalization_id
                WHERE i.publication_id=:publication_id
                ORDER BY i.input_ordinal
                """
            ),
            {"publication_id": publication_id},
        ).mappings().all()
    inputs: list[dict[str, Any]] = []
    for row in raw_inputs:
        source = source_by_id.get(row.run_source_id)
        payload: dict[str, Any] = {
            "ordinal": row.input_ordinal,
            "role": row.input_role,
            "arithmetic_sign": row.arithmetic_sign,
        }
        if row.source_publication_id is not None:
            payload["kind"] = "canonical_operand"
            payload["canonical_operand"] = {
                "metric_key": row.source_metric_key,
                "period_type": row.source_period_type,
                "period_end_date": row.source_period_end_date.isoformat(),
                "value_numeric": row.source_value_numeric,
                "unit": row.source_unit,
                "currency": row.source_currency,
            }
        else:
            payload.update(
                {
                    "kind": "as_filed_fact_metadata",
                    "accession": source.accession_no if source else None,
                    "form": source.form_type if source else None,
                    "parser_version": source.parser_version if source else None,
                    "concept": {
                        "namespace_uri": row.concept_namespace_uri,
                        "local_name": _concept_local_name(row.concept),
                    },
                    "context_id": row.context_id,
                    "period": {
                        "instant": row.period_instant.isoformat() if row.period_instant else None,
                        "start": row.period_start.isoformat() if row.period_start else None,
                        "end": row.period_end.isoformat() if row.period_end else None,
                    },
                    "unit": {
                        "numerator": row.unit_numerator_json,
                        "denominator": row.unit_denominator_json,
                    },
                    "normalization_version": row.normalization_version,
                }
            )
        inputs.append(payload)
    return {
        "publication_id": decision.id,
        "metric_fact_id": decision.metric_fact_id,
        "status": decision.status,
        "reason_code": decision.reason_code,
        "metric_key": decision.metric_key,
        "value_numeric": decision.canonical_value_numeric,
        "mapping_version": decision.mapping_version_id,
        "known_at": decision.known_at.isoformat(),
        "requested_knowledge_cutoff": decision.requested_cutoff.isoformat(),
        "source_role": decision.source_role,
        "fact_nature": decision.fact_nature,
        "derivation_kind": decision.derivation_kind,
        "context_id": decision.context_id,
        "dimensions_policy": decision.dimensions_policy,
        "period": {
            "type": decision.period_type,
            "basis": decision.period_basis,
            "start": decision.period_start_date.isoformat() if decision.period_start_date else None,
            "end": decision.period_end_date.isoformat(),
            "fiscal_year": decision.fiscal_year,
            "fiscal_quarter": decision.fiscal_quarter_ordinal,
        },
        "unit": decision.unit,
        "currency": decision.currency,
        "filings": filings,
        "inputs": inputs,
        "locator": _safe_locator(decision.locator_json),
    }


def current_sec_unresolved_states(session: Session, *, stock_id: int) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            SELECT ranked.id, ranked.status, ranked.reason_code, ranked.metric_key,
                   ranked.period_type, ranked.period_end_date, ranked.known_at
            FROM (
              SELECT p.*,
                     row_number() OVER (
                       PARTITION BY p.metric_key, p.period_type, p.period_end_date
                       ORDER BY p.known_at DESC, p.id DESC
                     ) AS slot_rank
              FROM sec_metric_publications p
              JOIN sec_metric_publication_runs r ON r.id=p.publication_run_id
              JOIN sec_metric_publication_availabilities a
                ON a.publication_run_id=r.id
              WHERE p.stock_id=:stock_id AND r.status='succeeded'
            ) ranked
            WHERE ranked.slot_rank=1 AND ranked.status IN ('unresolved','rejected')
            ORDER BY ranked.metric_key, ranked.period_end_date
            """
        ),
        {"stock_id": stock_id},
    ).mappings().all()
    states = [
        {
            "id": None,
            "publication_id": row.id,
            "status": row.status,
            "reason_code": row.reason_code,
            "metric_key": row.metric_key,
            "value_numeric": None,
            "unit": None,
            "period": row.period_type,
            "period_end_date": row.period_end_date,
            "source_type": "sec",
            "known_at": row.known_at,
            "evidence_route": f"/api/v1/stocks/{stock_id}/sec-publications/{row.id}/evidence",
        }
        for row in rows
    ]
    states.extend(active_sec_run_unresolved_states(session, stock_id=stock_id))
    return states
