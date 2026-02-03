# PRD Directory Governance

## Single Entry Point

For ValuePilot v0.1, the single authoritative PRD entry point is:

- `docs/prd/value-pilot-prd-v0.1.md`

Any addendum documents in this directory are either:
- merged into the entry point, or
- explicitly labeled as historical/read-only.

## Contract Sources & Precedence

This repository intentionally separates “system behavior + storage contracts” from “metric semantics”.

If any inconsistencies exist, the following precedence order MUST be applied:
1) `docs/metric_facts_mapping_spec.yml` (metric semantics: `metric_key`, units, `period_type`, `period_end_date` derivations)
2) `docs/prd/value-pilot-prd-v0.1.md` (system behavior, schema, ingestion/API contracts)
3) Historical addendums / decision records (read-only reference; not normative)

## Metric Semantics Rule (Hard Constraint)

No new PRD or addendum may redefine metric semantics outside `docs/metric_facts_mapping_spec.yml`.

Metric semantics includes (non-exhaustive):
- `metric_key` naming
- unit choices and normalization expectations
- period semantics (`period_type`, `period_end_date` rules/derivations)

