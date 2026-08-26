"""User follows, logical notifications, destinations, subscriptions and outbox.

Revision ID: 20260720160000
Revises: 20260720150000
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260720160000"
down_revision = "20260720150000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manager_follows",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("manager_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["manager_id"], ["institution_managers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "manager_id", name="uq_manager_follows_user_manager"),
    )
    op.create_index("ix_manager_follows_user_created", "manager_follows", ["user_id", "created_at"])

    op.create_table(
        "notification_destinations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("channel", sa.String(length=24), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("destination_hint", sa.String(length=240), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("key_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="disabled", nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_class", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("channel IN ('slack', 'email')", name="ck_notification_destinations_channel"),
        sa.CheckConstraint(
            "status IN ('pending_verification', 'enabled', 'disabled', 'configuration_blocked', 'revoked')",
            name="ck_notification_destinations_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notification_destinations_user_status",
        "notification_destinations",
        ["user_id", "status", "channel"],
    )

    op.create_table(
        "notification_email_challenges",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("destination_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["destination_id"], ["notification_destinations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_notification_email_challenges_hash"),
    )

    op.create_table(
        "notification_subscriptions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_family", sa.String(length=64), nullable=False),
        sa.Column("destination_id", sa.BigInteger(), nullable=True),
        sa.Column("frequency", sa.String(length=24), server_default="immediate", nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("quiet_start_local", sa.String(length=5), nullable=True),
        sa.Column("quiet_end_local", sa.String(length=5), nullable=True),
        sa.Column("cooldown_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "frequency IN ('immediate', 'daily_digest', 'weekly_digest')",
            name="ck_notification_subscriptions_frequency",
        ),
        sa.CheckConstraint("cooldown_minutes BETWEEN 0 AND 43200", name="ck_notification_subscriptions_cooldown"),
        sa.ForeignKeyConstraint(["destination_id"], ["notification_destinations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_notification_subscriptions_in_app",
        "notification_subscriptions",
        ["user_id", "event_family"],
        unique=True,
        postgresql_where=sa.text("destination_id IS NULL"),
    )
    op.create_index(
        "uq_notification_subscriptions_destination",
        "notification_subscriptions",
        ["user_id", "event_family", "destination_id"],
        unique=True,
        postgresql_where=sa.text("destination_id IS NOT NULL"),
    )

    op.create_table(
        "logical_notifications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_family", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        sa.Column("subject_key", sa.String(length=240), nullable=False),
        sa.Column("logical_key", sa.String(length=360), nullable=False),
        sa.Column("source_version", sa.String(length=240), nullable=False),
        sa.Column("content_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("correction_type", sa.String(length=24), server_default="original", nullable=False),
        sa.Column("supersedes_notification_id", sa.BigInteger(), nullable=True),
        sa.Column("case_id", sa.BigInteger(), nullable=True),
        sa.Column("stock_id", sa.BigInteger(), nullable=True),
        sa.Column("manager_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("evidence_route", sa.String(length=500), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("severity", sa.String(length=16), server_default="info", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("correction_type IN ('original', 'correction')", name="ck_logical_notifications_correction_type"),
        sa.CheckConstraint("severity IN ('info', 'warning', 'error')", name="ck_logical_notifications_severity"),
        sa.ForeignKeyConstraint(["case_id"], ["research_cases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["manager_id"], ["institution_managers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supersedes_notification_id"], ["logical_notifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "logical_key", "source_version", name="uq_logical_notifications_source"),
    )
    op.create_index("ix_logical_notifications_user_created", "logical_notifications", ["user_id", "created_at"])
    op.create_index("ix_logical_notifications_subject", "logical_notifications", ["event_family", "subject_key", "created_at"])

    op.create_table(
        "notification_inbox_states",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("logical_notification_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["logical_notification_id"], ["logical_notifications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("logical_notification_id", name="uq_notification_inbox_states_notification"),
    )
    op.create_index("ix_notification_inbox_states_user_read", "notification_inbox_states", ["user_id", "read_at", "dismissed_at"])

    op.create_table(
        "notification_delivery_attempts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("logical_notification_id", sa.BigInteger(), nullable=False),
        sa.Column("destination_id", sa.BigInteger(), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_response_class", sa.String(length=100), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'leased', 'retry_scheduled', 'succeeded', 'permanent_failure', 'configuration_blocked')",
            name="ck_notification_delivery_attempts_status",
        ),
        sa.ForeignKeyConstraint(["destination_id"], ["notification_destinations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["logical_notification_id"], ["logical_notifications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "logical_notification_id", "destination_id", "content_version",
            name="uq_notification_delivery_idempotency",
        ),
    )
    op.create_index("ix_notification_delivery_due", "notification_delivery_attempts", ["status", "next_attempt_at"])

    op.create_table(
        "notification_delivery_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("attempt_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("response_class", sa.String(length=100), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["notification_delivery_attempts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_delivery_events_attempt_created", "notification_delivery_events", ["attempt_id", "created_at"])

    op.create_table(
        "notification_price_alert_states",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("stock_id", sa.BigInteger(), nullable=False),
        sa.Column("last_price_id", sa.BigInteger(), nullable=True),
        sa.Column("last_side", sa.String(length=16), nullable=True),
        sa.Column("consecutive_fresh_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("last_side IS NULL OR last_side IN ('above', 'below')", name="ck_notification_price_alert_states_side"),
        sa.ForeignKeyConstraint(["last_price_id"], ["stock_prices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stock_id"], ["stocks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "stock_id", name="uq_notification_price_alert_states_user_stock"),
    )

    # Existing settings become in-app-only digest subscriptions. Legacy email
    # intent never verifies or activates an external destination implicitly.
    op.execute(
        """
        INSERT INTO notification_subscriptions
            (user_id, event_family, destination_id, frequency, timezone,
             cooldown_minutes, is_enabled)
        SELECT user_id, 'filing_season_digest', NULL,
               CASE WHEN frequency = 'weekly' THEN 'weekly_digest' ELSE 'daily_digest' END,
               COALESCE(NULLIF(timezone, ''), 'UTC'), 1440, is_enabled
        FROM notification_settings
        ON CONFLICT DO NOTHING
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_logical_notifications_append_only
        BEFORE UPDATE OR DELETE ON logical_notifications
        FOR EACH ROW EXECUTE FUNCTION reject_research_append_only_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_notification_delivery_events_append_only
        BEFORE UPDATE OR DELETE ON notification_delivery_events
        FOR EACH ROW EXECUTE FUNCTION reject_research_append_only_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_notification_delivery_events_append_only ON notification_delivery_events")
    op.execute("DROP TRIGGER IF EXISTS trg_logical_notifications_append_only ON logical_notifications")
    op.drop_table("notification_price_alert_states")
    op.drop_index("ix_notification_delivery_events_attempt_created", table_name="notification_delivery_events")
    op.drop_table("notification_delivery_events")
    op.drop_index("ix_notification_delivery_due", table_name="notification_delivery_attempts")
    op.drop_table("notification_delivery_attempts")
    op.drop_index("ix_notification_inbox_states_user_read", table_name="notification_inbox_states")
    op.drop_table("notification_inbox_states")
    op.drop_index("ix_logical_notifications_subject", table_name="logical_notifications")
    op.drop_index("ix_logical_notifications_user_created", table_name="logical_notifications")
    op.drop_table("logical_notifications")
    op.drop_index("uq_notification_subscriptions_destination", table_name="notification_subscriptions")
    op.drop_index("uq_notification_subscriptions_in_app", table_name="notification_subscriptions")
    op.drop_table("notification_subscriptions")
    op.drop_table("notification_email_challenges")
    op.drop_index("ix_notification_destinations_user_status", table_name="notification_destinations")
    op.drop_table("notification_destinations")
    op.drop_index("ix_manager_follows_user_created", table_name="manager_follows")
    op.drop_table("manager_follows")
