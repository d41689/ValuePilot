"""Pre-MVP8-01 widen cusip_ticker_map.ticker

OpenFIGI's mapCusips response can return non-equity identifiers for
some CUSIPs (e.g. bond CUSIPs match to instruments like
``"BRKR 6.375 09/01/28"`` — 19 chars). The original column was
sized at VARCHAR(10) which only fits typical equity tickers; bond /
preferred / warrant identifiers overflow. Per CLAUDE.md schema
band-aid rule, the fix is an Alembic migration, not truncation.

Discovered during Pre-MVP8-01 data-env readiness execution
2026-05-13 — see
``docs/tasks/2026-05-13_pre-mvp8-01-data-env-readiness.md``.

Revision ID: 20260513140000
Revises: 20260512130000
Create Date: 2026-05-13 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260513140000"
down_revision = "20260512130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "cusip_ticker_map",
        "ticker",
        existing_type=sa.String(10),
        type_=sa.String(50),
        existing_nullable=True,
    )


def downgrade() -> None:
    # N4 D1 finding (2026-05-18): the upgrade is driven by REAL data
    # exceeding VARCHAR(10) — OpenFIGI legitimately returns bond /
    # preferred / warrant identifiers > 10 chars for some CUSIPs
    # (e.g. ``"UBER 0.875 12/01/28 2028"`` = 24 chars). A naive
    # narrow-back would silently truncate those values and corrupt the
    # CUSIP → ticker mapping. Pre-check for offending rows and refuse
    # the downgrade with an actionable error rather than letting the
    # SQL ``StringDataRightTruncation`` surface unexplained.
    #
    # Rollback path if this downgrade is ever needed in production:
    # the operator must FIRST resolve the offending rows (delete them,
    # archive to a separate table, or coerce to a placeholder identifier)
    # and only then re-run ``alembic downgrade -1``.
    bind = op.get_bind()
    offending = (
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM cusip_ticker_map "
                "WHERE length(ticker) > 10"
            )
        ).scalar()
        or 0
    )
    if offending > 0:
        raise RuntimeError(
            f"cusip_ticker_map has {offending} rows with ticker length > 10 "
            "(OpenFIGI bond / preferred / warrant identifiers). Narrowing "
            "to VARCHAR(10) would truncate them and corrupt the mapping. "
            "Resolve the offending rows BEFORE downgrading — delete them "
            "or archive to a separate table — then re-run "
            "`alembic downgrade -1`."
        )
    op.alter_column(
        "cusip_ticker_map",
        "ticker",
        existing_type=sa.String(50),
        type_=sa.String(10),
        existing_nullable=True,
    )
