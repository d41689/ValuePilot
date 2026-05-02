from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.artifacts import DocumentPage, PdfDocument
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.services.calculated_metrics.piotroski_f_score import (
    COMPONENT_KEYS,
    TOTAL_KEY,
    PiotroskiFScoreCalculator,
)
from app.services.calculated_metrics.value_line_ratios import ValueLineRatioCalculator


VALUE_LINE_RATIO_KEYS = {
    "returns.roa",
    "liquidity.current_ratio",
    "leverage.long_term_debt_to_assets",
    "leverage.long_term_debt_to_capital",
    "efficiency.asset_turnover",
    "efficiency.capital_turnover",
    "ins.premium_turnover",
}
REFRESH_CALCULATED_KEYS = set(COMPONENT_KEYS) | {TOTAL_KEY} | VALUE_LINE_RATIO_KEYS


@dataclass(frozen=True)
class DuplicateDocumentGroup:
    user_id: int
    stock_id: int
    report_date: date
    keep_document: PdfDocument
    duplicate_documents: list[PdfDocument]

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "stock_id": self.stock_id,
            "report_date": self.report_date.isoformat(),
            "keep_document": _document_summary(self.keep_document),
            "duplicate_documents": [
                _document_summary(document) for document in self.duplicate_documents
            ],
        }


