import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa
import yaml

from app.core.db import SessionLocal
from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "docs" / "metric_facts_mapping_spec.yml"
TAXONOMY_PATH = REPO_ROOT / "docs" / "value_line_field_taxonomy.yml"


@dataclass(frozen=True)
class MetricKeyClassification:
    metric_key: str
    covered: bool
    reason: str


@dataclass(frozen=True)
class TaxonomyMatcher:
    exact_keys: frozenset[str]
    dynamic_patterns: tuple[re.Pattern[str], ...]


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def build_taxonomy_matcher(
    spec_path: Path = SPEC_PATH,
    taxonomy_path: Path = TAXONOMY_PATH,
) -> TaxonomyMatcher:
    spec = _load_yaml(spec_path)
    taxonomy = _load_yaml(taxonomy_path)
    mapping_semantics = taxonomy.get("mapping_semantics", {})

    exact_keys: set[str] = set()
    dynamic_patterns: list[re.Pattern[str]] = []

    for mapping in spec.get("mappings", []):
        mapping_id = mapping.get("id")
        semantics = mapping_semantics.get(mapping_id, {})
        if semantics.get("storage_role") == "evidence_only":
            continue

        metric_key = mapping.get("metric_key")
        if isinstance(metric_key, str):
            exact_keys.add(metric_key)
            continue

        template = mapping.get("metric_key_template")
        if isinstance(template, str):
            pattern_text = "^" + re.escape(template).replace(r"\{metric_key\}", r"[a-z0-9_]+") + "$"
            dynamic_patterns.append(re.compile(pattern_text))

    return TaxonomyMatcher(
        exact_keys=frozenset(exact_keys),
        dynamic_patterns=tuple(dynamic_patterns),
    )


def classify_metric_key(metric_key: str, matcher: TaxonomyMatcher) -> MetricKeyClassification:
    if metric_key in matcher.exact_keys:
        return MetricKeyClassification(metric_key=metric_key, covered=True, reason="exact_match")
    if any(pattern.fullmatch(metric_key) for pattern in matcher.dynamic_patterns):
        return MetricKeyClassification(metric_key=metric_key, covered=True, reason="dynamic_match")
    return MetricKeyClassification(metric_key=metric_key, covered=False, reason="not_in_taxonomy_v1")


