from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact
from app.services.active_report_resolver import ActiveReportSelection


def detect_actual_conflicts(
    session: Session,
    *,
    stock_id: int,
    active_report: ActiveReportSelection | None,
) -> list[dict[str, Any]]:
    fact_nature_expr = MetricFact.value_json["fact_nature"].as_string()
    rows = session.execute(
        select(
            MetricFact.metric_key,
            MetricFact.period_type,
            MetricFact.period_end_date,
            MetricFact.value_numeric,
            MetricFact.value_text,
            MetricFact.source_document_id,
            PdfDocument.report_date,
        )
        .join(PdfDocument, PdfDocument.id == MetricFact.source_document_id)
        .where(
            MetricFact.stock_id == stock_id,
            MetricFact.source_type == "parsed",
            MetricFact.source_document_id.is_not(None),
            fact_nature_expr == "actual",
        )
    ).all()

    grouped: dict[tuple[str, str | None, date | None], list[dict[str, Any]]] = defaultdict(list)
    for metric_key, period_type, period_end_date, value_numeric, value_text, source_document_id, report_date in rows:
        grouped[(metric_key, period_type, period_end_date)].append(
            {
                "source_document_id": source_document_id,
                "source_report_date": report_date.isoformat() if report_date else None,
                "value_numeric": float(value_numeric) if value_numeric is not None else None,
                "value_text": value_text,
                "is_active_report": bool(
                    active_report is not None
                    and source_document_id is not None
                    and active_report.document_id == source_document_id
                ),
            }
        )

    conflicts: list[dict[str, Any]] = []
    for (metric_key, period_type, period_end_date), observations in grouped.items():
        distinct_values = {
            (obs["value_numeric"], obs["value_text"])
            for obs in observations
        }
        if len(distinct_values) <= 1:
            continue
        ranked = sorted(
            observations,
            key=lambda obs: (
                obs["source_report_date"] or "",
                obs["source_document_id"] or -1,
            ),
            reverse=True,
        )
        conflicts.append(
            {
                "metric_key": metric_key,
                "period_type": period_type,
                "period_end_date": period_end_date.isoformat() if period_end_date else None,
                "observations": ranked,
            }
        )

    return sorted(
        conflicts,
        key=lambda item: (
            item["period_end_date"] or "",
            item["metric_key"],
        ),
        reverse=True,
    )
