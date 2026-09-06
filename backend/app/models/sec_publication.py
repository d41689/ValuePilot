"""ORM projections for immutable SEC mapping, publication, and method authorities."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SecMetricMappingVersion(Base):
    __tablename__ = "sec_metric_mapping_versions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    spec_sha256: Mapped[str] = mapped_column(String(64))
    currency_registry_id: Mapped[str] = mapped_column(String(80))
    currency_serialization: Mapped[str] = mapped_column(Text)
    currency_sha256: Mapped[str] = mapped_column(String(64))
    reviewer_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    review_reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)


class SecMetricMappingRule(Base):
    __tablename__ = "sec_metric_mapping_rules"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    mapping_version_id: Mapped[str] = mapped_column(ForeignKey("sec_metric_mapping_versions.id"))
    rule_id: Mapped[str] = mapped_column(String(120))
    metric_key: Mapped[str] = mapped_column(String)
    priority: Mapped[int] = mapped_column(Integer)
    concept_namespace_authority: Mapped[str] = mapped_column(String(32))
    concept_local_name: Mapped[str] = mapped_column(String)
    target_unit: Mapped[str] = mapped_column(String(32))
    period_policy: Mapped[str] = mapped_column(String(80))
    fact_nature: Mapped[str] = mapped_column(String(24))
    derivation_kind: Mapped[str] = mapped_column(String(40))
    derivation_rule: Mapped[str | None] = mapped_column(String(80))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    spec_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)


class SecMetricMappingRuleConcept(Base):
    __tablename__ = "sec_metric_mapping_rule_concepts"
    id: Mapped[int] = mapped_column(BigInteger,primary_key=True)
    mapping_rule_id: Mapped[int] = mapped_column(BigInteger,ForeignKey("sec_metric_mapping_rules.id"))
    concept_ordinal: Mapped[int] = mapped_column(Integer)
    namespace_authority: Mapped[str] = mapped_column(String(32))
    local_name: Mapped[str] = mapped_column(String)
    spec_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)


class SecMetricPublicationRun(Base):
    __tablename__ = "sec_metric_publication_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"))
    issuer_identity_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sec_issuer_identities.id"))
    mapping_version_id: Mapped[str] = mapped_column(ForeignKey("sec_metric_mapping_versions.id"))
    requested_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amendment_policy: Mapped[str] = mapped_column(String(80))
    source_set_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    published_count: Mapped[int] = mapped_column(Integer)
    unresolved_count: Mapped[int] = mapped_column(Integer)
    rejected_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)


class SecMetricPublicationRunSource(Base):
    __tablename__ = "sec_metric_publication_run_sources"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    publication_run_id: Mapped[str] = mapped_column(ForeignKey("sec_metric_publication_runs.id"))
    mapping_rule_id: Mapped[int] = mapped_column(ForeignKey("sec_metric_mapping_rules.id"))
    source_ordinal: Mapped[int] = mapped_column(Integer)
    parse_run_id: Mapped[int] = mapped_column(ForeignKey("sec_financial_parse_runs.id"))
    filing_id: Mapped[int] = mapped_column(ForeignKey("sec_financial_filings.id"))
    accession_no: Mapped[str] = mapped_column(String(20))
    parser_version: Mapped[str] = mapped_column(String(80))
    input_manifest_hash: Mapped[str] = mapped_column(String(64))
    source_available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)


class SecMetricPublication(Base):
    __tablename__ = "sec_metric_publications"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    publication_run_id: Mapped[str] = mapped_column(ForeignKey("sec_metric_publication_runs.id"))
    mapping_rule_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sec_metric_mapping_rules.id"))
    decision_ordinal: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str] = mapped_column(String(80))
    stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"))
    metric_key: Mapped[str] = mapped_column(String)
    period_type: Mapped[str] = mapped_column(String(16))
    period_end_date: Mapped[date] = mapped_column(Date)
    fiscal_year: Mapped[int] = mapped_column(Integer)
    fiscal_quarter_ordinal: Mapped[int | None] = mapped_column(SmallInteger)
    period_start_date: Mapped[date | None] = mapped_column(Date)
    period_basis: Mapped[str] = mapped_column(String(16))
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    unit: Mapped[str | None] = mapped_column(String(32))
    currency: Mapped[str | None] = mapped_column(String(3))
    source_role: Mapped[str] = mapped_column(String(40))
    fact_nature: Mapped[str] = mapped_column(String(24))
    derivation_kind: Mapped[str] = mapped_column(String(40))
    context_id: Mapped[str | None] = mapped_column(Text)
    dimensions_policy: Mapped[str] = mapped_column(String(40))
    dimensions_sha256: Mapped[str] = mapped_column(String(64))
    locator_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    audit_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    metric_fact_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("metric_facts.id"))
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)


class SecMetricPublicationInput(Base):
    __tablename__ = "sec_metric_publication_inputs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("sec_metric_publications.id"))
    input_ordinal: Mapped[int] = mapped_column(Integer)
    input_role: Mapped[str] = mapped_column(String(24))
    run_source_id: Mapped[int | None] = mapped_column(ForeignKey("sec_metric_publication_run_sources.id"))
    raw_fact_id: Mapped[int | None] = mapped_column(ForeignKey("sec_raw_xbrl_facts.id"))
    source_publication_id: Mapped[int | None] = mapped_column(ForeignKey("sec_metric_publications.id"))
    normalization_id: Mapped[int | None] = mapped_column(ForeignKey("sec_raw_numeric_normalizations.id"))
    arithmetic_sign: Mapped[int] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)


class SecMetricPublicationAudit(Base):
    """Append-only raw mapping outcome that did not prove a canonical slot."""

    __tablename__ = "sec_metric_publication_audits"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    publication_run_id: Mapped[str] = mapped_column(ForeignKey("sec_metric_publication_runs.id"))
    mapping_rule_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("sec_metric_mapping_rules.id"))
    audit_ordinal: Mapped[int] = mapped_column(Integer)
    reason_code: Mapped[str] = mapped_column(String(80))
    raw_fact_ids_json: Mapped[list[int]] = mapped_column(JSONB)
    detail: Mapped[str | None] = mapped_column(Text)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)


class SecMetricPublicationUnresolvedInput(Base):
    __tablename__ = "sec_metric_publication_unresolved_inputs"
    id: Mapped[int] = mapped_column(BigInteger,primary_key=True)
    publication_id: Mapped[int] = mapped_column(BigInteger,ForeignKey("sec_metric_publications.id"))
    input_ordinal: Mapped[int] = mapped_column(Integer)
    run_source_id: Mapped[int] = mapped_column(BigInteger,ForeignKey("sec_metric_publication_run_sources.id"))
    raw_fact_id: Mapped[int] = mapped_column(BigInteger,ForeignKey("sec_raw_xbrl_facts.id"))
    statement_authority_id: Mapped[int] = mapped_column(BigInteger,ForeignKey("sec_statement_fact_authorities.id"))
    normalization_id: Mapped[int | None] = mapped_column(BigInteger,ForeignKey("sec_raw_numeric_normalizations.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)


class SecMetricPublicationAvailability(Base):
    __tablename__ = "sec_metric_publication_availabilities"
    publication_run_id: Mapped[str] = mapped_column(ForeignKey("sec_metric_publication_runs.id"), primary_key=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finalized_txid: Mapped[int] = mapped_column(BigInteger)


class SecRawNumericNormalization(Base):
    __tablename__ = "sec_raw_numeric_normalizations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    raw_fact_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sec_raw_xbrl_facts.id"))
    mapping_rule_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sec_metric_mapping_rules.id"))
    mapping_version_id: Mapped[str] = mapped_column(String(80), ForeignKey("sec_metric_mapping_versions.id"))
    normalization_version: Mapped[str] = mapped_column(String(40))
    normalized_value: Mapped[Decimal] = mapped_column(Numeric(38, 12))
    raw_semantic_sha256: Mapped[str] = mapped_column(String(64))
    transformation_identity: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)


class SecEconomicClassificationReview(Base):
    __tablename__ = "sec_economic_classification_reviews"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"))
    economic_class: Mapped[str] = mapped_column(String(24))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_review_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("sec_economic_classification_reviews.id"))
    reviewer_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    review_reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)


class SecEconomicRiskReview(Base):
    __tablename__ = "sec_economic_risk_attribute_reviews"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stocks.id"))
    risk_attribute: Mapped[str] = mapped_column(String(32))
    is_present: Mapped[bool] = mapped_column(Boolean)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_review_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("sec_economic_risk_attribute_reviews.id"))
    reviewer_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    review_reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)


class SecMethodPolicyVersion(Base):
    __tablename__ = "sec_method_policy_versions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    policy_sha256: Mapped[str] = mapped_column(String(64))
    reviewer_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    review_reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)


class SecMethodPolicyRule(Base):
    __tablename__ = "sec_method_policy_rules"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    method_policy_version_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("sec_method_policy_versions.id")
    )
    method_key: Mapped[str] = mapped_column(String(80))
    economic_class: Mapped[str] = mapped_column(String(24))
    method_version_id: Mapped[str | None] = mapped_column(String(80))
    applicability: Mapped[str] = mapped_column(String(24))
    required_evidence_json: Mapped[list[str]] = mapped_column(JSONB)
    required_outputs_json: Mapped[list[str]] = mapped_column(JSONB)
    required_risk_reviews_json: Mapped[list[str]] = mapped_column(JSONB)
    required_adjustments_json: Mapped[list[str]] = mapped_column(JSONB)
    unsupported_reason_code: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)
