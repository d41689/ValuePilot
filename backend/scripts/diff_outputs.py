#!/usr/bin/env python3
"""Diff two JSON outputs and emit a readable summary."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List

from scripts.json_diff import diff_json


def summarize_diffs(diffs: Dict[str, List[Any]], max_items: int = 20) -> Dict[str, Any]:
    items = list(diffs.items())
    items.sort(key=lambda x: x[0])
    sample = items[:max_items]
    return {
        "diff_count": len(diffs),
        "sample": [
            {"path": path, "left": left, "right": right}
            for path, (left, right) in sample
        ],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diff two JSON files and summarize changes.")
    parser.add_argument("--left", required=True, help="Left JSON path")
    parser.add_argument("--right", required=True, help="Right JSON path")
    parser.add_argument("--out", required=True, help="Output diff JSON path")
    parser.add_argument("--summary", required=False, help="Optional summary JSON path")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    with open(args.left, "r", encoding="utf-8") as f:
        left_data = json.load(f)
    with open(args.right, "r", encoding="utf-8") as f:
        right_data = json.load(f)

    diffs: Dict[str, List[Any]] = {}
    diff_json(left_data, right_data, "", diffs)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(diffs, f, indent=2, ensure_ascii=True)

    summary = summarize_diffs(diffs)
    if args.summary:
        os.makedirs(os.path.dirname(args.summary) or ".", exist_ok=True)
        with open(args.summary, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=True)

    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
