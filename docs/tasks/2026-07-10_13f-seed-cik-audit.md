# 13F — 11 curated managers have a CIK that never files a 13F

Date opened: 2026-07-10
Status: **open, not started**
Severity: **high** — silent, product-visible, affects Oracle's Lens consensus
Found: while answering "can we confirm the pipeline parses 13F data correctly?"
after PR #115 merged. The pipeline is correct; the universe it is fed is not.

## The problem

`institution_managers` holds 82 confirmed managers. **Only 71 have ever produced a
filing.** The other 11 are absent from every quarter, because the CIK in
`backend/app/services/seed_data/confirmed_managers.json` is not the CIK that files
the 13F.

`ingest_quarter_index()` builds a whitelist from confirmed managers' CIKs and
matches `form.idx` records on it. A wrong CIK matches nothing, forever, silently.

### Evidence

Parsed **every stored `form.idx`** (2025-Q2 … 2026-Q2, 5 quarters, **45 319 13F
records**) with the project's own `parse_form_idx`, and looked up each seeded CIK:

> **None of the 11 seeded CIKs appears as a 13F filer in any of the 5 quarters.**

For 10 of them the real filer *is* in the index, under a different CIK:

| manager | seeded CIK | EDGAR 13F filer (candidate) |
|---|---|---|
| Francis Chou — Chou Associates | `0001389402` | Chou Associates Management Inc. — `0001389403` |
| Nelson Peltz — Trian | `0001345472` | TRIAN FUND MANAGEMENT, L.P. — `0001345471` |
| Ray Dalio — Bridgewater | `0001350685` | Bridgewater Associates, LP — `0001350694` |
| Third Avenue Management | `0001002858` | THIRD AVENUE MANAGEMENT LLC — `0001099281` |
| Steven Romick — FPA | `0000109501` | First Pacific Advisors, LP — `0001377581` |
| Mason Morfit — ValueAct | `0001351069` | ValueAct Holdings, L.P. — `0001418814` |
| David Tepper — Appaloosa | `0001006438` | Appaloosa LP — `0001656456` |
| Carl Icahn — Icahn Capital | `0001413902` | ICAHN CARL C — `0000921669` |
| Guy Spier — Aquamarine | `0001404599` | Aquamarine Zurich AG — `0001953324` **(ambiguous)** |
| Terry Smith — Fundsmith | `0001520023` | Fundsmith LLP — `0001569205` **(ambiguous)** |
| David Einhorn — Greenlight | `0001079114` | **no candidate found in 5 quarters** |

Chou and Trian are **off by a single digit**. That is what a hand-curated file
looks like when nothing checks it.

Two are ambiguous and need a human to pick:

- **Aquamarine** — `Aquamarine Zurich AG` (`0001953324`) vs
  `Aquamarine Financial (Cayman) Ltd` (`0002104187`).
- **Fundsmith** — `Fundsmith LLP` (`0001569205`) vs
  `FUNDSMITH INVESTMENT SERVICES LTD.` (`0001868537`).
- **Bridgewater** — `Bridgewater Associates, LP` (`0001350694`) is almost certainly
  right; `Bridgewater Advisors Inc.` (`0001600319`) is an unrelated firm. Confirm.

**Greenlight** has no name match at all across 45 319 records. Einhorn's 13F may be
filed under a different entity name entirely (e.g. an advisory affiliate). It needs
a direct EDGAR lookup, not a name grep.

### What is NOT wrong

Checked the other 71: for every one of them, our `legal_name` and the EDGAR filer
name for that CIK agree (`difflib` ratio ≥ 0.55 for all; **zero** divergences). So
**no manager is ingesting another filer's holdings.** The defect is 11 absences,
not any mis-attribution.

All 10 candidate CIKs are **free** (no `institution_managers` row holds them) and
none carries a `revoke_confirmed_cik` audit event, so re-pointing is unobstructed
by the unique index and does not overturn a human decision.

## Why it matters

`stock_id`-linked holdings from these 11 never exist, so:

- **Oracle's Lens consensus is computed over 71 managers, not 82.**
  `min_holders = 3` — losing 11 of the largest, most-followed filers changes which
  stocks clear the bar and changes every conviction percentile.
- Watchlist × 13F: Δ Holders, distinctiveness tier and the MOS cross-signal are all
  derived from that same holder set.
- The absence is **silent**. `match_cik_candidates()` only scans
  `cik IS NULL AND match_status IN ('seeded','candidate')`, so a *confirmed* row
  with a wrong CIK is never re-examined. Nothing alerts. Nothing degrades. The
  manager simply is not there.

This is the same family as [[financial-data-unknown-vs-zero]]: an unavailable
manager rendered as an absent one.

## Goal

1. Every one of the 82 curated CIKs is verified against EDGAR as an entity that
   actually files 13F-HR.
2. A check exists that makes this class of error loud, so the next bad CIK is
   caught by CI or by the admin dashboard rather than by a person asking the right
   question two months later.

## Acceptance criteria

- [ ] Each of the 11 CIKs is corrected in `confirmed_managers.json`, or the manager
      is explicitly marked as not-a-13F-filer with a recorded reason. **A human
      confirms each CIK against EDGAR** — a name grep over `form.idx` is evidence,
      not proof.
