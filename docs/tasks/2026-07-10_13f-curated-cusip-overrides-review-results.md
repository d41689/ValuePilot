# Review results — curated CUSIP overrides (PR #121)

## Verdict

**Send back — one P1 blocker.** The checked-in XOM/HON entries are correct and
the rank/temporal mechanisms are otherwise sound, but a case-variant CUSIP in a
future curated seed is accepted, reported as applied, and then cannot match the
canonical uppercase holdings. This is precisely a silent mega-cap omission,
contradicting the loader's fail-loud contract.

## Findings

### P1 — accepted lowercase CUSIP creates a mapping no holding can use

- **Location:** `backend/app/services/cusip_enrichment.py:193-205`, with the
  exact link lookup at `backend/app/services/cusip_enrichment.py:611-619`.
- **Trigger:** add a syntactically valid lowercase seed value such as
  `{"cusip":"30231g102", "ticker":"XOM", ...}`. The validator uppercases a
  local copy before testing it (`cusip_validation.py:8`), so it accepts this
  value; the loader retains the raw lowercase string when it calls
  `_active_mapping` and `upsert_cusip_mapping`.
- **Reproduced (isolated `valuepilot_test` transaction, rolled back):**

  ```bash
  docker compose exec -T -e DATABASE_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test" api python - <<'PY'
  import json
  from pathlib import Path
  from sqlalchemy import text
  from app.core.db import SessionLocal
  from app.services.cusip_enrichment import seed_curated_cusip_overrides

  session, seed = SessionLocal(), Path('/tmp/review_lowercase_override.json')
  try:
      seed.write_text(json.dumps([{
          'cusip': '30231g102', 'ticker': 'XOM',
          'issuer_name': 'Exxon Mobil Corp', 'reason': 'review',
      }]))
      report = seed_curated_cusip_overrides(session, seed_path=seed)
      stored = session.execute(text(
          "select cusip, ticker from cusip_ticker_map "
          "where cusip = '30231g102' and is_active"
      )).one()
      upper_count = session.execute(text(
          "select count(*) from cusip_ticker_map "
          "where cusip = '30231G102' and is_active"
      )).scalar()
      print({'report': report, 'stored_mapping': tuple(stored),
             'uppercase_holding_mapping_candidates': upper_count})
  finally:
      session.rollback(); session.close(); seed.unlink(missing_ok=True)
  # {'report': {'applied_cusips': ['30231g102'], ...},
  #  'stored_mapping': ('30231g102', 'XOM'),
  #  'uppercase_holding_mapping_candidates': 0}
  PY
  ```

- **Impact:** the seed reports `applied=1`, but `_apply_mappings_to_holdings`
  compares `CusipTickerMap.cusip == Holding13F.cusip` exactly. The parser stores
  uppercase CUSIPs; the real dev probe found 102 XOM holdings and 43 HON holdings
  with zero lowercase holdings. The affected mega-cap therefore remains
  unlinked/invisible while the operator is told the override was applied.
  `test_the_seed_file_is_structurally_valid` also misses this typo because it
  calls the same case-insensitive validator.
- **Suggested fix:** canonicalize before every lookup/write, e.g.
  `cusip = (entry.get("cusip") or "").strip().upper()`, then validate and use
  that canonical value in the report. Alternatively reject noncanonical input.
  Add a regression test proving a lowercase seed either fails loudly or stores
  uppercase and links an uppercase holding.

## Checks that passed

- **Current seed identity:** live OpenFIGI requests through Rate Guard returned
  `EXXON MOBIL CORP` for `30231G102` (including ticker `XOM`) and `HONEYWELL
  INTERNATIONAL INC` for `438516106`; the latter forward response contains only
  `HONEUR/HONGBP/HONGBX/HONRUB`, never `HON`. Reverse `TICKER=HON, exchCode=US`
  returned one US Common Stock record. Real dev holdings carry the corresponding
  issuer names and are already linked to manual `XOM`/`HON` mappings.
