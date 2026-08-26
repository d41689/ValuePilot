"""research case, immutable revision, origin, and event foundation

Revision ID: 20260720140000
Revises: 20260720130000
Create Date: 2026-07-20 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260720140000"
down_revision = "20260720130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Research-case revision IDs are BIGINT and are a documented polymorphic
    # source for manual val.fair_value facts.
    op.alter_column(
        "metric_facts",
        "source_ref_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )
    op.create_table(
        "research_cases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("stock_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=24), server_default="queued", nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=True),
        sa.Column("next_review_on", sa.Date(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("head_revision_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('queued', 'researching', 'monitoring', 'closed', 'voided')",
            name="ck_research_cases_state",
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('watch', 'own', 'pass')",
            name="ck_research_cases_decision",
        ),
        sa.CheckConstraint(
            "((state IN ('queued', 'researching') AND decision IS NULL "
            "AND next_review_on IS NULL AND void_reason IS NULL) OR "
            "(state = 'monitoring' AND decision IN ('watch', 'own') "
            "AND next_review_on IS NOT NULL AND void_reason IS NULL) OR "
            "(state = 'closed' AND decision = 'pass' "
            "AND next_review_on IS NULL AND void_reason IS NULL) OR "
            "(state = 'voided' AND decision IS NULL AND next_review_on IS NULL "
            "AND length(btrim(void_reason)) > 0))",
            name="ck_research_cases_state_shape",
        ),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_research_cases_active_user_stock",
        "research_cases",
        ["user_id", "stock_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('queued', 'researching', 'monitoring')"),
    )
    op.create_index(
        "ix_research_cases_user_state_updated",
        "research_cases",
        ["user_id", "state", "updated_at"],
    )

    op.create_table(
        "research_case_origins",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("origin_type", sa.String(length=32), nullable=False),
        sa.Column("origin_key", sa.String(length=240), nullable=False),
        sa.Column("source_version", sa.String(length=120), nullable=False),
        sa.Column("source_ref_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "origin_type IN ('manual', 'ticker_search', 'watchlist', 'screener', "
            "'oracle_lens', 'manager_holding', 'manager_change')",
            name="ck_research_case_origins_type",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["research_cases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_id", "origin_type", "origin_key", "source_version",
            name="uq_research_case_origins_source",
        ),
    )
    op.create_index(
        "ix_research_case_origins_case_created",
        "research_case_origins",
        ["case_id", "created_at"],
    )

    op.create_table(
        "research_case_revisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=True),
        sa.Column("variant_view", sa.Text(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("assumptions_json", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("risks_json", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("case_state", sa.String(length=24), nullable=False),
        sa.Column("is_qualified_decision", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("valuation_low", sa.Numeric(precision=24, scale=6), nullable=True),
        sa.Column("valuation_base", sa.Numeric(precision=24, scale=6), nullable=True),
        sa.Column("valuation_high", sa.Numeric(precision=24, scale=6), nullable=True),
        sa.Column("valuation_currency", sa.String(length=3), nullable=True),
        sa.Column("valuation_unavailable_reason", sa.Text(), nullable=True),
        sa.Column("valuation_as_of_date", sa.Date(), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=True),
        sa.Column("next_review_on", sa.Date(), nullable=True),
        sa.Column("snapshot_stock_id", sa.BigInteger(), nullable=False),
        sa.Column("stock_ticker", sa.String(length=40), nullable=False),
        sa.Column("stock_company_name", sa.Text(), nullable=False),
        sa.Column("stock_exchange", sa.String(length=40), nullable=False),
        sa.Column("stock_listing_exchange", sa.String(length=40), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("is_redacted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("redaction_content_hash", sa.String(length=64), nullable=True),
        sa.Column("redaction_reason", sa.Text(), nullable=True),
        sa.Column("redacted_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('watch', 'own', 'pass')",
            name="ck_research_case_revisions_decision",
        ),
        sa.CheckConstraint(
            "case_state IN ('queued', 'researching', 'monitoring', 'closed', 'voided')",
            name="ck_research_case_revisions_state",
        ),
        sa.CheckConstraint(
            "((valuation_low IS NULL AND valuation_base IS NULL "
            "AND valuation_high IS NULL AND valuation_currency IS NULL) OR "
            "(valuation_low IS NOT NULL AND valuation_base IS NOT NULL "
            "AND valuation_high IS NOT NULL AND valuation_currency = 'USD' "
            "AND valuation_unavailable_reason IS NULL "
            "AND valuation_low <= valuation_base "
            "AND valuation_base <= valuation_high))",
            name="ck_research_case_revisions_valuation_shape",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["research_cases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["redacted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["snapshot_stock_id"], ["stocks.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "revision_number", name="uq_research_case_revision_number"),
    )
    op.create_index(
        "ix_research_case_revisions_case_created",
        "research_case_revisions",
        ["case_id", "created_at"],
    )

    op.create_table(
        "research_case_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("correlation_id", sa.String(length=80), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["case_id"], ["research_cases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_id", "event_type", "correlation_id",
            name="uq_research_case_event_correlation",
        ),
    )
    op.create_index(
        "ix_research_case_events_case_created",
        "research_case_events",
        ["case_id", "created_at"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_research_append_only_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only; % is forbidden', TG_TABLE_NAME, TG_OP;
        END;
        $$
        """
    )
    for table_name in ("research_case_origins", "research_case_events"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_append_only
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_research_append_only_mutation()
            """
        )
    op.execute(
        """
        CREATE FUNCTION guard_research_revision_redaction()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'research_case_revisions is append-only; DELETE is forbidden';
            END IF;
            IF OLD.is_redacted
               OR NOT NEW.is_redacted
               OR (to_jsonb(NEW) - ARRAY[
                    'thesis', 'variant_view', 'decision_reason', 'assumptions_json',
                    'risks_json', 'evidence_json', 'valuation_unavailable_reason',
                    'is_redacted', 'redaction_content_hash', 'redaction_reason',
                    'redacted_by_user_id', 'redacted_at'
                  ]) IS DISTINCT FROM
                  (to_jsonb(OLD) - ARRAY[
                    'thesis', 'variant_view', 'decision_reason', 'assumptions_json',
                    'risks_json', 'evidence_json', 'valuation_unavailable_reason',
                    'is_redacted', 'redaction_content_hash', 'redaction_reason',
                    'redacted_by_user_id', 'redacted_at'
                  ]) THEN
                RAISE EXCEPTION 'research_case_revisions permits only one audited content redaction';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_research_case_revisions_redaction_only
        BEFORE UPDATE OR DELETE ON research_case_revisions
        FOR EACH ROW EXECUTE FUNCTION guard_research_revision_redaction()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_research_case_revisions_redaction_only "
        "ON research_case_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_research_revision_redaction()")
    for table_name in ("research_case_events", "research_case_origins"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only ON {table_name}"
        )
    op.execute("DROP FUNCTION IF EXISTS reject_research_append_only_mutation()")
    op.drop_index("ix_research_case_events_case_created", table_name="research_case_events")
    op.drop_table("research_case_events")
    op.drop_index("ix_research_case_revisions_case_created", table_name="research_case_revisions")
    op.drop_table("research_case_revisions")
    op.drop_index("ix_research_case_origins_case_created", table_name="research_case_origins")
    op.drop_table("research_case_origins")
    op.drop_index("ix_research_cases_user_state_updated", table_name="research_cases")
    op.drop_index("uq_research_cases_active_user_stock", table_name="research_cases")
    op.drop_table("research_cases")
    op.alter_column(
        "metric_facts",
        "source_ref_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="source_ref_id::integer",
    )
