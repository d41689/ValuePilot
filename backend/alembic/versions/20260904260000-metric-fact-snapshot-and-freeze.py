"""Freeze governed facts and index bounded currentness snapshots.

Revision ID: 20260904260000
Revises: 20260904250000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260904260000"
down_revision = "20260904250000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Currentness readers constrain immutable slot columns before ranking.  The
    # two complementary indexes keep stock and document scoped reads out of a
    # full-history sort.
    op.create_index(
        "ix_metric_fact_currentness_scope_known",
        "metric_fact_currentness_revisions",
        [
            "stock_id",
            "metric_key",
            "fact_id",
            sa.text("known_at DESC"),
            sa.text("id DESC"),
        ],
    )
    op.create_index(
        "ix_metric_fact_currentness_metric_known",
        "metric_fact_currentness_revisions",
        [
            "metric_key",
            "fact_id",
            sa.text("known_at DESC"),
            sa.text("id DESC"),
        ],
    )
    op.create_index(
        "ix_metric_fact_currentness_document_known",
        "metric_fact_currentness_revisions",
        [
            "source_document_id",
            "fact_id",
            sa.text("known_at DESC"),
            sa.text("id DESC"),
        ],
    )

    # Document retirement is the existing legal ownership boundary for facts
    # derived from an uploaded report.  Make that parent operation the deletion
    # mechanism instead of permitting a free-standing fact DELETE.
    op.drop_constraint(
        "fk_metric_facts_source_document_id_pdf_documents",
        "metric_facts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_metric_facts_source_document_cascade",
        "metric_facts",
        "pdf_documents",
        ["source_document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "fk_metric_facts_value_line_report_identity_revision",
        "metric_facts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_metric_facts_report_identity_cascade",
        "metric_facts",
        "value_line_document_report_identity_revisions",
        ["value_line_report_identity_revision_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute(
        r"""
        CREATE FUNCTION guard_governed_metric_fact_immutability()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          governed boolean;
          redacted_json jsonb;
          redacted_json_with_hash jsonb;
        BEGIN
          governed := OLD.source_type IN ('manual','calculated','derived');

          IF TG_OP='DELETE' THEN
            IF NOT governed THEN
              RETURN OLD;
            END IF;
            IF OLD.source_document_id IS NOT NULL
               AND pg_trigger_depth()>1
               AND NOT EXISTS (
                 SELECT 1 FROM pdf_documents d WHERE d.id=OLD.source_document_id
               )
            THEN
              RETURN OLD;
            END IF;
            IF OLD.value_line_report_identity_revision_id IS NOT NULL
               AND pg_trigger_depth()>1
               AND NOT EXISTS (
                 SELECT 1 FROM value_line_document_report_identity_revisions r
                 WHERE r.id=OLD.value_line_report_identity_revision_id
               )
            THEN
              RETURN OLD;
            END IF;
            RAISE EXCEPTION 'metric facts cannot be deleted directly';
          END IF;

          IF NOT governed THEN
            RETURN NEW;
          END IF;

          IF OLD.is_current=false AND NEW.is_current=true THEN
            RAISE EXCEPTION 'governed metric facts cannot be reactivated';
          END IF;

          -- The only content mutation retained for privacy is a one-way
          -- tombstone of user-authored explanatory text. Numeric truth,
          -- provenance, status and valuation origin remain byte-for-byte.
          redacted_json := jsonb_set(
            COALESCE(OLD.value_json,'{}'::jsonb),
            '{reason}',
            '"[redacted]"'::jsonb,
            true
          );
          redacted_json_with_hash := redacted_json ||
            CASE
              WHEN NEW.value_json ? 'redaction_content_hash'
              THEN jsonb_build_object(
                'redaction_content_hash', NEW.value_json->'redaction_content_hash'
              )
              ELSE '{}'::jsonb
            END;

          IF ROW(
               OLD.value_numeric,OLD.value_text,OLD.unit,OLD.currency,OLD.period,
               OLD.created_at,OLD.value_line_parse_run_id,
               OLD.value_line_legacy_revision,
               OLD.value_line_report_identity_revision_id,
               OLD.value_line_fact_known_at,OLD.value_line_created_txid
             ) IS DISTINCT FROM ROW(
               NEW.value_numeric,NEW.value_text,NEW.unit,NEW.currency,NEW.period,
               NEW.created_at,NEW.value_line_parse_run_id,
               NEW.value_line_legacy_revision,
               NEW.value_line_report_identity_revision_id,
               NEW.value_line_fact_known_at,NEW.value_line_created_txid
             ) OR (
               OLD.value_json IS DISTINCT FROM NEW.value_json
               AND NOT (
                 OLD.source_type='manual'
                 AND OLD.value_numeric IS NULL
                 AND COALESCE(OLD.value_json,'{}'::jsonb) ? 'reason'
                 AND NEW.value_json IN (redacted_json,redacted_json_with_hash)
                 AND (
                   NOT (NEW.value_json ? 'redaction_content_hash')
                   OR NEW.value_json->>'redaction_content_hash' ~ '^[0-9a-f]{64}$'
                 )
               )
             ) OR (
               OLD.source_type<>'manual'
               AND OLD.source_document_id IS DISTINCT FROM NEW.source_document_id
             )
          THEN
            RAISE EXCEPTION 'governed metric fact content and provenance are immutable';
          END IF;
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_zzz_governed_metric_fact_immutable
        BEFORE UPDATE OR DELETE ON metric_facts
        FOR EACH ROW EXECUTE FUNCTION guard_governed_metric_fact_immutability();
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            "SELECT count(*) FROM metric_facts "
            "WHERE source_type IN ('manual','calculated','derived')"
        )
    ).scalar_one():
        raise RuntimeError(
            "downgrade refused: cannot remove governed metric-fact immutability"
        )
    op.execute(
        "DROP TRIGGER trg_zzz_governed_metric_fact_immutable ON metric_facts; "
        "DROP FUNCTION guard_governed_metric_fact_immutability()"
    )
    op.drop_constraint(
        "fk_metric_facts_report_identity_cascade",
        "metric_facts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_metric_facts_value_line_report_identity_revision",
        "metric_facts",
        "value_line_document_report_identity_revisions",
        ["value_line_report_identity_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "fk_metric_facts_source_document_cascade", "metric_facts", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_metric_facts_source_document_id_pdf_documents",
        "metric_facts",
        "pdf_documents",
        ["source_document_id"],
        ["id"],
    )
    op.drop_index(
        "ix_metric_fact_currentness_document_known",
        table_name="metric_fact_currentness_revisions",
    )
    op.drop_index(
        "ix_metric_fact_currentness_metric_known",
        table_name="metric_fact_currentness_revisions",
    )
    op.drop_index(
        "ix_metric_fact_currentness_scope_known",
        table_name="metric_fact_currentness_revisions",
    )
