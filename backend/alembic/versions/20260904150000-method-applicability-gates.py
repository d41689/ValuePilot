"""Approve versioned industry and method applicability gates.

Revision ID: 20260904150000
Revises: 20260904140000
Create Date: 2026-09-04 15:00:00
"""

from __future__ import annotations

import hashlib
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260904150000"
down_revision = "20260904140000"
branch_labels = None
depends_on = None


POLICY_ID = "analysis-method-applicability-v2"
POLICY_EFFECTIVE_FROM = "2026-09-04T00:00:00+00:00"
RISK_ATTRIBUTES = ["high_sbc", "acquisitive", "cyclical", "commodity_exposed"]
ECONOMIC_CLASSES = [
    "ordinary",
    "bank",
    "insurer",
    "reit",
    "other_financial",
    "unclassified",
]
METHODS = ["owner_earnings", "roic", "per_share_trend", "system_valuation"]


def _rules() -> list[dict[str, object]]:
    approved = {
        "owner_earnings": {
            "method_version_id": "owner-earnings-per-share-v1",
            "required_evidence_json": [
                "per_share.eps",
                "is.depreciation",
                "equity.shares_outstanding",
                "per_share.capital_spending",
            ],
            "required_adjustments_json": ["all_capex_treated_as_maintenance"],
            "required_outputs_json": [
                "owners_earnings_per_share",
                "owners_earnings_per_share_normalized",
            ],
        },
        "roic": {
            "method_version_id": "value-line-return-on-total-capital-v1",
            "required_evidence_json": ["returns.total_capital"],
            "required_adjustments_json": ["value_line_adjusted_definition"],
            "required_outputs_json": ["returns.total_capital"],
        },
        "per_share_trend": {
            "method_version_id": "value-line-per-share-rates-v1",
            "required_evidence_json": [
                "rates.<metric>.cagr_10y",
                "rates.<metric>.cagr_5y",
                "rates.<metric>.cagr_est",
            ],
            "required_adjustments_json": ["value_line_per_share_basis"],
            "required_outputs_json": ["rates.<metric>.cagr_<horizon>"],
        },
    }
    rows: list[dict[str, object]] = []
    for economic_class in ECONOMIC_CLASSES:
        for method_key in METHODS:
            base: dict[str, object] = {
                "method_policy_version_id": POLICY_ID,
                "method_key": method_key,
                "economic_class": economic_class,
                "method_version_id": None,
                "applicability": "unsupported",
                "required_evidence_json": [],
                "required_outputs_json": [],
                "required_risk_reviews_json": [],
                "required_adjustments_json": [],
                "unsupported_reason_code": (
                    "system_valuation_method_pending_ft09"
                    if economic_class == "ordinary" and method_key == "system_valuation"
                    else f"{method_key}_unsupported_for_{economic_class}"
                ),
            }
            if economic_class == "ordinary" and method_key in approved:
                base.update(approved[method_key])
                base.update(
                    applicability="approved",
                    required_risk_reviews_json=RISK_ATTRIBUTES,
                    unsupported_reason_code=None,
                )
            elif economic_class == "ordinary" and method_key == "system_valuation":
                base["required_risk_reviews_json"] = RISK_ATTRIBUTES
            rows.append(base)
    return rows


POLICY_RULES = _rules()
POLICY_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "id": POLICY_ID,
            "effective_from": POLICY_EFFECTIVE_FROM,
            "rules": POLICY_RULES,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()


def _policy_table() -> sa.Table:
    return sa.table(
        "sec_method_policy_versions",
        sa.column("id"),
        sa.column("status"),
        sa.column("effective_from"),
        sa.column("policy_sha256"),
        sa.column("review_reason"),
    )


def _rule_table() -> sa.Table:
    return sa.table(
        "sec_method_policy_rules",
        sa.column("method_policy_version_id"),
        sa.column("method_key"),
        sa.column("economic_class"),
        sa.column("method_version_id"),
        sa.column("applicability"),
        sa.column("required_evidence_json", postgresql.JSONB()),
        sa.column("required_outputs_json", postgresql.JSONB()),
        sa.column("required_risk_reviews_json", postgresql.JSONB()),
        sa.column("required_adjustments_json", postgresql.JSONB()),
        sa.column("unsupported_reason_code"),
    )