def run_audit(*, parsed_only: bool = True) -> dict[str, Any]:
    matcher = build_taxonomy_matcher()
    session = SessionLocal()
    try:
        filters = []
        if parsed_only:
            filters.append(MetricFact.source_type == "parsed")

        metric_rows = (
            session.execute(
                sa.select(
                    MetricFact.metric_key.label("metric_key"),
                    sa.func.count(MetricFact.id).label("row_count"),
                    sa.func.count(sa.distinct(MetricFact.source_document_id)).label("document_count"),
                    sa.func.sum(sa.case((MetricFact.is_current.is_(True), 1), else_=0)).label(
                        "current_count"
                    ),
                    sa.func.max(PdfDocument.report_date).label("latest_report_date"),
                )
                .select_from(MetricFact)
                .outerjoin(PdfDocument, PdfDocument.id == MetricFact.source_document_id)
                .where(*filters)
                .group_by(MetricFact.metric_key)
                .order_by(sa.func.count(MetricFact.id).desc(), MetricFact.metric_key.asc())
            )
            .mappings()
            .all()
        )

        classified_rows: list[dict[str, Any]] = []
        for row in metric_rows:
            classification = classify_metric_key(row["metric_key"], matcher)
            classified_rows.append(
                {
                    "metric_key": row["metric_key"],
                    "row_count": int(row["row_count"] or 0),
                    "document_count": int(row["document_count"] or 0),
                    "current_count": int(row["current_count"] or 0),
                    "latest_report_date": (
                        row["latest_report_date"].isoformat() if row["latest_report_date"] else None
                    ),
                    "covered": classification.covered,
                    "coverage_reason": classification.reason,
                }
            )

        fact_nature_expr = sa.func.coalesce(
            MetricFact.value_json["fact_nature"].astext,
            sa.literal("null"),
        )
        fact_nature_rows = (
            session.execute(
                sa.select(
                    fact_nature_expr.label("fact_nature"),
                    sa.func.count(MetricFact.id).label("row_count"),
                )
                .select_from(MetricFact)
                .where(*filters)
                .group_by(fact_nature_expr)
                .order_by(sa.func.count(MetricFact.id).desc(), fact_nature_expr.asc())
            )
            .mappings()
            .all()
        )

        missing_fact_nature_rows = (
            session.execute(
                sa.select(
                    MetricFact.metric_key.label("metric_key"),
                    sa.func.count(MetricFact.id).label("row_count"),
                )
                .select_from(MetricFact)
                .where(
                    *filters,
                    sa.or_(
                        MetricFact.value_json.is_(None),
                        MetricFact.value_json["fact_nature"].astext.is_(None),
                    ),
                )
                .group_by(MetricFact.metric_key)
                .order_by(sa.func.count(MetricFact.id).desc(), MetricFact.metric_key.asc())
            )
            .mappings()
            .all()
        )

        covered_rows = [row for row in classified_rows if row["covered"]]
        uncovered_rows = [row for row in classified_rows if not row["covered"]]

        return {
            "scope": "parsed_only" if parsed_only else "all_source_types",
            "summary": {
                "fact_rows": sum(row["row_count"] for row in classified_rows),
                "distinct_metric_keys": len(classified_rows),
                "taxonomy_exact_keys": len(matcher.exact_keys),
                "taxonomy_dynamic_patterns": len(matcher.dynamic_patterns),
                "covered_metric_keys": len(covered_rows),
                "uncovered_metric_keys": len(uncovered_rows),
                "covered_row_count": sum(row["row_count"] for row in covered_rows),
                "uncovered_row_count": sum(row["row_count"] for row in uncovered_rows),
            },
            "covered_metric_keys": covered_rows,
            "uncovered_metric_keys": uncovered_rows,
            "fact_nature_distribution": [
                {
                    "fact_nature": row["fact_nature"],
                    "row_count": int(row["row_count"] or 0),
                }
                for row in fact_nature_rows
            ],
            "missing_fact_nature_metric_keys": [
                {
                    "metric_key": row["metric_key"],
                    "row_count": int(row["row_count"] or 0),
                }
                for row in missing_fact_nature_rows
            ],
            "matcher": {
                "exact_keys": sorted(matcher.exact_keys),
                "dynamic_patterns": [pattern.pattern for pattern in matcher.dynamic_patterns],
            },
        }
    finally:
        session.close()


def _print_text_report(payload: dict[str, Any], limit: int) -> None:
    summary = payload["summary"]
    print("Summary")
    print(f"  Scope: {payload['scope']}")
    print(f"  Fact rows: {summary['fact_rows']}")
    print(f"  Distinct metric keys: {summary['distinct_metric_keys']}")
    print(f"  Covered metric keys: {summary['covered_metric_keys']}")
    print(f"  Uncovered metric keys: {summary['uncovered_metric_keys']}")
    print(f"  Covered row count: {summary['covered_row_count']}")
    print(f"  Uncovered row count: {summary['uncovered_row_count']}")

    print("\nUncovered / Legacy Keys")
    for row in payload["uncovered_metric_keys"][:limit]:
        print(
            "  - "
            f"{row['metric_key']} | rows={row['row_count']} docs={row['document_count']} "
            f"current={row['current_count']} latest_report_date={row['latest_report_date']}"
        )

    print("\nFact Nature Distribution")
    for row in payload["fact_nature_distribution"]:
        print(f"  - {row['fact_nature']}: {row['row_count']}")

    print("\nMissing fact_nature metric keys")
    for row in payload["missing_fact_nature_metric_keys"][:limit]:
        print(f"  - {row['metric_key']}: {row['row_count']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit metric_facts coverage against taxonomy v1.")
    parser.add_argument("--all-source-types", action="store_true", help="Include non-parsed facts.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    parser.add_argument("--limit", type=int, default=25, help="Max rows per section in text mode.")
    args = parser.parse_args()

    payload = run_audit(parsed_only=not args.all_source_types)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    _print_text_report(payload, limit=args.limit)


if __name__ == "__main__":
    main()