- **Precedence:** rank-4 manual mapping replaces lower-rank OpenFIGI rows and an
  attempted later `high` foreign ticker returns the existing manual row. The
  targeted regression test covers this adversarial case.
- **Conflict/idempotency:** no prior, OpenFIGI review-needed, same manual ticker,
  and different manual ticker follow the intended applied/unchanged/conflict
  paths. On the real dev DB inside a rolled-back transaction the loader returned
  `entries=2, unchanged=2, applied=0, conflicts=0`; active mapping count stayed
  two.
- **Temporal/linking:** a NULL `valid_from`/`valid_to` mapping matches every
  dated holding through the explicit interval predicate; NULL quarter-end
  holdings correctly remain pending. No change touched
  `evaluate_openfigi_matches`.
- **Flag/transaction:** the flag defaults OFF and fully gates the call. When ON,
  it seeds before the existing bootstrap/backfill path. The commit makes the
  resumable enrichment workflow non-atomic, but a later failure remains visible
  as a failed job and a retry completes the existing bootstrap/backfill; no
  additional corrupting path was found. Repository deployment templates do not
  set the flag, so production activation remains an explicit data-gate
  environment operation rather than an implicit side effect.

## Verification

| Check | Result |
|---|---|
| Targeted curated-override tests on `valuepilot_test` | 8 passed |
| Full backend suite on `valuepilot_test` | 1250 passed (3 existing SQLAlchemy legacy warnings) |
| Frontend unit tests | 185 passed |
| Frontend lint | passed |
| `git diff --check main...HEAD` | passed |
| Production frontend build | not run — `git diff --stat main...HEAD -- frontend` is empty, per review prompt |

## Resolution (2026-07-11)

**P1 confirmed and fixed.** The finding is real: `is_valid_cusip` only uppercases
a local copy, so a lowercase seed CUSIP passed validation, was stored lowercase,
reported `applied`, and could never match the uppercase holdings — a silent
mega-cap omission that contradicts the loader's fail-loud contract. (The
checked-in XOM/HON entries are uppercase, so today's data was unaffected; the
defect was latent for any future case-variant entry.)

- **Fix** (`cusip_enrichment.py`, `seed_curated_cusip_overrides`): canonicalize
  `cusip` and `ticker` to `.strip().upper()` **before** validate / `_active_mapping`
  / `upsert_cusip_mapping`, so the stored form and the report use the canonical
  uppercase that `_apply_mappings_to_holdings` matches exactly.
- **Tests:** new `test_a_lowercase_seed_cusip_is_canonicalized_and_links_an_uppercase_holding`
  proves a lowercase seed now stores uppercase, reports the canonical CUSIP, and
  actually links a real (uppercase) holding. `test_the_seed_file_is_structurally_valid`
  now also asserts the checked-in file is already canonical uppercase (CI catches
  a case typo pre-merge).
- **Reviewer's exact repro** now returns `applied_cusips=['30231G102']`, zero
  lowercase rows stored, and the uppercase holding-matchable row `('30231G102','XOM')`.
- **Gates re-run green:** override tests **9 passed**, full backend **1250
  passed**, frontend **185 passed**, lint clean; no migration; frontend identical
  to `main`.

## Re-review (2026-07-11)

**Verdict: mergeable.** The P1 is correctly fixed; this independent re-review
found no new issue.

- Re-ran the original adversarial input in a rolled-back `valuepilot_test`
  transaction: seed `30231g102` / `xom` now returns
  `applied_cusips=['30231G102']`, stores `('30231G102', 'XOM')`, and leaves zero
  lowercase rows. That is the exact canonical key used by the holdings linker.
- The real dev probe, also rolled back, remains idempotent:
  `entries=2, unchanged=2, applied=0, conflicts=0`, with two active XOM/HON
  mappings. No real data was changed.
- Verification repeated: focused override suite **9 passed**; full backend
  suite **1251 passed** (the same three SQLAlchemy legacy warnings); frontend
  unit suite **185 passed** and lint passed. Frontend has no PR diff, so the
  review prompt's conditional production build remains inapplicable.
