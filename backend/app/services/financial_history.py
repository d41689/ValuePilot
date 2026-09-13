"""Presentation projection over guard-returned facts, not a source selector."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from hashlib import sha256
import json
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.models.facts import MetricFact
from app.schemas.financial_history import AnnualWindow, FinancialHistory, FinancialHistoryRow
from app.services.evaluation_snapshot import EvaluationSnapshot
from app.services.source_reconciliation import materialize_reconciliation_candidates


CORE_METRIC_KEYS = (
    "is.revenue", "is.net_income", "is.operating_cash_flow",
    "cf.capital_expenditures", "bs.cash_and_equivalents",
    "cap.long_term_debt_current", "cap.long_term_debt_noncurrent",
    "equity.weighted_average_diluted_shares", "cf.stock_based_compensation",
)


def _is_annual_actual(row: FinancialHistoryRow) -> bool:
    return (row.row_kind == "fact" and row.period_type == "FY"
            and row.fact_nature in {"actual", "derived_actual"}
            and row.fiscal_year is not None
            and row.period_basis in {"instant", "duration"})


def _sort_key(row: FinancialHistoryRow) -> tuple:
    key = row.metric_key or ""
    return (
        CORE_METRIC_KEYS.index(key) if key in CORE_METRIC_KEYS else len(CORE_METRIC_KEYS),
        "" if key in CORE_METRIC_KEYS else key,
        -(row.fiscal_year or 0), -(row.period_end or date.min).toordinal(),
        row.period_basis or "", row.source_type or "", row.source_role or "",
        row.fact_nature or "", row.row_key,
    )


def project_financial_history(*, stock_id: int, evaluated_at: datetime,
                              rows: Iterable[FinancialHistoryRow]) -> FinancialHistory:
    rows = list(rows)
    # An anchor requires proven annual source metadata and an ended period.
    # Other observations stay visible but do not invent a fiscal calendar.
    anchors = [row for row in rows if _is_annual_actual(row)
               and row.fact_nature == "actual"
               and row.source_role in {"primary_as_filed_actual", "value_line_adjusted_actual"}
               and row.period_end is not None and row.period_end <= evaluated_at.date()
               and (row.comparison_identity or {}).get("identity_complete") is True]
    if anchors:
        anchor = sorted(anchors, key=lambda r: (r.fiscal_year, r.period_end, -r.fact_id))[-1]
        years = list(range(anchor.fiscal_year - 9, anchor.fiscal_year + 1))
        window = AnnualWindow(status="determined", years=years, anchor_fact_id=anchor.fact_id)
        observed = {(row.metric_key, row.fiscal_year) for row in rows if _is_annual_actual(row)}
        blocked_metrics = {row.metric_key for row in rows if row.row_kind == "metric_state"}
        blocked_cells = {(row.metric_key, row.fiscal_year) for row in rows
                         if row.row_kind == "slot_state" and row.period_type == "FY"
                         and row.fiscal_year is not None}
        # A cycle state covers cells only when its source supplies explicit
        # metric/year scope. An unknown cycle must remain visible, not guessed.
        for row in rows:
            if row.row_kind == "filing_cycle_state" and row.scope:
                for key in row.scope.get("metric_keys", []):
                    for year in row.scope.get("fiscal_years", []):
                        blocked_cells.add((key, year))
        for key in CORE_METRIC_KEYS:
            for year in years:
                if key in blocked_metrics or (key, year) in observed | blocked_cells:
                    continue
                rows.append(FinancialHistoryRow(
                    row_kind="slot_state", status="unavailable", reason_code="not_returned",
                    row_key=f"expected:{stock_id}:{key}:FY:{year}:not_returned",
                    metric_key=key, period_type="FY", fiscal_year=year,
                ))
    else:
        window = AnnualWindow(status="undetermined", reason_code="annual_window_unproven")
    rows.sort(key=_sort_key)
    count = sum(row.row_kind == "fact" for row in rows)
    return FinancialHistory(evaluated_at=evaluated_at, annual_window=window,
                            total_rows=len(rows), available_fact_count=count,
                            state_count=len(rows) - count, rows=rows)


def _state_row(stock_id: int, state: dict[str, Any]) -> FinancialHistoryRow:
    metric = state.get("metric_key")
    period_type = state.get("period_type") or state.get("period")
    kind = ("filing_cycle_state" if not metric else
            "slot_state" if period_type or state.get("period_end_date") else "metric_state")
    # Include all non-value scope supplied by the existing state producer. Two
    # different source/period/run failures must not collapse by metric alone.
    scope = {key: value for key, value in state.items()
             if key not in {"id", "value_numeric", "value_text", "original_evidence_route", "evidence_route"}}
    encoded = json.dumps({"stock_id": stock_id, **scope}, sort_keys=True, default=str, separators=(",", ":"))
    publication_id = state.get("publication_id")
    reason = state.get("reason_code")
    row_key = (f"publication:{publication_id}:{reason}" if publication_id is not None
               else f"{kind}:{sha256(encoded.encode()).hexdigest()}")
    return FinancialHistoryRow(
        row_kind=kind, row_key=row_key, status=state.get("status") or "unavailable",
        reason_code=reason, metric_key=metric, publication_id=publication_id,
        period_type=period_type, period_end=state.get("period_end_date"),
        period_start=state.get("period_start_date"), period_basis=state.get("period_basis"),
        fiscal_year=state.get("fiscal_year"), fiscal_quarter=state.get("fiscal_quarter_ordinal"),
        source_type=state.get("source_type"), scope=scope,
    )


def build_financial_history(session: Session, *, stock_id: int, user_id: int,
                            facts: list[MetricFact], states: list[dict[str, Any]],
                            evaluation_snapshot: EvaluationSnapshot) -> FinancialHistory:
    """Caller supplies only the final guard-returned set, including text facts.

    Metadata is materialized per complete metric, using the shared adapter and
    snapshot. This does not perform another source election or fetch evidence.
    """
    by_metric = defaultdict(list)
    for fact in facts:
        by_metric[fact.metric_key].append(fact)
    descriptors = {}
    for unit in by_metric.values():
        candidates, _ = materialize_reconciliation_candidates(
            session, unit, user_id=user_id, evaluation_snapshot=evaluation_snapshot,
        )
        descriptors.update({candidate.fact_id: candidate for candidate in candidates})
    rows = []
    for fact in facts:
        candidate = descriptors.get(fact.id)
        identity = None
        if candidate:
            identity = {key: getattr(candidate, key) for key in (
                "definition_family", "definition_basis", "definition_id", "mapping_version",
                "source_mapping_version", "dimensions_identity", "source_identity",
                "duration_days", "period_duration_kind", "identity_complete",
            )}
        capability = ("sec_statement" if fact.source_type == "sec" and fact.source_ref_id
                      else "document_review" if fact.source_document_id else "reference_only")
        rows.append(FinancialHistoryRow(
            row_kind="fact", row_key=f"fact:{fact.id}", status="available",
            fact_id=fact.id, metric_key=fact.metric_key,
            publication_id=fact.source_ref_id if fact.source_type == "sec" else None,
            value_numeric_exact=format(fact.value_numeric, "f") if fact.value_numeric is not None else None,
            value_text=fact.value_text, unit=fact.unit, currency=fact.currency,
            period_type=fact.period_type, period_end=fact.period_end_date,
            period_start=candidate.period_start_date if candidate else None,
            period_basis=candidate.period_basis if candidate else None,
            fiscal_year=candidate.fiscal_year if candidate else None,
            fiscal_quarter=candidate.fiscal_quarter_ordinal if candidate else None,
            source_type=fact.source_type, source_role=candidate.source_role if candidate else None,
            fact_nature=candidate.fact_nature if candidate else None,
            comparison_identity=identity, evidence_capability=capability,
            document_id=fact.source_document_id,
        ))
    unique_states = {}
    for state in states:
        row = _state_row(stock_id, state)
        if row.row_key in unique_states and unique_states[row.row_key] != row:
            raise ValueError("different financial states have the same publication identity")
        unique_states[row.row_key] = row
    rows.extend(unique_states.values())
    return project_financial_history(stock_id=stock_id, evaluated_at=evaluation_snapshot.cutoff, rows=rows)
