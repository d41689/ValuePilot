"""Approve annual Value Line revenue aliases without rewriting prior authority.

Revision ID: 20260912110000
Revises: 20260912100000
Create Date: 2026-09-12 11:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260912110000"
down_revision = "20260912100000"
branch_labels = None
depends_on = None

PREVIOUS_POLICY_ID = (
    "value-line-resolved-v2:"
    "ad39a21849da51983b15588182cc8a66fa36999429d65fbc3a45323719452a4b"
)
POLICY_SHA256 = "bae1500f130fb367c2d98944d34a05f2ae703cb660205bafcb0c964917221264"
POLICY_ID = f"value-line-resolved-v2:{POLICY_SHA256}"


def _restore_registry_guard() -> None:
    op.execute(
        "CREATE TRIGGER trg_value_line_mapping_policy_registry "
        "BEFORE INSERT OR UPDATE OR DELETE ON value_line_mapping_policies "
        "FOR EACH ROW EXECUTE FUNCTION guard_value_line_mapping_policy_registry()"
    )


def upgrade() -> None:
    # Hold the table lock through the transaction while the insert guard is
    # removed. Prior policies remain byte-for-byte intact and readable.
    op.execute("LOCK TABLE value_line_mapping_policies IN ACCESS EXCLUSIVE MODE")
    predecessor = op.get_bind().execute(
        sa.text(
            "SELECT id FROM value_line_mapping_policies "
            "WHERE id=:id AND status='approved' AND spec_version=2 "
            "AND parser_version='value-line-v1'"
        ),
        {"id": PREVIOUS_POLICY_ID},
    ).scalar_one_or_none()
    if predecessor is None:
        raise RuntimeError(
            "Value Line revenue alias upgrade refused: expected approved predecessor missing"
        )
    op.execute(
        "DROP TRIGGER trg_value_line_mapping_policy_registry ON value_line_mapping_policies"
    )
    op.execute(
        sa.text(
            "INSERT INTO value_line_mapping_policies "
            "(id,policy_sha256,spec_version,parser_version,status,known_at,effective_from,retired_at) "
            "SELECT :id,:sha,2,'value-line-v1','approved',cutover,cutover,NULL "
            "FROM (SELECT clock_timestamp() AS cutover) timing"
        ).bindparams(id=POLICY_ID, sha=POLICY_SHA256)
    )
    _restore_registry_guard()


def downgrade() -> None:
    op.execute("LOCK TABLE value_line_mapping_policies IN ACCESS EXCLUSIVE MODE")
    referenced = op.get_bind().execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM value_line_parse_runs "
            "WHERE source_mapping_version=:id)"
        ),
        {"id": POLICY_ID},
    ).scalar_one()
    if referenced:
        raise RuntimeError(
            "Value Line revenue alias downgrade refused: immutable parse-run history uses this policy"
        )
    op.execute(
        "DROP TRIGGER trg_value_line_mapping_policy_registry ON value_line_mapping_policies"
    )
    op.execute(
        sa.text("DELETE FROM value_line_mapping_policies WHERE id=:id").bindparams(id=POLICY_ID)
    )
    _restore_registry_guard()