- [ ] `dev`: after re-seeding, `confirmed managers with zero filings` drops to 0
      (or to the count of managers explicitly ruled not-13F-filers).
- [ ] A new offline test asserts every seeded CIK is a distinct, 10-digit,
      zero-padded string (partially covered today by
      `test_the_curated_seed_file_is_valid`).
- [ ] A new **`audit_seed_ciks`** admin job / CLI command checks every confirmed
      manager's CIK against EDGAR (through Rate Guard) and reports any that has
      never filed a 13F-HR. It is read-only and proposes; it never rewrites a CIK.
- [ ] A readiness / quality check surfaces **"confirmed manager with zero filings
      across the last N indexed quarters"** as an admin task, so the condition is
      visible without anyone running a script.
- [ ] The downstream recompute (below) is executed and its result recorded.

## Scope

**In:** the 11 CIKs; the offline seed-file test; the `audit_seed_ciks` read-only
job; the readiness check; the recompute after the universe changes.

**Out:** adding or removing managers from the curated universe (that is M3's
`dataroma_sync`, propose-only); any change to `seed_confirmed_managers`'s lifecycle
rules (M1 locked those: the human wins, nothing is auto-deactivated).

## The universe change this creates — do not skip it

Fixing 11 CIKs means 11 managers start ingesting. **That is a universe change**, and
`min_holders = 3` makes the universe a scoring input. Every existing
`ownership_changes` row, Oracle's Lens signal and readiness metric was computed over
71 managers.

M2's startup seed already warns about exactly this
(`app/services/manager_seed_startup.py`, `MANAGER UNIVERSE CHANGED`), but it
deliberately does **not** recompute. After the re-seed, this ticket must:

1. backfill the 11 managers' filings for every indexed quarter,
2. re-run `compute_ownership_changes` and `oracles_lens_score_backfill` for each,
3. diff the Lens top-N before/after and record it — the same discipline
   MVP8-01 applied to the persisted-score flip. See
   [[tool-validation-vs-product-signoff]].

## Files to change

| file | change |
|---|---|
| `backend/app/services/seed_data/confirmed_managers.json` | the 11 CIKs |
| `backend/app/services/edgar_ingestion.py` | new `audit_confirmed_manager_ciks()` (read-only) |
| `backend/app/services/thirteenf_admin_dashboard.py` | `audit_seed_ciks` job branch + lock key |
| `backend/app/services/thirteenf_readiness.py` | "confirmed manager, zero filings" check |
| `backend/app/cli/edgar.py` | `audit-seed-ciks` command |
| `frontend/lib/admin13f/lockKey.ts` | the new job type (single-source, per MVP6-08) |
| `backend/tests/unit/test_13f_manager_seed_startup.py` | CIK shape assertions |
| `backend/tests/unit/test_13f_seed_cik_audit.py` [NEW] | the audit + the readiness check |

## Test plan

    docker compose up -d --build
    docker compose exec -T api alembic upgrade head
    TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
    docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q
    docker compose exec -T web sh -lc 'node --test lib/*.test.js'
    docker compose exec -T web npm run lint
    docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'

Plus, against the real dev data (read-only first):

    docker compose exec -T api python -m app.cli.edgar audit-seed-ciks
    # then, after the JSON is corrected:
    docker compose exec -T api python -m app.cli.edgar seed-confirmed-managers   # expect: updated 82, created 0
    # confirm zero-filing managers went to 0, then run the recompute above.

## Reproduction (read-only, no network)

    docker compose exec -T api python - <<'PY'
    from app.core.db import SessionLocal
    from app.models.institutions import RawSourceDocument, InstitutionManager, Filing13F
    from app.edgar.fetcher import load_body
    from app.edgar.parsers.form_idx import parse_form_idx
    db = SessionLocal()
    recs = []
    for d in db.query(RawSourceDocument).filter(RawSourceDocument.document_type=="form_idx"):
        recs.extend(parse_form_idx(load_body(d)))
    filer_ciks = {r.cik for r in recs}
    missing = (db.query(InstitutionManager)
                 .filter(InstitutionManager.match_status=="confirmed")
                 .filter(~InstitutionManager.id.in_(db.query(Filing13F.manager_id))).all())
    for m in missing:
        print(m.cik, m.cik in filer_ciks, m.display_name)
    PY

## Decisions needed before implementation

1. **Aquamarine, Fundsmith, Bridgewater** — pick the filing entity (candidates above).
2. **Greenlight** — find the real 13F filer, or rule that Einhorn is out of the
   universe. He is a headline value manager; removing him is a product decision.
3. **Should the seed rewrite a `cik` on a confirmed row without an audit event?**
   It does today: `seed_confirmed_managers` writes `existing.cik = cik` for any row
   whose lifecycle a human does not own. That is how this fix lands with no
   migration — but a CIK change is the same identity edit `revoke_confirmed_cik`
   demands a note for. Consider emitting an `InstitutionManagerCikReviewEvent` when
   the seed changes a non-NULL CIK.