def _create_policy_insert_guard() -> None:
    op.execute(
        """
        CREATE TRIGGER trg_sec_method_policy_insert_guard
        BEFORE INSERT ON sec_method_policy_versions
        FOR EACH ROW EXECUTE FUNCTION guard_sec_method_policy_insert()
        """
    )


def upgrade() -> None:
    connection = op.get_bind()
    op.execute(
        "LOCK TABLE sec_economic_classification_reviews, "
        "sec_economic_risk_attribute_reviews IN SHARE MODE"
    )
    untrusted_legacy_reviews = connection.execute(
        sa.text(
            """
            SELECT count(*)
            FROM (
              SELECT reviewer_user_id, review_reason
              FROM sec_economic_classification_reviews
              UNION ALL
              SELECT reviewer_user_id, review_reason
              FROM sec_economic_risk_attribute_reviews
            ) reviews
            LEFT JOIN users reviewer ON reviewer.id=reviews.reviewer_user_id
            WHERE reviewer.id IS NULL OR reviewer.role<>'admin'
               OR reviewer.is_active IS NOT TRUE
               OR length(btrim(reviews.review_reason))=0
            """
        )
    ).scalar_one()
    if untrusted_legacy_reviews:
        raise RuntimeError("cannot adopt untrusted legacy method reviews into FT-07")
    conflicting_legacy_lineages = connection.execute(
        sa.text(
            """
            SELECT count(*)
            FROM (
              SELECT stock_id, 'classification'::text AS review_kind
              FROM sec_economic_classification_reviews
              WHERE supersedes_review_id IS NULL
              GROUP BY stock_id
              HAVING count(*) > 1
              UNION ALL
              SELECT stock_id, risk_attribute AS review_kind
              FROM sec_economic_risk_attribute_reviews
              WHERE supersedes_review_id IS NULL
              GROUP BY stock_id, risk_attribute
              HAVING count(*) > 1
            ) conflicts
            """
        )
    ).scalar_one()
    if conflicting_legacy_lineages:
        raise RuntimeError("cannot adopt conflicting legacy method review lineages")

    op.create_check_constraint(
        "ck_sec_economic_classification_review_reason",
        "sec_economic_classification_reviews",
        "length(btrim(review_reason)) > 0",
    )
    op.create_check_constraint(
        "ck_sec_economic_risk_review_reason",
        "sec_economic_risk_attribute_reviews",
        "length(btrim(review_reason)) > 0",
    )
    op.execute(
        """
        DROP TRIGGER trg_sec_economic_classification_guard
          ON sec_economic_classification_reviews;
        DROP TRIGGER trg_sec_economic_risk_guard
          ON sec_economic_risk_attribute_reviews;

        CREATE FUNCTION guard_ft07_method_review_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          review_count integer;
          terminal_count integer;
          terminal_id bigint;
          lock_key text;
        BEGIN
          NEW.created_at := clock_timestamp();
          NEW.known_at := NEW.created_at;
          NEW.created_txid := txid_current();
          PERFORM 1 FROM users
          WHERE id=NEW.reviewer_user_id AND role='admin' AND is_active=true
          FOR SHARE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'method applicability review requires active admin';
          END IF;

          IF TG_TABLE_NAME='sec_economic_classification_reviews' THEN
            lock_key := 'method-applicability-review' || chr(58) || NEW.stock_id ||
              chr(58) || 'classification';
            PERFORM pg_advisory_xact_lock(hashtextextended(lock_key, 0));
            SELECT count(*) INTO review_count
            FROM sec_economic_classification_reviews r
            WHERE r.stock_id=NEW.stock_id;
            SELECT count(*), min(r.id) INTO terminal_count, terminal_id
            FROM sec_economic_classification_reviews r
            WHERE r.stock_id=NEW.stock_id
              AND NOT EXISTS (
                SELECT 1 FROM sec_economic_classification_reviews later
                WHERE later.supersedes_review_id=r.id
              );
          ELSE
            lock_key := 'method-applicability-review' || chr(58) || NEW.stock_id ||
              chr(58) || 'risk' || chr(58) || NEW.risk_attribute;
            PERFORM pg_advisory_xact_lock(hashtextextended(lock_key, 0));
            SELECT count(*) INTO review_count
            FROM sec_economic_risk_attribute_reviews r
            WHERE r.stock_id=NEW.stock_id
              AND r.risk_attribute=NEW.risk_attribute;
            SELECT count(*), min(r.id) INTO terminal_count, terminal_id
            FROM sec_economic_risk_attribute_reviews r
            WHERE r.stock_id=NEW.stock_id
              AND r.risk_attribute=NEW.risk_attribute
              AND NOT EXISTS (
                SELECT 1 FROM sec_economic_risk_attribute_reviews later
                WHERE later.supersedes_review_id=r.id
              );
          END IF;

          IF review_count=0 THEN
            IF NEW.supersedes_review_id IS NOT NULL THEN
              RAISE EXCEPTION 'method review requires exact terminal supersession';
            END IF;
          ELSIF terminal_count<>1 THEN
            RAISE EXCEPTION 'method review lineage conflict';
          ELSIF NEW.supersedes_review_id IS NULL
             OR NEW.supersedes_review_id<>terminal_id THEN
            RAISE EXCEPTION 'method review requires exact terminal supersession';
          END IF;
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_sec_economic_classification_guard
          BEFORE INSERT ON sec_economic_classification_reviews
          FOR EACH ROW EXECUTE FUNCTION guard_ft07_method_review_insert();
        CREATE TRIGGER trg_sec_economic_risk_guard
          BEFORE INSERT ON sec_economic_risk_attribute_reviews
          FOR EACH ROW EXECUTE FUNCTION guard_ft07_method_review_insert();
        """
    )
    op.add_column(
        "sec_method_policy_rules",
        sa.Column("method_version_id", sa.String(80), nullable=True),
    )
    op.add_column(
        "sec_method_policy_rules",
        sa.Column(
            "required_risk_reviews_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "sec_method_policy_rules",
        sa.Column(
            "required_adjustments_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "sec_method_policy_rules",
        sa.Column("unsupported_reason_code", sa.String(120), nullable=True),
    )
    op.create_check_constraint(
        "ck_sec_method_rule_risk_reviews_array",
        "sec_method_policy_rules",
        "jsonb_typeof(required_risk_reviews_json)='array'",
    )
    op.create_check_constraint(
        "ck_sec_method_rule_adjustments_array",
        "sec_method_policy_rules",
        "jsonb_typeof(required_adjustments_json)='array'",
    )
    op.create_check_constraint(
        "ck_sec_method_rule_version_shape",
        "sec_method_policy_rules",
        "(applicability='approved' AND method_version_id IS NOT NULL "
        "AND unsupported_reason_code IS NULL) OR "
        "(applicability='unsupported' AND method_version_id IS NULL)",
    )

    # Approved policies are migration-owned. Remove only the approval guard;
    # the DB stamp trigger remains active and overwrites knowledge/creation time
    # at the real migration transaction rather than accepting a backdated value.
    op.execute("DROP TRIGGER trg_sec_method_policy_insert_guard ON sec_method_policy_versions")
    op.bulk_insert(
        _policy_table(),
        [
            {
                "id": POLICY_ID,
                "status": "approved",
                "effective_from": POLICY_EFFECTIVE_FROM,
                "policy_sha256": POLICY_SHA256,
                "review_reason": (
                    "FT-07 migration-owned ordinary-company methods and "
                    "fail-closed industry/risk applicability policy"
                ),
            }
        ],
    )
    _create_policy_insert_guard()
    op.bulk_insert(_rule_table(), POLICY_RULES)


def downgrade() -> None:
    connection = op.get_bind()
    op.execute(
        "LOCK TABLE sec_economic_classification_reviews, "
        "sec_economic_risk_attribute_reviews, metric_facts IN SHARE MODE"
    )
    retained = connection.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM sec_economic_classification_reviews) + "
            "(SELECT count(*) FROM sec_economic_risk_attribute_reviews) + "
            "(SELECT count(*) FROM metric_facts WHERE "
            " value_json->'analysis_method'->>'method_policy_version_id'=:policy)"
        ),
        {"policy": POLICY_ID},
    ).scalar_one()
    if retained:
        raise RuntimeError("cannot downgrade retained FT-07 method authority")

    # ``IF EXISTS`` also lets a developer who applied an earlier draft of this
    # unmerged revision return through the canonical migration path. Retained
    # authority was already rejected above, before any mutation.
    op.execute(
        "DROP FUNCTION IF EXISTS guard_ft07_method_review_insert() CASCADE; "
        "DROP FUNCTION IF EXISTS guard_ft07_method_reviewer_authority() CASCADE; "
        "DROP TRIGGER IF EXISTS trg_sec_economic_classification_guard "
        "ON sec_economic_classification_reviews; "
        "DROP TRIGGER IF EXISTS trg_sec_economic_risk_guard "
        "ON sec_economic_risk_attribute_reviews"
    )
    op.execute(
        "CREATE TRIGGER trg_sec_economic_classification_guard BEFORE INSERT "
        "ON sec_economic_classification_reviews FOR EACH ROW "
        "EXECUTE FUNCTION guard_sec_method_authority_insert()"
    )
    op.execute(
        "CREATE TRIGGER trg_sec_economic_risk_guard BEFORE INSERT "
        "ON sec_economic_risk_attribute_reviews FOR EACH ROW "
        "EXECUTE FUNCTION guard_sec_method_authority_insert()"
    )

    op.execute("DROP TRIGGER trg_sec_method_policy_insert_guard ON sec_method_policy_versions")
    op.execute("DROP TRIGGER trg_sec_method_policy_rule_stamp ON sec_method_policy_rules")
    op.execute("DROP TRIGGER trg_sec_method_policy_rules_immutable ON sec_method_policy_rules")
    op.execute("DELETE FROM sec_method_policy_rules WHERE method_policy_version_id='analysis-method-applicability-v2'")
    op.execute("DROP TRIGGER trg_sec_method_policy_versions_immutable ON sec_method_policy_versions")
    op.execute("DELETE FROM sec_method_policy_versions WHERE id='analysis-method-applicability-v2'")
    op.execute(
        "CREATE TRIGGER trg_sec_method_policy_versions_immutable BEFORE UPDATE OR DELETE "
        "ON sec_method_policy_versions FOR EACH ROW "
        "EXECUTE FUNCTION reject_sec_financial_lineage_mutation()"
    )
    op.execute(
        "CREATE TRIGGER trg_sec_method_policy_rules_immutable BEFORE UPDATE OR DELETE "
        "ON sec_method_policy_rules FOR EACH ROW "
        "EXECUTE FUNCTION reject_sec_financial_lineage_mutation()"
    )
    op.execute(
        "CREATE TRIGGER trg_sec_method_policy_rule_stamp BEFORE INSERT "
        "ON sec_method_policy_rules FOR EACH ROW "
        "EXECUTE FUNCTION guard_sec_method_authority_insert()"
    )
    _create_policy_insert_guard()

    op.drop_constraint(
        "ck_sec_method_rule_version_shape",
        "sec_method_policy_rules",
        type_="check",
    )
    op.drop_constraint(
        "ck_sec_method_rule_adjustments_array",
        "sec_method_policy_rules",
        type_="check",
    )
    op.drop_constraint(
        "ck_sec_method_rule_risk_reviews_array",
        "sec_method_policy_rules",
        type_="check",
    )
    op.drop_column("sec_method_policy_rules", "unsupported_reason_code")
    op.drop_column("sec_method_policy_rules", "required_adjustments_json")
    op.drop_column("sec_method_policy_rules", "required_risk_reviews_json")
    op.drop_column("sec_method_policy_rules", "method_version_id")
    op.drop_constraint(
        "ck_sec_economic_risk_review_reason",
        "sec_economic_risk_attribute_reviews",
        type_="check",
    )
    op.drop_constraint(
        "ck_sec_economic_classification_review_reason",
        "sec_economic_classification_reviews",
        type_="check",
    )
