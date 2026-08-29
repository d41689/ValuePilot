"""Transaction locks shared by user-owned financial-truth writers."""

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.users import AccountErasureEvent, User


def acquire_account_mutation_lock(session: Session, *, user_id: int) -> None:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"account-erasure:{user_id}"},
    )


def acquire_active_account_mutation_lock(
    session: Session,
    *,
    user_id: int,
) -> bool:
    """Serialize with erasure, then re-prove that writes are still allowed.

    Authentication may have loaded a user before a concurrent erasure commits.
    The post-lock database read is therefore authoritative; callers must fail
    closed when this function returns ``False``.
    """
    acquire_account_mutation_lock(session, user_id=user_id)
    is_active = session.scalar(
        select(User.is_active).where(User.id == user_id)
    )
    erased = session.scalar(
        select(AccountErasureEvent.id).where(
            AccountErasureEvent.user_id == user_id
        )
    )
    return is_active is True and erased is None


def acquire_user_stock_fact_lock(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
) -> None:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"metric-facts:{user_id}:{stock_id}"},
    )
