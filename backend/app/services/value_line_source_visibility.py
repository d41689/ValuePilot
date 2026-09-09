"""Current Value Line source-authorization policy for report consumers."""

from __future__ import annotations

from sqlalchemy import and_, func, or_

from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact


VALUE_LINE_CURRENT_SOURCES = ("upload", "value_line", "value line")
VALUE_LINE_CURRENT_PARSE_STATUSES = ("parsing", "parsed", "parsed_partial")


class ValueLineSourceUnavailableError(ValueError):
    """Historical identity exists but its source is not currently readable."""

    code = "source_unavailable"

    def __init__(self) -> None:
        super().__init__("Value Line source evidence is currently unavailable.")


def current_value_line_source_unavailable_predicate():
    """Return the shared fail-closed current document visibility predicate."""

    return or_(
        PdfDocument.id.is_(None),
        PdfDocument.user_id != MetricFact.user_id,
        value_line_document_source_unavailable_predicate(),
        and_(
            PdfDocument.stock_id.is_not(None),
            PdfDocument.stock_id != MetricFact.stock_id,
        ),
    )


def current_value_line_source_available_predicate():
    return ~current_value_line_source_unavailable_predicate()


def current_value_line_report_predicate():
    """Current analysis additionally excludes ordinarily archived evidence."""

    return and_(
        current_value_line_source_available_predicate(),
        PdfDocument.archived_at.is_(None),
    )


def value_line_document_source_unavailable_predicate():
    """Authorization/identity conditions shared by document-only readers."""

    return or_(
        ~func.lower(PdfDocument.source).in_(VALUE_LINE_CURRENT_SOURCES),
        ~PdfDocument.parse_status.in_(VALUE_LINE_CURRENT_PARSE_STATUSES),
        PdfDocument.identity_needs_review.is_(True),
        PdfDocument.source_unavailable_at.is_not(None),
    )


def current_value_line_document_predicate():
    return and_(
        ~value_line_document_source_unavailable_predicate(),
        PdfDocument.archived_at.is_(None),
    )
