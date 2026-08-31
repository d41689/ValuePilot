"""SEC metric publication mapping and lifecycle foundation.

Revision ID: 20260901120000
Revises: 20260831120000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260901120000"
down_revision = "20260831120000"
branch_labels = None
depends_on = None

V1_ID = "sec-us-gaap-v1"
V1_SPEC_SHA256 = "01b828534060e04439103c935842c1a9cf42d3f5a2311934c99bef81bdcc073d"
V1_CURRENCY_SHA256 = "c398cea3e87a35c10aded8caa21bc8e592e72ac5129f3b182761cb8788e4c4c2"
V1_CURRENCIES = ("DKK", "EUR", "TWD", "USD")
V1_NAMESPACES = {
    "us_gaap": tuple(f"http://fasb.org/us-gaap/{year}-01-31" for year in range(2014, 2022)) + tuple(f"http://fasb.org/us-gaap/{year}" for year in range(2022, 2027)),
    "dei": ("http://xbrl.sec.gov/dei/2014-01-31", "http://xbrl.sec.gov/dei/2018-01-31", "http://xbrl.sec.gov/dei/2019-01-31", "http://xbrl.sec.gov/dei/2020-01-31", "http://xbrl.sec.gov/dei/2021", "http://xbrl.sec.gov/dei/2021q4", "http://xbrl.sec.gov/dei/2022", "http://xbrl.sec.gov/dei/2023", "http://xbrl.sec.gov/dei/2024", "http://xbrl.sec.gov/dei/2025", "http://xbrl.sec.gov/dei/2026"),
}
V1_RULES = (
    ("sec.revenue", "is.revenue", "currency", "duration", ["RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenues"]),
    ("sec.gross_profit", "is.gross_profit", "currency", "duration", ["GrossProfit"]),
    ("sec.operating_income", "is.operating_income", "currency", "duration", ["OperatingIncomeLoss"]),
    ("sec.net_income", "is.net_income", "currency", "duration", ["NetIncomeLoss"]),
    ("sec.operating_cash_flow", "is.operating_cash_flow", "currency", "duration", ["NetCashProvidedByUsedInOperatingActivities"]),
    ("sec.capital_expenditures", "cf.capital_expenditures", "currency", "duration", ["PaymentsToAcquirePropertyPlantAndEquipment"]),
    ("sec.stock_based_compensation", "cf.stock_based_compensation", "currency", "duration", ["ShareBasedCompensation"]),
    ("sec.cash_and_equivalents", "bs.cash_and_equivalents", "currency", "instant", ["CashAndCashEquivalentsAtCarryingValue"]),
    ("sec.cash_and_restricted_cash", "bs.cash_and_restricted_cash", "currency", "instant", ["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]),
    ("sec.total_assets", "bs.total_assets", "currency", "instant", ["Assets"]),
    ("sec.current_assets", "bs.current_assets", "currency", "instant", ["AssetsCurrent"]),
    ("sec.total_liabilities", "bs.total_liabilities", "currency", "instant", ["Liabilities"]),
    ("sec.current_liabilities", "bs.current_liabilities", "currency", "instant", ["LiabilitiesCurrent"]),
    ("sec.stockholders_equity", "bs.stockholders_equity", "currency", "instant", ["StockholdersEquity"]),
    ("sec.equity_including_noncontrolling_interest", "bs.equity_including_noncontrolling_interest", "currency", "instant", ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]),
    ("sec.long_term_debt_current", "cap.long_term_debt_current", "currency", "instant", ["LongTermDebtCurrent"]),
    ("sec.short_term_borrowings", "cap.short_term_borrowings", "currency", "instant", ["ShortTermBorrowings"]),
    ("sec.long_term_debt_noncurrent", "cap.long_term_debt_noncurrent", "currency", "instant", ["LongTermDebtNoncurrent"]),
    ("sec.diluted_eps", "per_share.eps", "currency_per_share", "duration", ["EarningsPerShareDiluted"]),
    ("sec.shares_outstanding", "equity.shares_outstanding", "shares", "instant", ["CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"]),
    ("sec.weighted_average_diluted_shares", "equity.weighted_average_diluted_shares", "shares", "duration", ["WeightedAverageNumberOfDilutedSharesOutstanding"]),
)


def _authority_triggers(table: str) -> None:
    op.execute(f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_sec_financial_lineage_mutation()")
    op.execute(f"CREATE TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_financial_lineage_mutation()")


def upgrade() -> None:
    op.create_table("sec_metric_mapping_versions",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column("spec_sha256", sa.String(64), nullable=False),
        sa.Column("currency_registry_id", sa.String(80), nullable=False),
        sa.Column("currency_serialization", sa.Text(), nullable=False),
        sa.Column("currency_sha256", sa.String(64), nullable=False),
        sa.Column("reviewer_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("review_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column("created_txid", sa.BigInteger(), nullable=False, server_default=sa.text("txid_current()")),
        sa.CheckConstraint("status IN ('draft','approved','retired')"),
        sa.CheckConstraint("spec_sha256 ~ '^[0-9a-f]{64}$' AND currency_sha256 ~ '^[0-9a-f]{64}$'"),
        sa.CheckConstraint("retired_at IS NULL OR retired_at >= effective_from"))
    op.create_table("sec_metric_mapping_version_namespaces",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mapping_version_id", sa.String(80), sa.ForeignKey("sec_metric_mapping_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("authority", sa.String(32), nullable=False),
        sa.Column("namespace_uri", sa.Text(), nullable=False),
        sa.Column("spec_sha256", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column("created_txid", sa.BigInteger(), nullable=False, server_default=sa.text("txid_current()")),
        sa.UniqueConstraint("mapping_version_id","namespace_uri"), sa.UniqueConstraint("mapping_version_id","authority","ordinal"),
        sa.CheckConstraint("authority IN ('us_gaap','dei') AND ordinal >= 1"))
    op.create_table("sec_metric_mapping_version_currencies",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mapping_version_id", sa.String(80), sa.ForeignKey("sec_metric_mapping_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False), sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("registry_id", sa.String(80), nullable=False), sa.Column("canonical_serialization", sa.Text(), nullable=False),
        sa.Column("registry_sha256", sa.String(64), nullable=False), sa.Column("spec_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column("created_txid", sa.BigInteger(), nullable=False, server_default=sa.text("txid_current()")),
        sa.UniqueConstraint("mapping_version_id","currency_code"), sa.UniqueConstraint("mapping_version_id","ordinal"),
        sa.CheckConstraint("currency_code ~ '^[A-Z]{3}$' AND ordinal >= 1"))
    op.create_table("sec_metric_mapping_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mapping_version_id", sa.String(80), sa.ForeignKey("sec_metric_mapping_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rule_id", sa.String(120), nullable=False), sa.Column("metric_key", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False), sa.Column("concept_namespace_authority", sa.String(32), nullable=False),
        sa.Column("concept_local_name", sa.String(), nullable=False), sa.Column("target_unit", sa.String(32), nullable=False),
        sa.Column("period_policy", sa.String(80), nullable=False), sa.Column("fact_nature", sa.String(24), nullable=False),
        sa.Column("derivation_rule", sa.String(80)), sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("spec_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column("created_txid", sa.BigInteger(), nullable=False, server_default=sa.text("txid_current()")),
        sa.UniqueConstraint("mapping_version_id","rule_id"),
        sa.CheckConstraint("priority >= 1 AND target_unit IN ('currency','currency_per_share','shares') AND fact_nature IN ('actual','derived_actual')"))
    op.create_table("sec_metric_publication_runs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("stock_id", sa.BigInteger(), sa.ForeignKey("stocks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("issuer_identity_id", sa.BigInteger(), sa.ForeignKey("sec_issuer_identities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("mapping_version_id", sa.String(80), sa.ForeignKey("sec_metric_mapping_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("requested_cutoff", sa.DateTime(timezone=True), nullable=False), sa.Column("amendment_policy", sa.String(80), nullable=False),
        sa.Column("source_set_sha256", sa.String(64), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("published_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("unresolved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column("created_txid", sa.BigInteger(), nullable=False, server_default=sa.text("txid_current()")),
        sa.CheckConstraint("id ~ '^[0-9a-f-]{36}$' AND status IN ('pending','succeeded','failed') AND published_count>=0 AND unresolved_count>=0 AND rejected_count>=0"))
    op.create_table("sec_metric_publication_run_sources",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("publication_run_id", sa.String(36), sa.ForeignKey("sec_metric_publication_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("mapping_rule_id", sa.BigInteger(), sa.ForeignKey("sec_metric_mapping_rules.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_ordinal", sa.Integer(), nullable=False), sa.Column("parse_run_id", sa.BigInteger(), sa.ForeignKey("sec_financial_parse_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("filing_id", sa.BigInteger(), sa.ForeignKey("sec_financial_filings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("accession_no", sa.String(20), nullable=False), sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("input_manifest_hash", sa.String(64), nullable=False), sa.Column("source_available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")), sa.Column("created_txid", sa.BigInteger(), nullable=False, server_default=sa.text("txid_current()")),
        sa.UniqueConstraint("publication_run_id","source_ordinal"), sa.UniqueConstraint("publication_run_id","parse_run_id"), sa.CheckConstraint("source_ordinal >= 1"))
    op.create_table("sec_metric_publications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("publication_run_id", sa.String(36), sa.ForeignKey("sec_metric_publication_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("decision_ordinal", sa.Integer(), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("stock_id", sa.BigInteger(), sa.ForeignKey("stocks.id", ondelete="RESTRICT"), nullable=False), sa.Column("metric_key", sa.String(), nullable=False),
        sa.Column("period_type", sa.String(16), nullable=False), sa.Column("period_end_date", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False), sa.Column("fiscal_quarter_ordinal", sa.SmallInteger()),
        sa.Column("period_start_date", sa.Date()), sa.Column("period_basis", sa.String(16), nullable=False),
        sa.Column("value_numeric", sa.Numeric(38,12)), sa.Column("unit", sa.String(32)), sa.Column("currency", sa.String(3)),
        sa.Column("source_role", sa.String(40), nullable=False), sa.Column("fact_nature", sa.String(24), nullable=False),
        sa.Column("derivation_kind", sa.String(40), nullable=False),
        sa.Column("context_id", sa.Text(), nullable=False), sa.Column("dimensions_policy", sa.String(40), nullable=False),
        sa.Column("dimensions_sha256", sa.String(64), nullable=False),
        sa.Column("locator_json", postgresql.JSONB(), nullable=False), sa.Column("audit_json", postgresql.JSONB(), nullable=False),
        sa.Column("metric_fact_id", sa.BigInteger()), sa.Column("known_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")), sa.Column("created_txid", sa.BigInteger(), nullable=False, server_default=sa.text("txid_current()")),
        sa.UniqueConstraint("publication_run_id","decision_ordinal"), sa.CheckConstraint("decision_ordinal>=1 AND status IN ('published','unresolved','rejected')"),
        sa.CheckConstraint("octet_length(reason_code) BETWEEN 1 AND 80 AND jsonb_typeof(locator_json)='object' AND jsonb_typeof(audit_json)='object'"),
        sa.CheckConstraint("derivation_kind IN ('direct','current_ytd_minus_prior_ytd','fiscal_year_minus_nine_month_ytd','unresolved')"),
        sa.CheckConstraint("fiscal_year BETWEEN 1900 AND 2200 AND (fiscal_quarter_ordinal IS NULL OR fiscal_quarter_ordinal BETWEEN 1 AND 4) AND period_basis IN ('instant','duration') AND dimensions_sha256 ~ '^[0-9a-f]{64}$'"),
        sa.CheckConstraint("(status='published' AND value_numeric IS NOT NULL AND unit IS NOT NULL AND derivation_kind<>'unresolved') OR (status<>'published' AND metric_fact_id IS NULL AND value_numeric IS NULL AND derivation_kind='unresolved')"))
    op.create_table("sec_raw_numeric_normalizations",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),
        sa.Column("raw_fact_id",sa.BigInteger(),sa.ForeignKey("sec_raw_xbrl_facts.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("mapping_rule_id",sa.BigInteger(),sa.ForeignKey("sec_metric_mapping_rules.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("mapping_version_id",sa.String(80),sa.ForeignKey("sec_metric_mapping_versions.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("normalization_version",sa.String(40),nullable=False),
        sa.Column("normalized_value",sa.Numeric(38,12),nullable=False),
        sa.Column("raw_semantic_sha256",sa.String(64),nullable=False),
        sa.Column("transformation_identity",sa.String(120),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("clock_timestamp()")),
        sa.Column("created_txid",sa.BigInteger(),nullable=False,server_default=sa.text("txid_current()")),
        sa.UniqueConstraint("raw_fact_id","mapping_rule_id","mapping_version_id","normalization_version"),
        sa.UniqueConstraint("id","raw_fact_id","mapping_rule_id","mapping_version_id"),
        sa.CheckConstraint("normalization_version='sec_numeric_v1' AND raw_semantic_sha256 ~ '^[0-9a-f]{64}$'"))
    op.create_table("sec_metric_publication_inputs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("publication_id", sa.BigInteger(), sa.ForeignKey("sec_metric_publications.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("input_ordinal", sa.Integer(), nullable=False), sa.Column("input_role", sa.String(24), nullable=False),
        sa.Column("run_source_id", sa.BigInteger(), sa.ForeignKey("sec_metric_publication_run_sources.id", ondelete="RESTRICT")),
        sa.Column("raw_fact_id", sa.BigInteger(), sa.ForeignKey("sec_raw_xbrl_facts.id", ondelete="RESTRICT")),
        sa.Column("source_publication_id", sa.BigInteger(), sa.ForeignKey("sec_metric_publications.id", ondelete="RESTRICT")),
        sa.Column("normalization_id", sa.BigInteger(), sa.ForeignKey("sec_raw_numeric_normalizations.id", ondelete="RESTRICT")),
        sa.Column("arithmetic_sign", sa.SmallInteger(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column("created_txid", sa.BigInteger(), nullable=False, server_default=sa.text("txid_current()")),
        sa.UniqueConstraint("publication_id","input_ordinal"), sa.UniqueConstraint("publication_id","raw_fact_id"), sa.UniqueConstraint("publication_id","source_publication_id"), sa.UniqueConstraint("publication_id","input_role"),
        sa.CheckConstraint("((input_role='direct' AND input_ordinal=1 AND arithmetic_sign=1 AND raw_fact_id IS NOT NULL AND run_source_id IS NOT NULL AND normalization_id IS NOT NULL AND source_publication_id IS NULL) OR (input_role='left_operand' AND input_ordinal=1 AND arithmetic_sign=1 AND raw_fact_id IS NULL AND run_source_id IS NULL AND normalization_id IS NULL AND source_publication_id IS NOT NULL) OR (input_role='right_operand' AND input_ordinal=2 AND arithmetic_sign=-1 AND raw_fact_id IS NULL AND run_source_id IS NULL AND normalization_id IS NULL AND source_publication_id IS NOT NULL))"))
    op.create_table("sec_metric_publication_availabilities",
        sa.Column("publication_run_id", sa.String(36), sa.ForeignKey("sec_metric_publication_runs.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.Column("finalized_txid", sa.BigInteger(), nullable=False, server_default=sa.text("txid_current()")))

    for table in ["sec_metric_mapping_versions","sec_metric_mapping_version_namespaces","sec_metric_mapping_version_currencies","sec_metric_mapping_rules","sec_metric_publication_runs","sec_metric_publication_run_sources","sec_metric_publications","sec_raw_numeric_normalizations","sec_metric_publication_inputs","sec_metric_publication_availabilities"]:
        _authority_triggers(table)

    op.execute("""
    CREATE FUNCTION stamp_sec_publication_authority() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      NEW.created_at:=clock_timestamp(); NEW.created_txid:=txid_current();
      IF TG_TABLE_NAME='sec_metric_mapping_versions' THEN
        IF NEW.id='sec-us-gaap-v1' AND NEW.status='approved' THEN
          NEW.known_at:='2026-08-31T00:00:00Z'::timestamptz;
        ELSE NEW.known_at:=NEW.created_at; END IF;
      END IF;
      IF TG_TABLE_NAME='sec_metric_publications' THEN NEW.known_at:=NEW.created_at; END IF;
      RETURN NEW; END $$;
    CREATE TRIGGER trg_sec_mapping_version_stamp BEFORE INSERT ON sec_metric_mapping_versions FOR EACH ROW EXECUTE FUNCTION stamp_sec_publication_authority();
    CREATE TRIGGER trg_sec_publication_run_stamp BEFORE INSERT ON sec_metric_publication_runs FOR EACH ROW EXECUTE FUNCTION stamp_sec_publication_authority();
    CREATE TRIGGER trg_sec_publication_stamp BEFORE INSERT ON sec_metric_publications FOR EACH ROW EXECUTE FUNCTION stamp_sec_publication_authority();
    """)

    # V1 is migration-owned evidence. Runtime writers may propose drafts, but
    # cannot manufacture an approved authority inside the application DB.
    mapping = sa.table("sec_metric_mapping_versions", *[sa.column(name) for name in ("id","status","effective_from","known_at","spec_sha256","currency_registry_id","currency_serialization","currency_sha256","review_reason")])
    op.bulk_insert(mapping, [{"id":V1_ID,"status":"approved","effective_from":"2026-08-31T00:00:00+00:00","known_at":"2026-08-31T00:00:00+00:00","spec_sha256":V1_SPEC_SHA256,"currency_registry_id":"locked_ft00_gold_set_v1","currency_serialization":"[\"DKK\",\"EUR\",\"TWD\",\"USD\"]","currency_sha256":V1_CURRENCY_SHA256,"review_reason":"migration-owned approved SEC mapping V1"}])
    ns = sa.table("sec_metric_mapping_version_namespaces", *[sa.column(name) for name in ("mapping_version_id","authority","namespace_uri","spec_sha256","ordinal")])
    op.bulk_insert(ns, [{"mapping_version_id":V1_ID,"authority":authority,"namespace_uri":uri,"spec_sha256":V1_SPEC_SHA256,"ordinal":ordinal} for authority,uris in V1_NAMESPACES.items() for ordinal,uri in enumerate(uris,1)])
    currencies = sa.table("sec_metric_mapping_version_currencies", *[sa.column(name) for name in ("mapping_version_id","currency_code","ordinal","registry_id","canonical_serialization","registry_sha256","spec_sha256")])
    op.bulk_insert(currencies, [{"mapping_version_id":V1_ID,"currency_code":code,"ordinal":ordinal,"registry_id":"locked_ft00_gold_set_v1","canonical_serialization":"[\"DKK\",\"EUR\",\"TWD\",\"USD\"]","registry_sha256":V1_CURRENCY_SHA256,"spec_sha256":V1_SPEC_SHA256} for ordinal,code in enumerate(V1_CURRENCIES,1)])
    rules = sa.table("sec_metric_mapping_rules", *[sa.column(name) for name in ("mapping_version_id","rule_id","metric_key","priority","concept_namespace_authority","concept_local_name","target_unit","period_policy","fact_nature","derivation_rule","spec_sha256")], sa.column("metadata_json", postgresql.JSONB()))
    op.bulk_insert(rules, [{"mapping_version_id":V1_ID,"rule_id":rule_id,"metric_key":metric_key,"priority":1,"concept_namespace_authority":"us_gaap","concept_local_name":concepts[0],"target_unit":unit,"period_policy":period,"fact_nature":"actual","derivation_rule":None,"metadata_json":{"ordered_concepts":concepts},"spec_sha256":V1_SPEC_SHA256} for rule_id,metric_key,unit,period,concepts in V1_RULES])
    op.execute("""
    CREATE FUNCTION guard_sec_mapping_version_insert() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF NEW.status<>'draft' THEN RAISE EXCEPTION 'approved mapping authorities are migration-owned'; END IF;
      RETURN NEW; END $$;
    CREATE TRIGGER trg_sec_mapping_version_insert_guard BEFORE INSERT ON sec_metric_mapping_versions FOR EACH ROW EXECUTE FUNCTION guard_sec_mapping_version_insert();
    """)


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE sec_metric_mapping_versions, sec_metric_publication_runs, sec_metric_publications, sec_raw_numeric_normalizations IN SHARE ROW EXCLUSIVE MODE"))
    if connection.execute(sa.text("SELECT (SELECT count(*) FROM sec_metric_mapping_versions WHERE id<>'sec-us-gaap-v1')+(SELECT count(*) FROM sec_metric_publication_runs)+(SELECT count(*) FROM sec_metric_publications)+(SELECT count(*) FROM sec_raw_numeric_normalizations)" )).scalar_one():
        raise RuntimeError("cannot downgrade retained SEC publication authority")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_mapping_version_insert() CASCADE; DROP FUNCTION IF EXISTS stamp_sec_publication_authority() CASCADE")
    for table in ["sec_metric_publication_availabilities","sec_metric_publication_inputs","sec_raw_numeric_normalizations","sec_metric_publications","sec_metric_publication_run_sources","sec_metric_publication_runs","sec_metric_mapping_rules","sec_metric_mapping_version_currencies","sec_metric_mapping_version_namespaces","sec_metric_mapping_versions"]:
        op.drop_table(table)
