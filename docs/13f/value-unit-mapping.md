# 13F Value-Unit Mapping Rule

## Purpose

This document records the G2 spike decision for Form 13F information table `<value>` units. It is a rule contract for MVP 1B parser work, not a parser implementation.

PRD references:
- `docs/prd/13f_automation_and_resilience_prd.md` §7.2
- `docs/prd/13f_automation_and_resilience_prd.md` §17
- `docs/prd/13f_automation_and_resilience_prd.md` §18.2
- `docs/prd/13f_automation_and_resilience_prd.md` §20

## Fixture Evidence

Official SEC reference: SEC's [Frequently Asked Questions About Form 13F](https://www.sec.gov/divisions/investment/13ffaq.htm), Q36, states that the January 3, 2023 requirement changed Form 13F value rounding from nearest thousand dollars to nearest dollar. The same FAQ update also identifies January 3, 2023 as the start date for amended Form 13F use.

| Fixture | SEC source | Accepted at | Period | Expected rule |
| --- | --- | --- | --- | --- |
| `backend/tests/fixtures/13f/value_units/2022_sio_capital_0001214659-22-013603_infotable.xml` | `https://www.sec.gov/Archives/edgar/data/1482416/000121465922013603/infotable.xml` | `2022-11-14T12:49:28` | `2022-09-30` | `schema_thousands` |
| `backend/tests/fixtures/13f/value_units/2022_mit_0001214659-22-013108_infotable.xml` | `https://www.sec.gov/Archives/edgar/data/351051/000121465922013108/infotable.xml` | `2022-11-03T16:23:40` | `2022-09-30` | `schema_thousands` |
| `backend/tests/fixtures/13f/value_units/2023_berkshire_0000950123-23-005270_22815.xml` | `https://www.sec.gov/Archives/edgar/data/1067983/000095012323005270/22815.xml` | `2023-05-15T16:01:08` | `2023-03-31` | `schema_dollars` |
| `backend/tests/fixtures/13f/value_units/2023_toms_capital_0000902664-23-004449_infotable.xml` | `https://www.sec.gov/Archives/edgar/data/1743937/000090266423004449/infotable.xml` | `2023-08-14T16:30:16` | `2023-06-30` | `schema_dollars` |
| `backend/tests/fixtures/13f/value_units/2022q4_accepted_2023_arex_0000919574-23-001400_infotable.xml` | `https://www.sec.gov/Archives/edgar/data/1800261/000091957423001400/infotable.xml` | `2023-02-14T10:01:06` | `2022-12-31` | `schema_dollars` |

Observation: multiple 2023 accepted filings still use the namespace `http://www.sec.gov/edgar/document/thirteenf/informationtable` and may still reference `eis_13FDocument.xsd` in `xsi:schemaLocation`. Therefore, `schemaLocation` alone is not sufficient to distinguish dollars from thousands.

## Mapping Rule

The parser must assign one of these rules to every information table before normalizing holdings values:

| Rule | Meaning |
| --- | --- |
| `schema_thousands` | Raw `<value>` is in thousands of dollars. Persisted USD value is `raw_value * 1000`. |
| `schema_dollars` | Raw `<value>` is already in dollars. Persisted USD value is `raw_value`. |
| `inferred` + `VALUE_UNIT_UNCERTAIN` | Evidence is insufficient. Persist with an uncertainty warning and do not silently treat the value as authoritative. |

Rule order:

1. If a manager-level `value_unit_override` is present later in the ingestion flow, it may override automatic inference. This spike does not implement manager overrides.
2. If explicit `form_spec_version` or XML schema version evidence is available, use it first:
   - 2023-or-later specification evidence maps to `schema_dollars`.
   - 2022-or-earlier specification evidence maps to `schema_thousands`.
3. If explicit version evidence is not available, and the XML namespace is the known SEC 13F information table namespace, use `accepted_at`:
   - `accepted_at >= 2023-01-03` maps to `schema_dollars`.
   - `accepted_at < 2023-01-03` maps to `schema_thousands`.
4. Do not classify by report quarter alone. A Q4 2022 filing accepted after `2023-01-03` maps to `schema_dollars`.
5. If namespace, schema/version evidence, and `accepted_at` do not produce a clear answer, return `value_parse_rule="inferred"` with warning `VALUE_UNIT_UNCERTAIN`.

`ValueUnitDecision.evidence["decided_by"]` records the branch that selected the rule: `form_spec_version`, `xml_schema_version`, `accepted_at`, or `fallback_uncertain`.

## Implementation Boundary

The helper in `backend/app/edgar/parsers/value_units.py` only classifies value-unit rules. It intentionally does not parse holdings rows, normalize database values, enqueue jobs, or update PRD semantics.
