"""Authorize typed nonfinancial amendments without inventing affected slots.

Revision ID: 20260901170000
Revises: 20260901160000
"""

from alembic import op


revision = "20260901170000"
down_revision = "20260901160000"
branch_labels = None
depends_on = None


def _audit_guard(*, allow_nonfinancial: bool) -> str:
    nonfinancial_reason = (
        ",'nonfinancial_amendment_no_slot_effect'" if allow_nonfinancial else ""
    )
    nonfinancial_checks = (
        """
        IF NEW.reason_code='nonfinancial_amendment_no_slot_effect' THEN
          IF NEW.mapping_rule_id IS NOT NULL
             OR jsonb_array_length(NEW.raw_fact_ids_json)<>0
             OR NEW.detail IS NULL
             OR left(NEW.detail,20)<>'filing_authority_id='
             OR NOT EXISTS (
               SELECT 1
               FROM sec_metric_publication_run_sources source
               JOIN sec_financial_parse_runs parse ON parse.id=source.parse_run_id
               JOIN sec_financial_filings filing ON filing.id=source.filing_id
               WHERE source.publication_run_id=NEW.publication_run_id
                 AND filing.accession_no=substr(NEW.detail,21)
                 AND source.accession_no=filing.accession_no
                 AND filing.is_amendment AND right(filing.form_type,2)='/A'
                 AND parse.status='succeeded'
                 AND NOT EXISTS (
                   SELECT 1
                   FROM sec_raw_xbrl_facts raw
                   JOIN sec_statement_fact_authorities authority
                     ON authority.raw_fact_id=raw.id
                    AND authority.parse_run_id=raw.parse_run_id
                   JOIN sec_metric_mapping_rule_concepts mapped_concept
                     ON mapped_concept.local_name=
                       CASE WHEN strpos(raw.concept,':')>0
                            THEN split_part(raw.concept,':',2) ELSE raw.concept END
                   JOIN sec_metric_mapping_rules mapped_rule
                     ON mapped_rule.id=mapped_concept.mapping_rule_id
                    AND mapped_rule.mapping_version_id=run.mapping_version_id
                   JOIN sec_metric_mapping_version_namespaces namespace
                     ON namespace.mapping_version_id=mapped_rule.mapping_version_id
                    AND namespace.authority=mapped_concept.namespace_authority
                    AND namespace.namespace_uri=raw.concept_namespace_uri
                   WHERE raw.parse_run_id=parse.id
                 )
             )
          THEN RAISE EXCEPTION 'nonfinancial amendment audit authority mismatch'; END IF;
        END IF;
        """
        if allow_nonfinancial
        else ""
    )
    return f"""
    CREATE OR REPLACE FUNCTION guard_sec_metric_publication_audit_insert()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE run sec_metric_publication_runs%ROWTYPE;
            rule sec_metric_mapping_rules%ROWTYPE;
    BEGIN
      NEW.created_at:=clock_timestamp();
      NEW.known_at:=NEW.created_at;
      NEW.created_txid:=txid_current();
      SELECT * INTO run FROM sec_metric_publication_runs
        WHERE id=NEW.publication_run_id;
      IF run.id IS NULL THEN
        RAISE EXCEPTION 'publication audit run authority mismatch';
      END IF;
      IF NEW.mapping_rule_id IS NOT NULL THEN
        SELECT * INTO rule FROM sec_metric_mapping_rules
          WHERE id=NEW.mapping_rule_id;
        IF rule.id IS NULL OR rule.mapping_version_id<>run.mapping_version_id THEN
          RAISE EXCEPTION 'publication audit mapping authority mismatch';
        END IF;
      END IF;
      IF NEW.reason_code NOT IN (
        'duplicate_identical_candidate_not_selected',
        'lower_priority_concept_not_selected',
        'unresolved_amendment_parse_failure'{nonfinancial_reason},
        'unresolved_conflicting_candidates','unresolved_context',
        'unresolved_currency','unresolved_custom_concept',
        'unresolved_derived_context_mismatch','unresolved_derived_cross_stock',
        'unresolved_derived_currency_mismatch',
        'unresolved_derived_filing_authority_mismatch',
        'unresolved_derived_fiscal_year_mismatch',
        'unresolved_derived_input_after_cutoff',
        'unresolved_derived_period_identity','unresolved_derived_unit_mismatch',
        'unresolved_dimensions','unresolved_missing_derived_quarter_input',
        'unresolved_period','unresolved_period_filing_cycle_mismatch',
        'unresolved_unit','unresolved_unsupported_form_semantics',
        'unresolved_value'
      ) THEN
        RAISE EXCEPTION 'publication audit reason is not approved';
      END IF;
      IF EXISTS (
           SELECT 1 FROM jsonb_array_elements(NEW.raw_fact_ids_json) value
           WHERE jsonb_typeof(value)<>'number'
              OR (value#>>'{{}}')::bigint<=0
         )
         OR (SELECT count(*) FROM jsonb_array_elements(NEW.raw_fact_ids_json))<>
            (SELECT count(DISTINCT value#>>'{{}}')
             FROM jsonb_array_elements(NEW.raw_fact_ids_json) value)
      THEN RAISE EXCEPTION 'publication audit raw identity mismatch'; END IF;
      IF NEW.reason_code='unresolved_amendment_parse_failure'
         AND jsonb_array_length(NEW.raw_fact_ids_json)<>0
      THEN RAISE EXCEPTION 'failed amendment run audit cannot claim raw identity';
      END IF;
      {nonfinancial_checks}
      IF NEW.reason_code NOT IN (
           'unresolved_amendment_parse_failure'{nonfinancial_reason}
         ) AND EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(NEW.raw_fact_ids_json) value
        WHERE NOT EXISTS (
          SELECT 1 FROM sec_raw_xbrl_facts raw
          JOIN sec_metric_publication_run_sources source
            ON source.parse_run_id=raw.parse_run_id
          WHERE source.publication_run_id=NEW.publication_run_id
            AND raw.id=value::bigint
            AND (
              NEW.mapping_rule_id IS NULL
              OR rule.metadata_json->'ordered_concepts' ?
                CASE WHEN strpos(raw.concept,':')>0
                     THEN split_part(raw.concept,':',2) ELSE raw.concept END
            )
        )
      ) THEN RAISE EXCEPTION 'publication audit raw source authority mismatch';
      END IF;
      RETURN NEW;
    END $$;
    """


def upgrade() -> None:
    op.execute(_audit_guard(allow_nonfinancial=True))


def downgrade() -> None:
    op.execute(
        "LOCK TABLE sec_metric_publication_audits IN SHARE ROW EXCLUSIVE MODE"
    )
    if op.get_bind().exec_driver_sql(
        """SELECT count(*) FROM sec_metric_publication_audits
           WHERE reason_code='nonfinancial_amendment_no_slot_effect'"""
    ).scalar_one():
        raise RuntimeError(
            "downgrade refused: retained nonfinancial amendment authority exists"
        )
    op.execute(_audit_guard(allow_nonfinancial=False))
