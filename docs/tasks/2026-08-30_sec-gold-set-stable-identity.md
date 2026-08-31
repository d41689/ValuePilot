# SEC gold-set stable identity hardening

Status: complete

Owner: Product / Engineering

Date: 2026-08-30

## Goal

Make the FT-03 gold-case operator path resolve a locked case through its stable,
reviewed stock-to-CIK identity even when a provider-specific ticker separator
differs (for example manifest `BRK-B` versus stock `BRK/B`). Preserve a narrow,
fail-closed bootstrap path for cases whose locked CIK has not yet been
registered.

This advances “estimate normalized owner earnings” and “disconfirm before
deciding” by preventing an operator-only ticker spelling difference from
blocking primary-source lineage while keeping conflicting or ambiguous issuer
identity visible. Success is observable when the reviewed CIK selects the
intended stock, safe separator aliases can bootstrap exactly once, and every
ambiguous or conflicting case stops before acquisition.

## Acceptance criteria

- A terminal, effective `reviewed` `sec_issuer_identities` decision for the
  locked CIK is authoritative for gold-case stock resolution.
- Manifest ticker spelling is not the lookup key once that reviewed identity
  exists; `BRK-B`, `BRK/B`, and `BRK.B` are treated only as narrowly defined
  separator aliases.
- When no reviewed CIK decision exists, bootstrap considers only active stocks
  with the exact ticker or a separator-only alias and requires consistent
  listing country, listing venue when known, and normalized company name.
- A nonmatching reviewed stock, multiple reviewed candidates, or multiple
  bootstrap candidates fails closed without registering another identity or
  starting SEC acquisition.
- Operator output states whether resolution used the reviewed CIK or the locked
  manifest bootstrap path and shows both manifest and stored ticker spellings.

## Scope

### In

- Gold-case stock resolution in the FT-03 operator CLI.
- Unit/database tests for reviewed-CIK authority, `BRK-B` bootstrap aliasing,
  ambiguity, and conflicting reviewed identity.
- Operator-facing documentation and this task record.

### Out

- Filing-form-aware history selection.
- SEC artifact or parse-input manifest hashing.
- Changes to the locked gold-set manifest.
- Schema, migration, SEC publication, or product read API changes.

## PRD and architecture references

- `AGENTS.md`
- `docs/architecture/research-decision-support.md`
- `docs/architecture/coverage-source-policy.md`
- `docs/prd/value-pilot-prd-v0.1.md` §H.2 and §H.7
- `docs/acceptance/financial_truth_beta_gold_set.yml`

## Files to change

- `backend/app/cli/sec_financials.py`
- `backend/tests/unit/test_sec_financial_cli.py` (new)
- `docs/tasks/2026-08-30_sec-gold-set-stable-identity.md`

## Test plan

Test first with the focused CLI identity suite:

1. `docker compose exec -T api pytest -q tests/unit/test_sec_financial_cli.py`
2. `git diff --check`

The full canonical closing gate belongs to the completed multi-step repair; this
standalone Step 1 commit records its focused Docker verification and does not
claim the later steps or whole repair are ready.

## Decisions and gotchas

- 2026-08-30: reviewed CIK identity is the stable key. Ticker canonicalization
  is deliberately restricted to exchanging `.`, `/`, and `-` between
  alphanumeric symbol segments; it is never a fuzzy symbol search.
- 2026-08-30: the bootstrap path remains because this CLI is the approved path
  that turns a locked, reviewed FT-00 case into its first durable SEC identity.
  It cannot override any terminal reviewed decision for the locked CIK.
- 2026-08-30: no form/history or manifest-hash behavior is changed in this
  step.
- 2026-08-30: first adversarial review found that the reviewed-CIK path could
  select an inactive stock even though bootstrap rejected inactive candidates.
  The shared consistency gate now rejects inactive stocks on both paths, and a
  regression proves an active alias cannot become a fallback from an inactive
  reviewed decision.
- 2026-08-30: second adversarial review found that a matching raw/legacy venue
  could mask a contradictory canonical `listing_exchange`. A known canonical
  venue now has sole precedence. Raw/legacy venues are consulted only when the
  canonical venue is absent or generic, and all known fallback values must
  agree with the locked MIC.

## Sign-off trail

- Red tests: initial resolver import failed; inactive-reviewed and both venue
  precedence regressions then reproduced their respective review findings
  before production changes.
- Targeted Docker tests: `46 passed` across the CLI resolver, locked manifest,
  SEC source guard, and SEC financial-lineage suites.
- `git diff --check`: passed.
- Adversarial review: final Terra re-review passed with no actionable finding
  (`45` focused tests and diff check passed in the reviewer environment).
