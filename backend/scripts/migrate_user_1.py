#!/usr/bin/env python3
"""Promote user_id=1 to admin and set a real hashed password.

Usage:
    # Password from env var (recommended):
    INITIAL_ADMIN_PASSWORD=SomeStr0ng!Pass python -m scripts.migrate_user_1

    # Or pass explicitly:
    python -m scripts.migrate_user_1 --password 'SomeStr0ng!Pass'

Requires:
    - The Alembic migration 3c4d5e6f7a8b (add_user_auth_fields) has been applied.
    - bcrypt is installed (via passlib[bcrypt]).
"""

from __future__ import annotations

import argparse
import os
import sys

import bcrypt as _bcrypt

from app.core.db import SessionLocal
from app.models.users import User


TARGET_USER_ID = 1
ENV_VAR = "INITIAL_ADMIN_PASSWORD"
MIN_PASSWORD_LENGTH = 8


def run(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Error: password must be at least {MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == TARGET_USER_ID).first()
        if user is None:
            print(f"Error: user with id={TARGET_USER_ID} not found.", file=sys.stderr)
            sys.exit(1)

        user.hashed_password = _bcrypt.hashpw(
            password.encode("utf-8"), _bcrypt.gensalt(rounds=12)
        ).decode("utf-8")
        user.role = "admin"
        db.commit()
        db.refresh(user)

        print(f"Success: user id={user.id} email={user.email}")
        print(f"  role      = {user.role}")
        print(f"  is_active = {user.is_active}")
        print(f"  tier      = {user.tier}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote user_id=1 to admin.")
    parser.add_argument(
        "--password",
        default=None,
        help=f"Admin password. Falls back to ${ENV_VAR} env var.",
    )
    args = parser.parse_args()

    password = args.password or os.environ.get(ENV_VAR)
    if not password:
        print(
            f"Error: provide --password or set ${ENV_VAR} environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    run(password)


if __name__ == "__main__":
    main()
