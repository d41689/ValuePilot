#!/usr/bin/env python3
import argparse
import json
from typing import Any


MISSING = object()


def diff_json(left: Any, right: Any, path: str, diffs: dict[str, list[Any]]) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        keys = set(left.keys()) | set(right.keys())
        for key in sorted(keys):
            left_val = left.get(key, MISSING)
            right_val = right.get(key, MISSING)
            next_path = f"{path}.{key}" if path else key
            if left_val is MISSING or right_val is MISSING:
                diffs[next_path] = [
                    None if left_val is MISSING else left_val,
                    None if right_val is MISSING else right_val,
                ]
                continue
            diff_json(left_val, right_val, next_path, diffs)
        return

    if isinstance(left, list) and isinstance(right, list):
        max_len = max(len(left), len(right))
        for idx in range(max_len):
            left_val = left[idx] if idx < len(left) else MISSING
            right_val = right[idx] if idx < len(right) else MISSING
            next_path = f"{path}[{idx}]" if path else f"[{idx}]"
            if left_val is MISSING or right_val is MISSING:
                diffs[next_path] = [
                    None if left_val is MISSING else left_val,
                    None if right_val is MISSING else right_val,
                ]
                continue
            diff_json(left_val, right_val, next_path, diffs)
        return

    if left != right:
        diffs[path or "$"] = [left, right]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diff two JSON files and output a map of mismatched keys to [left, right] values."
    )
    parser.add_argument("left", help="Path to the left JSON file")
    parser.add_argument("right", help="Path to the right JSON file")
    parser.add_argument("output", help="Path to write the diff JSON")
    args = parser.parse_args()

    with open(args.left, "r", encoding="utf-8") as left_file:
        left_data = json.load(left_file)
    with open(args.right, "r", encoding="utf-8") as right_file:
        right_data = json.load(right_file)

    diffs: dict[str, list[Any]] = {}
    diff_json(left_data, right_data, "", diffs)

    with open(args.output, "w", encoding="utf-8") as output_file:
        json.dump(diffs, output_file, indent=2, ensure_ascii=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
