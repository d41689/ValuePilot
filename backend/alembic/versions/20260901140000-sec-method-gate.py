"""Reviewed economic classification and versioned method-policy gate."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision="20260901140000"
down_revision="20260901130000"
branch_labels=None
depends_on=None
METHOD_V1_ID="sec-method-gate-v1"
METHOD_V1_SHA256="9af58420ef7656ff45f644bc39d0a4fa0ae9afba383953bd6349acf165d4088f"

def _protect(table: str) -> None:
    op.execute(f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_sec_financial_lineage_mutation()")
    op.execute(f"CREATE TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION reject_sec_financial_lineage_mutation()")

def upgrade() -> None:
    op.create_table("sec_economic_classification_reviews",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),sa.Column("stock_id",sa.BigInteger(),sa.ForeignKey("stocks.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("economic_class",sa.String(24),nullable=False),sa.Column("effective_from",sa.Date(),nullable=False),sa.Column("effective_to",sa.Date()),
        sa.Column("known_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("clock_timestamp()")),sa.Column("reviewer_user_id",sa.BigInteger(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),sa.Column("review_reason",sa.Text(),nullable=False),
        sa.Column("supersedes_review_id",sa.BigInteger(),sa.ForeignKey("sec_economic_classification_reviews.id",ondelete="RESTRICT"),unique=True),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("clock_timestamp()")),sa.Column("created_txid",sa.BigInteger(),nullable=False,server_default=sa.text("txid_current()")),
        sa.CheckConstraint("economic_class IN ('ordinary','bank','insurer','reit','other_financial','unclassified')"),sa.CheckConstraint("effective_to IS NULL OR effective_to>=effective_from"))
    op.create_table("sec_economic_risk_attribute_reviews",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),sa.Column("stock_id",sa.BigInteger(),sa.ForeignKey("stocks.id",ondelete="RESTRICT"),nullable=False),sa.Column("risk_attribute",sa.String(40),nullable=False),sa.Column("is_present",sa.Boolean(),nullable=False),
        sa.Column("effective_from",sa.Date(),nullable=False),sa.Column("effective_to",sa.Date()),sa.Column("known_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("clock_timestamp()")),sa.Column("reviewer_user_id",sa.BigInteger(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=False),sa.Column("review_reason",sa.Text(),nullable=False),
        sa.Column("supersedes_review_id",sa.BigInteger(),sa.ForeignKey("sec_economic_risk_attribute_reviews.id",ondelete="RESTRICT"),unique=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("clock_timestamp()")),sa.Column("created_txid",sa.BigInteger(),nullable=False,server_default=sa.text("txid_current()")),
        sa.UniqueConstraint("stock_id","risk_attribute","effective_from","known_at"),sa.CheckConstraint("risk_attribute IN ('high_sbc','acquisitive','cyclical','commodity_exposed')"),sa.CheckConstraint("effective_to IS NULL OR effective_to>=effective_from"))
    op.create_table("sec_method_policy_versions",
        sa.Column("id",sa.String(80),primary_key=True),sa.Column("status",sa.String(16),nullable=False),sa.Column("effective_from",sa.DateTime(timezone=True),nullable=False),sa.Column("known_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("clock_timestamp()")),sa.Column("policy_sha256",sa.String(64),nullable=False),sa.Column("reviewer_user_id",sa.BigInteger(),sa.ForeignKey("users.id",ondelete="RESTRICT")),sa.Column("review_reason",sa.Text(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("clock_timestamp()")),sa.Column("created_txid",sa.BigInteger(),nullable=False,server_default=sa.text("txid_current()")),sa.CheckConstraint("status IN ('draft','approved','retired') AND policy_sha256 ~ '^[0-9a-f]{64}$'"))
    op.create_table("sec_method_policy_rules",
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),sa.Column("method_policy_version_id",sa.String(80),sa.ForeignKey("sec_method_policy_versions.id",ondelete="RESTRICT"),nullable=False),sa.Column("method_key",sa.String(80),nullable=False),sa.Column("economic_class",sa.String(24),nullable=False),sa.Column("applicability",sa.String(24),nullable=False),sa.Column("required_evidence_json",postgresql.JSONB(),nullable=False),sa.Column("required_outputs_json",postgresql.JSONB(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("clock_timestamp()")),sa.Column("created_txid",sa.BigInteger(),nullable=False,server_default=sa.text("txid_current()")),sa.UniqueConstraint("method_policy_version_id","method_key","economic_class"),sa.CheckConstraint("method_key IN ('owner_earnings','roic','per_share_trend','system_valuation') AND applicability IN ('approved','unsupported')"),sa.CheckConstraint("jsonb_typeof(required_evidence_json)='array' AND jsonb_typeof(required_outputs_json)='array'"))
    for table in ["sec_economic_classification_reviews","sec_economic_risk_attribute_reviews","sec_method_policy_versions","sec_method_policy_rules"]:_protect(table)
    op.execute("""
    CREATE FUNCTION guard_sec_method_authority_insert() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE overlap_count integer; overlap_id bigint; prior_known timestamptz;
    BEGIN NEW.created_at:=clock_timestamp();NEW.created_txid:=txid_current();
      IF TG_TABLE_NAME IN ('sec_economic_classification_reviews','sec_economic_risk_attribute_reviews') THEN NEW.known_at:=NEW.created_at;END IF;
      IF TG_TABLE_NAME='sec_method_policy_versions' THEN
        IF NEW.id='sec-method-gate-v1' AND NEW.status='approved' THEN NEW.known_at:='2026-08-31T00:00:00Z'::timestamptz;
        ELSE NEW.known_at:=NEW.created_at; END IF;
      END IF;
      IF TG_TABLE_NAME='sec_economic_classification_reviews' THEN
        SELECT count(*),min(r.id),min(r.known_at) INTO overlap_count,overlap_id,prior_known FROM sec_economic_classification_reviews r WHERE r.stock_id=NEW.stock_id AND daterange(r.effective_from,COALESCE(r.effective_to,'infinity'::date),'[]')&&daterange(NEW.effective_from,COALESCE(NEW.effective_to,'infinity'::date),'[]') AND NOT EXISTS(SELECT 1 FROM sec_economic_classification_reviews later WHERE later.supersedes_review_id=r.id AND later.known_at<=NEW.created_at);
        IF overlap_count>0 AND NOT (overlap_count=1 AND NEW.supersedes_review_id IS NOT NULL AND NEW.supersedes_review_id=overlap_id AND prior_known<NEW.created_at) THEN RAISE EXCEPTION 'overlapping economic classification review';END IF;
        IF NEW.supersedes_review_id IS NOT NULL AND (overlap_count<>1 OR NEW.supersedes_review_id<>overlap_id) THEN RAISE EXCEPTION 'invalid economic classification supersession'; END IF;
      ELSIF TG_TABLE_NAME='sec_economic_risk_attribute_reviews' THEN
        SELECT count(*),min(r.id),min(r.known_at) INTO overlap_count,overlap_id,prior_known FROM sec_economic_risk_attribute_reviews r WHERE r.stock_id=NEW.stock_id AND r.risk_attribute=NEW.risk_attribute AND daterange(r.effective_from,COALESCE(r.effective_to,'infinity'::date),'[]')&&daterange(NEW.effective_from,COALESCE(NEW.effective_to,'infinity'::date),'[]') AND NOT EXISTS(SELECT 1 FROM sec_economic_risk_attribute_reviews later WHERE later.supersedes_review_id=r.id AND later.known_at<=NEW.created_at);
        IF overlap_count>0 AND NOT (overlap_count=1 AND NEW.supersedes_review_id IS NOT NULL AND NEW.supersedes_review_id=overlap_id AND prior_known<NEW.created_at) THEN RAISE EXCEPTION 'overlapping economic risk review';END IF;
        IF NEW.supersedes_review_id IS NOT NULL AND (overlap_count<>1 OR NEW.supersedes_review_id<>overlap_id) THEN RAISE EXCEPTION 'invalid economic risk supersession'; END IF;
      END IF;RETURN NEW;END $$;
    CREATE TRIGGER trg_sec_economic_classification_guard BEFORE INSERT ON sec_economic_classification_reviews FOR EACH ROW EXECUTE FUNCTION guard_sec_method_authority_insert();
    CREATE TRIGGER trg_sec_economic_risk_guard BEFORE INSERT ON sec_economic_risk_attribute_reviews FOR EACH ROW EXECUTE FUNCTION guard_sec_method_authority_insert();
    CREATE TRIGGER trg_sec_method_policy_stamp BEFORE INSERT ON sec_method_policy_versions FOR EACH ROW EXECUTE FUNCTION guard_sec_method_authority_insert();
    CREATE TRIGGER trg_sec_method_policy_rule_stamp BEFORE INSERT ON sec_method_policy_rules FOR EACH ROW EXECUTE FUNCTION guard_sec_method_authority_insert();
    """)
    policy=sa.table("sec_method_policy_versions",*[sa.column(n) for n in ("id","status","effective_from","known_at","policy_sha256","review_reason")])
    op.bulk_insert(policy,[{"id":METHOD_V1_ID,"status":"approved","effective_from":"2026-08-31T00:00:00+00:00","known_at":"2026-08-31T00:00:00+00:00","policy_sha256":METHOD_V1_SHA256,"review_reason":"migration-owned default unsupported system-method gate"}])
    rules=sa.table("sec_method_policy_rules",*[sa.column(n) for n in ("method_policy_version_id","method_key","economic_class","applicability")],sa.column("required_evidence_json",postgresql.JSONB()),sa.column("required_outputs_json",postgresql.JSONB()))
    op.bulk_insert(rules,[{"method_policy_version_id":METHOD_V1_ID,"method_key":method,"economic_class":economic_class,"applicability":"unsupported","required_evidence_json":[],"required_outputs_json":[]} for method in ("owner_earnings","roic","per_share_trend","system_valuation") for economic_class in ("ordinary","bank","insurer","reit","other_financial","unclassified")])
    op.execute("""
    CREATE FUNCTION guard_sec_method_policy_insert() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF NEW.status<>'draft' THEN RAISE EXCEPTION 'approved method policies are migration-owned'; END IF;
      RETURN NEW; END $$;
    CREATE TRIGGER trg_sec_method_policy_insert_guard BEFORE INSERT ON sec_method_policy_versions FOR EACH ROW EXECUTE FUNCTION guard_sec_method_policy_insert();
    """)

def downgrade() -> None:
    connection=op.get_bind();connection.execute(sa.text("LOCK TABLE sec_economic_classification_reviews,sec_economic_risk_attribute_reviews,sec_method_policy_versions IN SHARE ROW EXCLUSIVE MODE"))
    if connection.execute(sa.text("SELECT (SELECT count(*) FROM sec_economic_classification_reviews)+(SELECT count(*) FROM sec_economic_risk_attribute_reviews)+(SELECT count(*) FROM sec_method_policy_versions WHERE id<>'sec-method-gate-v1')" )).scalar_one():raise RuntimeError("cannot downgrade retained SEC method authority")
    op.execute("DROP FUNCTION IF EXISTS guard_sec_method_policy_insert() CASCADE; DROP FUNCTION IF EXISTS guard_sec_method_authority_insert() CASCADE")
    for table in ["sec_method_policy_rules","sec_method_policy_versions","sec_economic_risk_attribute_reviews","sec_economic_classification_reviews"]:op.drop_table(table)
