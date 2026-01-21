#!/usr/bin/env python3
"""Run open-world discovery on a Value Line PDF and write discovery JSON."""

from __future__ import annotations

import argparse
import json
import os

from scripts import fields_extracting


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run discovery for a Value Line PDF.")
    parser.add_argument("--pdf", required=True, help="Path to PDF")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    data = fields_extracting.discover_pdf_structure(args.pdf)
    indent = 2 if args.pretty else None
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, indent=indent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
