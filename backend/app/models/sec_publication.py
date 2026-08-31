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
    context_id: Mapped[str | None] = mapped_column(Text)
    dimensions_policy: Mapped[str] = mapped_column(String(40))
    dimensions_sha256: Mapped[str] = mapped_column(String(64))
    locator_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    audit_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    metric_fact_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("metric_facts.id"))
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_txid: Mapped[int] = mapped_column(BigInteger)


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
