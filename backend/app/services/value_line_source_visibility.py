"""Current Value Line source-authorization policy for report consumers."""

from __future__ import annotations

from sqlalchemy import and_, or_

from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact


VALUE_LINE_CURRENT_SOURCES = ("upload", "value_line")
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
        ~PdfDocument.source.in_(VALUE_LINE_CURRENT_SOURCES),
        ~PdfDocument.parse_status.in_(VALUE_LINE_CURRENT_PARSE_STATUSES),
        PdfDocument.identity_needs_review.is_(True),
        and_(
            PdfDocument.stock_id.is_not(None),
            PdfDocument.stock_id != MetricFact.stock_id,
        ),
    )


def current_value_line_source_available_predicate():
    return ~current_value_line_source_unavailable_predicate()
