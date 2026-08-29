"""One visibility contract for canonical metric_facts product reads."""

from __future__ import annotations

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import aliased

from app.models.artifacts import PdfDocument
from app.models.facts import CalculatedRun, MetricFact
from app.models.sec_financials import (
    SecFinancialFiling,
    SecFinancialParseRun,
    SecIssuerIdentity,
    SecMetricMappingRegistry,
    SecMetricPublication,
    SecRawXbrlFact,
)


USER_INTRINSIC_VALUE_KEY = "val.fair_value"


def _authorized_manual_fact_predicate(fact_entity):
    """Use the database-owned authority predicate for every manual read."""
    return func.current_manual_fact_has_exact_authority(fact_entity.id).is_(True)


def _authorized_parsed_fact_predicate(fact_entity):
    """Require the immutable extraction stock/mapping/value projection."""
    return func.parsed_metric_fact_has_exact_authority(fact_entity.id).is_(True)


def visible_metric_fact_predicate(
    fact_entity,
    *,
    user_id: int,
):
    """Return the SQL predicate for user-owned and approved public facts.

    SEC actuals are public canonical observations (`user_id IS NULL`). Private
    parsed/manual/calculated facts remain user-scoped. An administrative role
    never publishes a proprietary upload to other users.
    """
    manual_override = aliased(MetricFact)
    has_manual_override = exists(
        select(manual_override.id).where(
            manual_override.user_id == user_id,
            manual_override.stock_id == fact_entity.stock_id,
            manual_override.metric_key == fact_entity.metric_key,
            manual_override.period_type.is_not_distinct_from(
                fact_entity.period_type
            ),
            manual_override.period_end_date.is_not_distinct_from(
                fact_entity.period_end_date
            ),
            manual_override.as_of_date.is_not_distinct_from(
                fact_entity.as_of_date
            ),
            manual_override.source_type == "manual",
            manual_override.is_current.is_(True),
            _authorized_manual_fact_predicate(manual_override),
        )
    )
    source_available = or_(
        fact_entity.source_document_id.is_(None),
        exists(
            select(PdfDocument.id).where(
                PdfDocument.id == fact_entity.source_document_id,
                PdfDocument.lifecycle_state == "active",
            )
        ),
    )
    filing_identity = aliased(SecIssuerIdentity)
    current_identity = aliased(SecIssuerIdentity)
    superseding_identity = aliased(SecIssuerIdentity)
    identity_is_current = exists(
        select(current_identity.id).where(
            current_identity.stock_id == fact_entity.stock_id,
            current_identity.cik == filing_identity.cik,
            current_identity.status == "reviewed",
            current_identity.known_at <= func.clock_timestamp(),
            current_identity.effective_from
            <= func.coalesce(
                SecFinancialFiling.report_date,
                SecFinancialFiling.filed_on,
            ),
            or_(
                current_identity.effective_to.is_(None),
                current_identity.effective_to
                >= func.coalesce(
                    SecFinancialFiling.report_date,
                    SecFinancialFiling.filed_on,
                ),
            ),
            ~exists(
                select(superseding_identity.id).where(
                    superseding_identity.supersedes_identity_id
                    == current_identity.id,
                    superseding_identity.known_at <= func.clock_timestamp(),
                )
            ),
        )
    )
    return or_(
        and_(
            fact_entity.source_type == "sec",
            fact_entity.user_id.is_(None),
            exists(
                select(SecMetricPublication.id)
                .join(
                    SecRawXbrlFact,
                    SecRawXbrlFact.id == SecMetricPublication.raw_fact_id,
                )
                .join(
                    SecFinancialParseRun,
                    SecFinancialParseRun.id == SecRawXbrlFact.parse_run_id,
                )
                .join(
                    SecFinancialFiling,
                    SecFinancialFiling.id == SecFinancialParseRun.filing_id,
                )
                .join(
                    filing_identity,
                    filing_identity.id == SecFinancialFiling.issuer_identity_id,
                )
                .join(
                    SecMetricMappingRegistry,
                    and_(
                        SecMetricMappingRegistry.mapping_version
                        == SecMetricPublication.mapping_version,
                        SecMetricMappingRegistry.canonical_metric_key
                        == SecMetricPublication.canonical_metric_key,
                    ),
                )
                .where(
                    SecMetricPublication.metric_fact_id == fact_entity.id,
                    SecMetricPublication.status == "published",
                    SecMetricPublication.raw_fact_id == fact_entity.source_ref_id,
                    SecMetricPublication.mapping_version
                    == fact_entity.value_json["mapping_version"].as_string(),
                    SecMetricPublication.canonical_metric_key
                    == fact_entity.metric_key,
                    SecMetricPublication.period_type.is_not_distinct_from(
                        fact_entity.period_type
                    ),
                    SecMetricPublication.period_end_date.is_not_distinct_from(
                        fact_entity.period_end_date
                    ),
                    identity_is_current,
                )
            ),
        ),
        and_(
            fact_entity.source_type == "parsed",
            source_available,
            _authorized_parsed_fact_predicate(fact_entity),
            ~has_manual_override,
            fact_entity.user_id == user_id,
        ),
        and_(
            fact_entity.user_id == user_id,
            fact_entity.source_type == "manual",
            _authorized_manual_fact_predicate(fact_entity),
        ),
        and_(
            fact_entity.user_id == user_id,
            fact_entity.source_type == "calculated",
            source_available,
            # Legacy ratio/Piotroski rows contain caller-authored JSON only;
            # they have no DB-verifiable exact run, inputs, or arithmetic.
            # Preserve them as historical data but fail closed for every
            # product read.  A calculated fact becomes canonical only through
            # the protected formula-v2 publication protocol.
            fact_entity.value_json["formula_lineage_version"].as_string()
            == "formula-v2",
            exists(
                select(CalculatedRun.id).where(
                    CalculatedRun.id == fact_entity.source_ref_id,
                    CalculatedRun.user_id == user_id,
                    CalculatedRun.stock_id == fact_entity.stock_id,
                    CalculatedRun.is_dirty.is_(False),
                )
            ),
        ),
    )
