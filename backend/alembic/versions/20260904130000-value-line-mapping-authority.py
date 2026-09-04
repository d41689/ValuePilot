"""Make Value Line mapping identity database-owned and preserve manual history.

Revision ID: 20260904130000
Revises: 20260904120000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904130000"
down_revision = "20260904120000"
branch_labels = None
depends_on = None


CURRENT_POLICY_ID = (
    "value-line-resolved-v2:"
    "961bb30d1378694f1d79bd7f3dfe1693f3a50270d95664daddad16f1796f9d67"
)
CURRENT_POLICY_SHA256 = (
    "961bb30d1378694f1d79bd7f3dfe1693f3a50270d95664daddad16f1796f9d67"
)
PREVIOUS_POLICY_ID = (
    "value-line-resolved-v2:"
    "d16b1bc2809941ecbd9b1a8570a4689521b541e6b203ab829bca3e1040d44b98"
)
PREVIOUS_POLICY_SHA256 = (
    "d16b1bc2809941ecbd9b1a8570a4689521b541e6b203ab829bca3e1040d44b98"
)


def upgrade() -> None:
    op.create_table(
        "value_line_mapping_policies",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("policy_sha256", sa.String(length=64), nullable=False),
        sa.Column("spec_version", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('approved','superseded')",
            name="ck_value_line_mapping_policies_status",
        ),
        sa.CheckConstraint(
            "policy_sha256 ~ '^[0-9a-f]{64}$' AND "
            "id=('value-line-resolved-v' || spec_version::text || ':' || policy_sha256)",
            name="ck_value_line_mapping_policies_identity",
        ),
        sa.CheckConstraint(
            "(status='approved' AND retired_at IS NULL) OR "
            "(status='superseded' AND retired_at IS NOT NULL)",
            name="ck_value_line_mapping_policies_lifecycle",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO value_line_mapping_policies
              (id,policy_sha256,spec_version,parser_version,status,known_at,
               effective_from,retired_at)
            VALUES
              (:previous_id,:previous_sha,2,'value-line-v1','superseded',
               TIMESTAMPTZ '2026-09-04 00:00:00+00',
               TIMESTAMPTZ '2026-09-04 00:00:00+00',
               TIMESTAMPTZ '2026-09-04 00:00:00+00'),
              (:current_id,:current_sha,2,'value-line-v1','approved',
               TIMESTAMPTZ '2026-09-04 00:00:00+00',
               TIMESTAMPTZ '2026-09-04 00:00:00+00',NULL)
            """
        ).bindparams(
            previous_id=PREVIOUS_POLICY_ID,
            previous_sha=PREVIOUS_POLICY_SHA256,
            current_id=CURRENT_POLICY_ID,
            current_sha=CURRENT_POLICY_SHA256,
        )
    )

    bind = op.get_bind()
    unregistered_runs = bind.execute(
        sa.text(
            "SELECT count(*) FROM value_line_parse_runs r "
            "LEFT JOIN value_line_mapping_policies p "
            "ON p.id=r.source_mapping_version WHERE p.id IS NULL"
        )
    ).scalar_one()
    runless_parsed = bind.execute(
        sa.text(
            "SELECT count(*) FROM metric_facts WHERE source_type='parsed' "
            "AND NOT value_line_legacy_revision "
            "AND value_line_parse_run_id IS NULL"
        )
    ).scalar_one()
    runless_extractions = bind.execute(
        sa.text(
            "SELECT count(*) FROM metric_extractions "
            "WHERE NOT value_line_legacy_revision "
            "AND value_line_parse_run_id IS NULL"
        )
    ).scalar_one()
    duplicate_manual_current = bind.execute(
        sa.text(
            "SELECT count(*) FROM ("
            "SELECT 1 FROM metric_facts WHERE source_type='manual' AND is_current "
            "GROUP BY coalesce(user_id,0),stock_id,metric_key,coalesce(period_type,''),"
            "coalesce(period_end_date,DATE '0001-01-01'),"
            "coalesce(as_of_date,DATE '0001-01-01') HAVING count(*)>1"
            ") duplicates"
        )
    ).scalar_one()
    if unregistered_runs or runless_parsed or runless_extractions:
        raise RuntimeError(
            "Value Line mapping-authority upgrade refused: post-cutover rows "
            "lack an approved parse-run lineage"
        )
    if duplicate_manual_current:
        raise RuntimeError(
            "Value Line mapping-authority upgrade refused: ambiguous current "
            "manual fact slots require review"
        )

    op.create_foreign_key(
        "fk_value_line_parse_runs_mapping_policy",
        "value_line_parse_runs",
        "value_line_mapping_policies",
        ["source_mapping_version"],
        ["id"],
    )

    op.drop_index(
        "uq_metric_facts_nonparsed_document_period", table_name="metric_facts"
    )
    # SEC already has uq_metric_facts_current_sec_period. Calculated facts were
    # never constrained by the old document index because their document is
    # NULL. Manual facts need immutable history plus one exact current slot.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_metric_facts_current_manual_slot
        ON metric_facts (
          coalesce(user_id,0),stock_id,metric_key,coalesce(period_type,''),
          coalesce(period_end_date,DATE '0001-01-01'),
          coalesce(as_of_date,DATE '0001-01-01')
        ) WHERE source_type='manual' AND is_current=true
        """
    )

    op.execute(
        """
        CREATE FUNCTION guard_value_line_mapping_policy_registry() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION 'Value Line mapping policy registry is immutable';
        END $$;

        CREATE TRIGGER trg_value_line_mapping_policy_registry
        BEFORE INSERT OR UPDATE OR DELETE ON value_line_mapping_policies
        FOR EACH ROW EXECUTE FUNCTION guard_value_line_mapping_policy_registry();

        CREATE OR REPLACE FUNCTION guard_value_line_parse_run_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE policy_row value_line_mapping_policies%ROWTYPE;
        BEGIN
          IF TG_OP='INSERT' THEN
            SELECT * INTO policy_row FROM value_line_mapping_policies
              WHERE id=NEW.source_mapping_version;
            IF NOT FOUND OR policy_row.status<>'approved'
               OR policy_row.parser_version<>NEW.parser_version
               OR NOT EXISTS (
                 SELECT 1 FROM pdf_documents d
                 WHERE d.id=NEW.document_id AND d.user_id=NEW.user_id
               )
            THEN
              RAISE EXCEPTION 'Value Line parse run requires an approved mapping policy';
            END IF;
            NEW.status := 'running';
            NEW.created_txid := txid_current();
            NEW.started_at := clock_timestamp();
            NEW.completed_at := NULL;
            RETURN NEW;
          END IF;
          IF TG_OP='DELETE' THEN
            IF EXISTS (SELECT 1 FROM pdf_documents WHERE id=OLD.document_id) THEN
              RAISE EXCEPTION 'Value Line parse runs are append-only';
            END IF;
            RETURN OLD;
          END IF;
          IF OLD.created_txid<>txid_current() OR OLD.status<>'running'
             OR NEW.status NOT IN ('succeeded','failed')
             OR ROW(OLD.id,OLD.user_id,OLD.document_id,OLD.parser_version,
                    OLD.source_mapping_version,OLD.created_txid,OLD.started_at)
                IS DISTINCT FROM
                ROW(NEW.id,NEW.user_id,NEW.document_id,NEW.parser_version,
                    NEW.source_mapping_version,NEW.created_txid,NEW.started_at)
          THEN
            RAISE EXCEPTION 'Value Line parse run may finalize only in its creating transaction';
          END IF;
          NEW.completed_at := clock_timestamp();
          RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION guard_value_line_extraction_run_binding()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE run_row value_line_parse_runs%ROWTYPE;
        BEGIN
          IF TG_OP='INSERT' THEN
            NEW.value_line_legacy_revision := false;
          END IF;
          IF TG_OP='UPDATE' THEN
            IF NEW.value_line_parse_run_id IS DISTINCT FROM OLD.value_line_parse_run_id
               OR NEW.value_line_legacy_revision IS DISTINCT FROM OLD.value_line_legacy_revision
               OR ((OLD.value_line_parse_run_id IS NOT NULL OR OLD.value_line_legacy_revision)
                   AND ROW(NEW.id,NEW.user_id,NEW.document_id,NEW.page_number,
                           NEW.field_key,NEW.raw_value_text,NEW.original_text_snippet,
                           NEW.parsed_value_json::text,NEW.unit,NEW.currency,NEW.period,
                           NEW.period_type,NEW.period_end_date,NEW.as_of_date,
                           NEW.confidence_score,NEW.bbox_json::text,
                           NEW.parser_template_id,NEW.parser_version,NEW.created_at,
                           NEW.target_year_range,NEW.corrected_by_user,NEW.corrected_at)
                       IS DISTINCT FROM
                       ROW(OLD.id,OLD.user_id,OLD.document_id,OLD.page_number,
                           OLD.field_key,OLD.raw_value_text,OLD.original_text_snippet,
                           OLD.parsed_value_json::text,OLD.unit,OLD.currency,OLD.period,
                           OLD.period_type,OLD.period_end_date,OLD.as_of_date,
                           OLD.confidence_score,OLD.bbox_json::text,
                           OLD.parser_template_id,OLD.parser_version,OLD.created_at,
                           OLD.target_year_range,OLD.corrected_by_user,OLD.corrected_at))
            THEN
              RAISE EXCEPTION 'Value Line extraction run binding is immutable';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.value_line_parse_run_id IS NULL THEN
            RAISE EXCEPTION 'Value Line extraction requires a creating parse run';
          END IF;
          SELECT * INTO run_row FROM value_line_parse_runs
            WHERE id=NEW.value_line_parse_run_id;
          IF NOT FOUND OR run_row.status<>'running'
             OR run_row.created_txid<>txid_current()
             OR run_row.user_id<>NEW.user_id
             OR run_row.document_id<>NEW.document_id
          THEN
            RAISE EXCEPTION 'Value Line extraction must bind its creating parse run';
          END IF;
          RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION guard_value_line_fact_run_binding()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE run_row value_line_parse_runs%ROWTYPE;
        BEGIN
          IF TG_OP='INSERT' THEN
            NEW.value_line_legacy_revision := false;
          END IF;
          IF TG_OP='UPDATE' THEN
            IF NEW.source_type='parsed'
               AND OLD.source_type IS DISTINCT FROM 'parsed'
               AND NEW.value_line_parse_run_id IS NULL
            THEN
              RAISE EXCEPTION 'Value Line parsed fact requires a creating parse run';
            END IF;
            IF NEW.value_line_parse_run_id IS DISTINCT FROM OLD.value_line_parse_run_id
               OR NEW.value_line_legacy_revision IS DISTINCT FROM OLD.value_line_legacy_revision
               OR (OLD.source_type IS DISTINCT FROM NEW.source_type
                   AND (OLD.source_type='parsed' OR NEW.source_type='parsed'))
               OR ((OLD.value_line_parse_run_id IS NOT NULL OR OLD.value_line_legacy_revision)
                   AND OLD.is_current=false AND NEW.is_current=true)
               OR ((OLD.value_line_parse_run_id IS NOT NULL OR OLD.value_line_legacy_revision)
                   AND ROW(NEW.id,NEW.user_id,NEW.stock_id,NEW.metric_key,
                           NEW.value_json,NEW.value_numeric,NEW.value_text,NEW.unit,
                           NEW.currency,NEW.period,NEW.period_type,NEW.period_end_date,
                           NEW.as_of_date,NEW.source_document_id,NEW.source_type,
                           NEW.source_ref_id,NEW.created_at)
                       IS DISTINCT FROM
                       ROW(OLD.id,OLD.user_id,OLD.stock_id,OLD.metric_key,
                           OLD.value_json,OLD.value_numeric,OLD.value_text,OLD.unit,
                           OLD.currency,OLD.period,OLD.period_type,OLD.period_end_date,
                           OLD.as_of_date,OLD.source_document_id,OLD.source_type,
                           OLD.source_ref_id,OLD.created_at))
            THEN
              RAISE EXCEPTION 'Value Line fact run binding is immutable';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.source_type='parsed' AND NEW.value_line_parse_run_id IS NULL THEN
            RAISE EXCEPTION 'Value Line parsed fact requires a creating parse run';
          END IF;
          IF NEW.value_line_parse_run_id IS NULL THEN RETURN NEW; END IF;
          SELECT * INTO run_row FROM value_line_parse_runs
            WHERE id=NEW.value_line_parse_run_id;
          IF NOT FOUND OR run_row.status<>'running'
             OR run_row.created_txid<>txid_current()
             OR NEW.source_type<>'parsed'
             OR run_row.user_id<>NEW.user_id
             OR run_row.document_id IS DISTINCT FROM NEW.source_document_id
          THEN
            RAISE EXCEPTION 'Value Line fact must bind its creating parse run';
          END IF;
          NEW.value_json := coalesce(NEW.value_json,'{}'::jsonb)
            || jsonb_build_object(
                 'source_mapping_version',run_row.source_mapping_version,
                 'source_parser_version',run_row.parser_version
               );
          RETURN NEW;
        END $$;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    run_count = bind.execute(
        sa.text("SELECT count(*) FROM value_line_parse_runs")
    ).scalar_one()
    duplicate_old_slots = bind.execute(
        sa.text(
            "SELECT count(*) FROM ("
            "SELECT 1 FROM metric_facts WHERE source_type<>'parsed' "
            "AND stock_id IS NOT NULL AND metric_key IS NOT NULL "
            "AND period_type IS NOT NULL AND period_end_date IS NOT NULL "
            "AND source_document_id IS NOT NULL "
            "GROUP BY stock_id,metric_key,period_type,period_end_date,source_document_id "
            "HAVING count(*)>1) duplicates"
        )
    ).scalar_one()
    if run_count or duplicate_old_slots:
        raise RuntimeError(
            "downgrade refused: approved mapping lineage or manual history "
            "cannot be represented by revision 20260904120000"
        )

    op.execute(
        """
        DROP TRIGGER trg_value_line_mapping_policy_registry
          ON value_line_mapping_policies;
        DROP FUNCTION guard_value_line_mapping_policy_registry();

        CREATE OR REPLACE FUNCTION guard_value_line_parse_run_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          IF TG_OP='INSERT' THEN
            NEW.status := 'running'; NEW.created_txid := txid_current();
            NEW.started_at := clock_timestamp(); NEW.completed_at := NULL;
            RETURN NEW;
          END IF;
          IF TG_OP='DELETE' THEN
            IF EXISTS (SELECT 1 FROM pdf_documents WHERE id=OLD.document_id) THEN
              RAISE EXCEPTION 'Value Line parse runs are append-only';
            END IF;
            RETURN OLD;
          END IF;
          IF OLD.created_txid<>txid_current() OR OLD.status<>'running'
             OR NEW.status NOT IN ('succeeded','failed')
             OR ROW(OLD.id,OLD.user_id,OLD.document_id,OLD.parser_version,
                    OLD.source_mapping_version,OLD.created_txid,OLD.started_at)
                IS DISTINCT FROM
                ROW(NEW.id,NEW.user_id,NEW.document_id,NEW.parser_version,
                    NEW.source_mapping_version,NEW.created_txid,NEW.started_at)
          THEN
            RAISE EXCEPTION 'Value Line parse run may finalize only in its creating transaction';
          END IF;
          NEW.completed_at := clock_timestamp(); RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION guard_value_line_extraction_run_binding()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE run_row value_line_parse_runs%ROWTYPE;
        BEGIN
          IF TG_OP='INSERT' THEN NEW.value_line_legacy_revision := false; END IF;
          IF TG_OP='UPDATE' THEN
            IF NEW.value_line_parse_run_id IS DISTINCT FROM OLD.value_line_parse_run_id
               OR NEW.value_line_legacy_revision IS DISTINCT FROM OLD.value_line_legacy_revision
               OR ((OLD.value_line_parse_run_id IS NOT NULL OR OLD.value_line_legacy_revision)
                   AND ROW(NEW.id,NEW.user_id,NEW.document_id,NEW.page_number,
                           NEW.field_key,NEW.raw_value_text,NEW.original_text_snippet,
                           NEW.parsed_value_json::text,NEW.unit,NEW.currency,NEW.period,
                           NEW.period_type,NEW.period_end_date,NEW.as_of_date,
                           NEW.confidence_score,NEW.bbox_json::text,
                           NEW.parser_template_id,NEW.parser_version,NEW.created_at,
                           NEW.target_year_range)
                       IS DISTINCT FROM
                       ROW(OLD.id,OLD.user_id,OLD.document_id,OLD.page_number,
                           OLD.field_key,OLD.raw_value_text,OLD.original_text_snippet,
                           OLD.parsed_value_json::text,OLD.unit,OLD.currency,OLD.period,
                           OLD.period_type,OLD.period_end_date,OLD.as_of_date,
                           OLD.confidence_score,OLD.bbox_json::text,
                           OLD.parser_template_id,OLD.parser_version,OLD.created_at,
                           OLD.target_year_range))
            THEN RAISE EXCEPTION 'Value Line extraction run binding is immutable'; END IF;
            RETURN NEW;
          END IF;
          IF NEW.value_line_parse_run_id IS NULL THEN RETURN NEW; END IF;
          SELECT * INTO run_row FROM value_line_parse_runs WHERE id=NEW.value_line_parse_run_id;
          IF NOT FOUND OR run_row.status<>'running' OR run_row.created_txid<>txid_current()
             OR run_row.user_id<>NEW.user_id OR run_row.document_id<>NEW.document_id
          THEN RAISE EXCEPTION 'Value Line extraction must bind its creating parse run'; END IF;
          RETURN NEW;
        END $$;

        CREATE OR REPLACE FUNCTION guard_value_line_fact_run_binding()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE run_row value_line_parse_runs%ROWTYPE;
        BEGIN
          IF TG_OP='INSERT' THEN NEW.value_line_legacy_revision := false; END IF;
          IF TG_OP='UPDATE' THEN
            IF NEW.value_line_parse_run_id IS DISTINCT FROM OLD.value_line_parse_run_id
               OR NEW.value_line_legacy_revision IS DISTINCT FROM OLD.value_line_legacy_revision
               OR ((OLD.value_line_parse_run_id IS NOT NULL OR OLD.value_line_legacy_revision)
                   AND OLD.is_current=false AND NEW.is_current=true)
               OR ((OLD.value_line_parse_run_id IS NOT NULL OR OLD.value_line_legacy_revision)
                   AND ROW(NEW.id,NEW.user_id,NEW.stock_id,NEW.metric_key,NEW.value_json,
                           NEW.value_numeric,NEW.value_text,NEW.unit,NEW.currency,NEW.period,
                           NEW.period_type,NEW.period_end_date,NEW.as_of_date,
                           NEW.source_document_id,NEW.source_type,NEW.source_ref_id,NEW.created_at)
                       IS DISTINCT FROM
                       ROW(OLD.id,OLD.user_id,OLD.stock_id,OLD.metric_key,OLD.value_json,
                           OLD.value_numeric,OLD.value_text,OLD.unit,OLD.currency,OLD.period,
                           OLD.period_type,OLD.period_end_date,OLD.as_of_date,
                           OLD.source_document_id,OLD.source_type,OLD.source_ref_id,OLD.created_at))
            THEN RAISE EXCEPTION 'Value Line fact run binding is immutable'; END IF;
            RETURN NEW;
          END IF;
          IF NEW.value_line_parse_run_id IS NULL THEN RETURN NEW; END IF;
          SELECT * INTO run_row FROM value_line_parse_runs WHERE id=NEW.value_line_parse_run_id;
          IF NOT FOUND OR run_row.status<>'running' OR run_row.created_txid<>txid_current()
             OR NEW.source_type<>'parsed' OR run_row.user_id<>NEW.user_id
             OR run_row.document_id IS DISTINCT FROM NEW.source_document_id
          THEN RAISE EXCEPTION 'Value Line fact must bind its creating parse run'; END IF;
          RETURN NEW;
        END $$;
        """
    )
    op.drop_index("uq_metric_facts_current_manual_slot", table_name="metric_facts")
    op.create_index(
        "uq_metric_facts_nonparsed_document_period",
        "metric_facts",
        ["stock_id", "metric_key", "period_type", "period_end_date", "source_document_id"],
        unique=True,
        postgresql_where=sa.text("source_type<>'parsed'"),
    )
    op.drop_constraint(
        "fk_value_line_parse_runs_mapping_policy",
        "value_line_parse_runs",
        type_="foreignkey",
    )
    op.drop_table("value_line_mapping_policies")