class DocumentDedupeService:
    def __init__(self, db: Session):
        self.db = db

    def find_duplicate_groups(
        self,
        *,
        user_id: Optional[int] = None,
        stock_id: Optional[int] = None,
    ) -> list[DuplicateDocumentGroup]:
        filters = [
            PdfDocument.stock_id.is_not(None),
            PdfDocument.report_date.is_not(None),
        ]
        if user_id is not None:
            filters.append(PdfDocument.user_id == user_id)
        if stock_id is not None:
            filters.append(PdfDocument.stock_id == stock_id)

        documents = self.db.scalars(
            select(PdfDocument)
            .where(*filters)
            .order_by(
                PdfDocument.user_id.asc(),
                PdfDocument.stock_id.asc(),
                PdfDocument.report_date.asc(),
                PdfDocument.id.asc(),
            )
        ).all()

        by_key: dict[tuple[int, int, date], list[PdfDocument]] = {}
        for document in documents:
            if document.stock_id is None or document.report_date is None:
                continue
            by_key.setdefault(
                (document.user_id, document.stock_id, document.report_date), []
            ).append(document)

        groups: list[DuplicateDocumentGroup] = []
        for (
            group_user_id,
            group_stock_id,
            group_report_date,
        ), group_docs in by_key.items():
            if len(group_docs) < 2:
                continue
            keep = _canonical_document(group_docs)
            duplicates = [document for document in group_docs if document.id != keep.id]
            groups.append(
                DuplicateDocumentGroup(
                    user_id=group_user_id,
                    stock_id=group_stock_id,
                    report_date=group_report_date,
                    keep_document=keep,
                    duplicate_documents=duplicates,
                )
            )
        return groups

    def cleanup_duplicates(
        self,
        *,
        user_id: Optional[int] = None,
        stock_id: Optional[int] = None,
        apply: bool = False,
    ) -> dict[str, Any]:
        groups = self.find_duplicate_groups(user_id=user_id, stock_id=stock_id)
        summary: dict[str, Any] = {
            "mode": "apply" if apply else "dry_run",
            "duplicate_group_count": len(groups),
            "deleted_document_count": sum(
                len(group.duplicate_documents) for group in groups
            ),
            "groups": [group.to_dict() for group in groups],
        }
        if not apply or not groups:
            return summary

        try:
            deleted_document_ids = [
                document.id
                for group in groups
                for document in group.duplicate_documents
            ]
            affected_user_stock_pairs = sorted(
                {(group.user_id, group.stock_id) for group in groups}
            )

            duplicate_to_keep_document_id = {
                duplicate_document.id: group.keep_document.id
                for group in groups
                for duplicate_document in group.duplicate_documents
            }

            affected_slots = self.db.execute(
                select(
                    MetricFact.user_id,
                    MetricFact.stock_id,
                    MetricFact.metric_key,
                    MetricFact.period_type,
                    MetricFact.period_end_date,
                    MetricFact.as_of_date,
                )
                .where(
                    MetricFact.source_document_id.in_(deleted_document_ids),
                    MetricFact.source_type == "parsed",
                )
                .distinct()
            ).all()

            preserved_fact_count = self._detach_non_parsed_facts_from_deleted_documents(
                duplicate_to_keep_document_id=duplicate_to_keep_document_id
            )
            self.db.flush()

            self.db.execute(
                delete(MetricFact).where(
                    MetricFact.source_document_id.in_(deleted_document_ids),
                    MetricFact.source_type == "parsed",
                )
            )
            self.db.execute(
                delete(MetricExtraction).where(
                    MetricExtraction.document_id.in_(deleted_document_ids)
                )
            )
            self.db.execute(
                delete(DocumentPage).where(
                    DocumentPage.document_id.in_(deleted_document_ids)
                )
            )
            self.db.execute(
                delete(PdfDocument).where(PdfDocument.id.in_(deleted_document_ids))
            )
            self.db.flush()

            for (
                slot_user_id,
                slot_stock_id,
                metric_key,
                period_type,
                period_end_date,
                as_of_date,
            ) in affected_slots:
                self._reconcile_parsed_fact_current_slot(
                    user_id=slot_user_id,
                    stock_id=slot_stock_id,
                    metric_key=metric_key,
                    period_type=period_type,
                    period_end_date=period_end_date,
                    as_of_date=as_of_date,
                )

            for affected_user_id, affected_stock_id in affected_user_stock_pairs:
                self.db.execute(
                    delete(MetricFact).where(
                        MetricFact.user_id == affected_user_id,
                        MetricFact.stock_id == affected_stock_id,
                        MetricFact.source_type == "calculated",
                        MetricFact.metric_key.in_(sorted(REFRESH_CALCULATED_KEYS)),
                    )
                )
            self.db.flush()

            for affected_user_id, affected_stock_id in affected_user_stock_pairs:
                ValueLineRatioCalculator(self.db).calculate_for_stock(
                    user_id=affected_user_id,
                    stock_id=affected_stock_id,
                )
                PiotroskiFScoreCalculator(self.db).calculate_for_stock(
                    user_id=affected_user_id,
                    stock_id=affected_stock_id,
                )

            self.db.commit()
            summary["affected_user_stock_pairs"] = [
                {"user_id": pair_user_id, "stock_id": pair_stock_id}
                for pair_user_id, pair_stock_id in affected_user_stock_pairs
            ]
            summary["preserved_non_parsed_fact_count"] = preserved_fact_count
            return summary
        except Exception:
            self.db.rollback()
            raise

    def _detach_non_parsed_facts_from_deleted_documents(
        self,
        *,
        duplicate_to_keep_document_id: dict[int, int],
    ) -> int:
        preserved_fact_count = 0
        for (
            duplicate_document_id,
            keep_document_id,
        ) in duplicate_to_keep_document_id.items():
            facts = self.db.scalars(
                select(MetricFact).where(
                    MetricFact.source_document_id == duplicate_document_id,
                    MetricFact.source_type != "parsed",
                )
            ).all()
            for fact in facts:
                conflicting_fact_id = self.db.scalar(
                    select(MetricFact.id)
                    .where(
                        MetricFact.stock_id == fact.stock_id,
                        MetricFact.metric_key == fact.metric_key,
                        MetricFact.period_type == fact.period_type,
                        MetricFact.period_end_date == fact.period_end_date,
                        MetricFact.source_document_id == keep_document_id,
                        MetricFact.id != fact.id,
                    )
                    .limit(1)
                )
                fact.source_document_id = (
                    None if conflicting_fact_id is not None else keep_document_id
                )
                self.db.add(fact)
                preserved_fact_count += 1
        return preserved_fact_count

    def _reconcile_parsed_fact_current_slot(
        self,
        *,
        user_id: int,
        stock_id: int,
        metric_key: str,
        period_type: Optional[str],
        period_end_date: Optional[date],
        as_of_date: Optional[date],
    ) -> None:
        facts = self.db.scalars(
            select(MetricFact).where(
                MetricFact.user_id == user_id,
                MetricFact.stock_id == stock_id,
                MetricFact.metric_key == metric_key,
                MetricFact.source_type == "parsed",
                MetricFact.period_type == period_type,
                MetricFact.period_end_date == period_end_date,
                MetricFact.as_of_date == as_of_date,
            )
        ).all()
        if not facts:
            return

        manual_current_exists = self.db.scalar(
            select(MetricFact.id)
            .where(
                MetricFact.user_id == user_id,
                MetricFact.stock_id == stock_id,
                MetricFact.metric_key == metric_key,
                MetricFact.source_type == "manual",
                MetricFact.period_type == period_type,
                MetricFact.period_end_date == period_end_date,
                MetricFact.as_of_date == as_of_date,
                MetricFact.is_current.is_(True),
            )
            .limit(1)
        )
        if manual_current_exists is not None:
            for fact in facts:
                fact.is_current = False
                self.db.add(fact)
            self.db.flush()
            return

        doc_ids = sorted(
            {
                fact.source_document_id
                for fact in facts
                if fact.source_document_id is not None
            }
        )
        report_dates_by_doc: dict[int, Optional[date]] = {}
        if doc_ids:
            report_dates_by_doc = dict(
                self.db.execute(
                    select(PdfDocument.id, PdfDocument.report_date).where(
                        PdfDocument.id.in_(doc_ids)
                    )
                ).all()
            )

        winner = max(
            facts,
            key=lambda fact: (
                report_dates_by_doc.get(fact.source_document_id or -1) or date.min,
                fact.source_document_id or -1,
                fact.id or -1,
            ),
        )
        for fact in facts:
            fact.is_current = fact.id == winner.id
            self.db.add(fact)
        self.db.flush()


def _canonical_document(documents: list[PdfDocument]) -> PdfDocument:
    return max(
        documents,
        key=lambda document: (
            _parse_status_rank(document.parse_status),
            document.upload_time or datetime.min,
            document.id or -1,
        ),
    )


def _parse_status_rank(status: Optional[str]) -> int:
    if status == "parsed":
        return 4
    if status == "parsed_partial":
        return 3
    if status in {"parsing", "uploaded"}:
        return 2
    if status == "failed":
        return 1
    return 0


def _document_summary(document: PdfDocument) -> dict[str, Any]:
    return {
        "id": document.id,
        "file_name": document.file_name,
        "parse_status": document.parse_status,
        "upload_time": document.upload_time.isoformat() if document.upload_time else None,
        "report_date": document.report_date.isoformat() if document.report_date else None,
    }
