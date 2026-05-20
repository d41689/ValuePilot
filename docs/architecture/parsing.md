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
