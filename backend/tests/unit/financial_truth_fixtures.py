"""Factories for positive tests that need real parsed-fact authority.

Do not use these helpers in negative tests that intentionally exercise an
untrusted lineage shape: those tests should keep constructing the attack
directly and assert that the database rejects it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

from app.models.artifacts import PdfDocument
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact


def _json_value(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def exact_projection(fact: MetricFact) -> dict:
    return {
        key: _json_value(getattr(fact, key))
        for key in (
            "metric_key",
            "value_numeric",
            "value_text",
            "value_json",
            "unit",
            "currency",
            "period",
            "period_type",
            "period_end_date",
            "as_of_date",
        )
    }


def authorize_parsed_facts(
    session,
    *,
    document: PdfDocument,
    facts: Iterable[MetricFact],
) -> list[MetricFact]:
    """Attach one immutable exact extraction projection to each parsed fact."""
    authorized: list[MetricFact] = []
    for index, fact in enumerate(facts, start=1):
        if fact.source_type != "parsed":
            raise ValueError("exact parsed authority helper requires parsed facts")
        if fact.user_id != document.user_id:
            raise ValueError("fact and document owners must match")
        extraction = MetricExtraction(
            user_id=fact.user_id,
            document_id=document.id,
            page_number=index,
            field_key=f"fixture_{fact.metric_key}_{index}",
            raw_value_text=str(
                fact.value_numeric
                if fact.value_numeric is not None
                else fact.value_text
            ),
            original_text_snippet=f"{fact.metric_key} fixture evidence",
            parsed_value_json={"fixture": True},
            parser_version="v1",
            parse_generation=document.current_parse_generation,
            resolved_stock_id=fact.stock_id,
            mapping_version="value-line-v2",
            canonical_projections_json=[exact_projection(fact)],
        )
        session.add(extraction)
        session.flush()
        fact.source_document_id = document.id
        fact.source_ref_id = extraction.id
        fact.parse_generation = document.current_parse_generation
        session.add(fact)
        authorized.append(fact)
    return authorized
