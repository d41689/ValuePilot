from __future__ import annotations

import argparse
import json
from typing import Any

from app.core.db import SessionLocal
from app.services.document_dedupe_service import DocumentDedupeService


def dedupe_documents(
    *,
    apply: bool = False,
    user_id: int | None = None,
    stock_id: int | None = None,
) -> dict[str, Any]:
    session = SessionLocal()
    try:
        return DocumentDedupeService(session).cleanup_duplicates(
            apply=apply,
            user_id=user_id,
            stock_id=stock_id,
        )
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find and optionally delete duplicate documents for the same user, stock, and report date."
    )
    parser.add_argument("--apply", action="store_true", help="Delete duplicates and refresh calculated facts.")
    parser.add_argument("--user-id", type=int, help="Limit cleanup to one user id.")
    parser.add_argument("--stock-id", type=int, help="Limit cleanup to one stock id.")
    args = parser.parse_args()

    result = dedupe_documents(
        apply=args.apply,
        user_id=args.user_id,
        stock_id=args.stock_id,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
