# Parsing — detail

Detail behind **AGENTS.md → "Parsing"**.

## Parser fixture alignment workflow (required)

When asked to align a parser to an expected fixture, use project scripts inside
Docker. Do NOT use OS-level `diff` for JSON comparisons.

- Generate `*.parser.json`: `docker compose exec api python -m scripts.value_line_dump --pdf tests/fixtures/value_line/<name>.pdf --out tests/fixtures/value_line/<name>_v1.parser.json`
- Key-by-key JSON diff: `docker compose exec api python -m scripts.json_diff tests/fixtures/value_line/<name>_v1.expected.json tests/fixtures/value_line/<name>_v1.parser.json tests/fixtures/value_line/<name>_v1.diff.json`
- Iterate: use the diff JSON as the source of truth for mismatched paths/values.
  Adjust parser code minimally (TDD), regenerate, re-run, repeat until the diff
  is `{}`.
- Verify with `docker compose exec api pytest -q` (or the targeted fixture test)
  during iteration; full suite at the closing gate per the Verification section
  of `AGENTS.md`.

## EDGAR / 13F pipeline gotchas

- `shrsOrPrnAmt` is a wrapper element in infotable XML; unwrap it to read
  `sshPrnamt` / `sshPrnamtType`.
- `xslForm13F_X02/` paths in EDGAR filing index are XSLT-rendered HTML, not
  machine-readable XML — skip them when scanning for infotable URLs.
- `cusip_ticker_map.source` is VARCHAR(50); valid source strings: `"openfigi"`,
  `"sec_co_tickers"`, `"manual"`. Dataroma is not a CUSIP or security-identity
  source.
- Kahn Brothers (`0001039565-*`) reports values in dollars, not thousands —
  reconciliation warnings for this filer are True Positives, not bugs.

## EDGAR financial-filing lineage gotchas

- Read the permission and product boundary in
  `docs/architecture/coverage-source-policy.md` and PRD §H before expanding the
  form set, coverage universe, retention policy, or consumers.
- An accession `index.json` item's `type` may describe the index icon (for
  example `text.gif`) rather than the SEC exhibit type. Retention therefore
  uses the reviewed primary-document name and approved XBRL filename suffixes;
  the complete index remains retained as evidence of the manifest.
- Retain both the submissions payload that discovered the filing and the
  accession index. A hash column alone is not a replayable raw artifact.
- A parse-run checksum is not its input lineage. Persist every retained input
  through `sec_financial_parse_run_artifacts`; raw facts must reference one of
  those exact inputs.
- Inline-XBRL concept prefixes are document-local. Preserve the resolved
  namespace URI, transformation format, language/continuation reference, and
  structured unit meaning (including divided units) before FT-04 mapping.
- Raw XBRL is never canonical financial truth. Only an approved FT-04 mapping
  may publish it into `metric_facts`; product consumers must not query the raw
  lineage tables.
