"""Protect retained Piotroski ROIC-proxy authority.

Revision ID: 20260904160000
Revises: 20260904150000
Create Date: 2026-09-04 16:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260904160000"
down_revision = "20260904150000"
branch_labels = None
depends_on = None


def _guard_sql(*, protect_piotroski: bool) -> str:
    piotroski_declaration = "governs_piotroski boolean;" if protect_piotroski else ""
    piotroski_assignment = (
        """
          governs_piotroski :=
            (OLD.source_type='calculated'
             AND OLD.metric_key LIKE 'score.piotroski.%')
            OR
            (NEW.source_type='calculated'
             AND NEW.metric_key LIKE 'score.piotroski.%');
        """
        if protect_piotroski
        else ""
    )
    governed_calculation = (
        "governs_owner_earnings OR governs_piotroski"
        if protect_piotroski
        else "governs_owner_earnings"
    )
    return f"""
        CREATE OR REPLACE FUNCTION guard_ft07_metric_fact_authority_update()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          governs_owner_earnings boolean;
          {piotroski_declaration}
          governs_manual_valuation boolean;
          current_state_allowed boolean;
          valuation_content_allowed boolean;
        BEGIN
          governs_owner_earnings :=
            (OLD.source_type='calculated'
             AND OLD.metric_key LIKE 'owners\\_earnings\\_per\\_share%' ESCAPE '\\')
            OR
            (NEW.source_type='calculated'
             AND NEW.metric_key LIKE 'owners\\_earnings\\_per\\_share%' ESCAPE '\\');
          {piotroski_assignment}
          governs_manual_valuation :=
            (OLD.source_type='manual' AND OLD.metric_key='val.fair_value')
            OR
            (NEW.source_type='manual' AND NEW.metric_key='val.fair_value');
          current_state_allowed :=
            OLD.is_current IS NOT DISTINCT FROM NEW.is_current
            OR (OLD.is_current IS TRUE AND NEW.is_current IS FALSE);

          IF {governed_calculation} THEN
            IF ROW(
                OLD.id, OLD.user_id, OLD.stock_id, OLD.metric_key,
                OLD.value_json, OLD.value_numeric, OLD.value_text, OLD.unit,
                OLD.currency, OLD.period, OLD.period_type, OLD.period_end_date,
                OLD.as_of_date, OLD.source_document_id, OLD.source_type,
                OLD.source_ref_id, OLD.value_line_parse_run_id,
                OLD.value_line_legacy_revision, OLD.created_at
              ) IS DISTINCT FROM ROW(
                NEW.id, NEW.user_id, NEW.stock_id, NEW.metric_key,
                NEW.value_json, NEW.value_numeric, NEW.value_text, NEW.unit,
                NEW.currency, NEW.period, NEW.period_type, NEW.period_end_date,
                NEW.as_of_date, NEW.source_document_id, NEW.source_type,
                NEW.source_ref_id, NEW.value_line_parse_run_id,
                NEW.value_line_legacy_revision, NEW.created_at
              )
              OR NOT current_state_allowed THEN
              RAISE EXCEPTION 'FT-07 metric fact authority is immutable';
            END IF;
          END IF;

          IF governs_manual_valuation THEN
            IF ROW(
                OLD.id, OLD.user_id, OLD.stock_id, OLD.metric_key,
                OLD.value_numeric, OLD.value_text, OLD.unit, OLD.currency,
                OLD.period, OLD.period_type, OLD.period_end_date, OLD.as_of_date,
                OLD.source_document_id, OLD.source_type, OLD.source_ref_id,
                OLD.value_line_parse_run_id, OLD.value_line_legacy_revision,
                OLD.created_at
              ) IS DISTINCT FROM ROW(
                NEW.id, NEW.user_id, NEW.stock_id, NEW.metric_key,
                NEW.value_numeric, NEW.value_text, NEW.unit, NEW.currency,
                NEW.period, NEW.period_type, NEW.period_end_date, NEW.as_of_date,
                NEW.source_document_id, NEW.source_type, NEW.source_ref_id,
                NEW.value_line_parse_run_id, NEW.value_line_legacy_revision,
                NEW.created_at
              )
              OR OLD.value_json->'valuation_origin'
                   IS DISTINCT FROM NEW.value_json->'valuation_origin'
              OR NOT current_state_allowed THEN
              RAISE EXCEPTION 'FT-07 metric fact authority is immutable';
            END IF;

            valuation_content_allowed :=
              OLD.value_json IS NOT DISTINCT FROM NEW.value_json
              OR (
                OLD.value_numeric IS NULL
                AND OLD.value_json->>'status'='unavailable'
                AND NEW.value_json->>'status'='unavailable'
                AND NEW.value_json->>'reason'='[redacted]'
                AND NEW.value_json->>'redaction_content_hash' ~ '^[0-9a-f]{{64}}$'
                AND (OLD.value_json - 'reason' - 'redaction_content_hash'
                     - 'valuation_origin')
                    IS NOT DISTINCT FROM
                    (NEW.value_json - 'reason' - 'redaction_content_hash'
                     - 'valuation_origin')
              );
            IF NOT valuation_content_allowed THEN
              RAISE EXCEPTION 'FT-07 metric fact authority is immutable';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
    """


def _replace_guard(*, protect_piotroski: bool) -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metric_facts_ft07_authority_update "
        "ON metric_facts"
    )
    op.execute(_guard_sql(protect_piotroski=protect_piotroski))
    op.execute(
        "CREATE TRIGGER trg_metric_facts_ft07_authority_update "
        "BEFORE UPDATE ON metric_facts FOR EACH ROW "
        "EXECUTE FUNCTION guard_ft07_metric_fact_authority_update()"
    )


def upgrade() -> None:
    _replace_guard(protect_piotroski=True)


def downgrade() -> None:
    connection = op.get_bind()
    op.execute("LOCK TABLE metric_facts IN SHARE MODE")
    retained = connection.execute(
        sa.text(
            "SELECT count(*) FROM metric_facts "
            "WHERE source_type='calculated' AND metric_key LIKE 'score.piotroski.%'"
        )
    ).scalar_one()
    if retained:
        raise RuntimeError("cannot downgrade retained Piotroski method authority")
    _replace_guard(protect_piotroski=False)
