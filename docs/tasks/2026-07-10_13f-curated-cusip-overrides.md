# 13F — curated CUSIP overrides (OpenFIGI mega-cap matcher root-cause fix)

## Goal

Give the 13F pipeline a **safe, deterministic way to resolve the CUSIPs that
OpenFIGI cannot map**, so widely-held US mega-caps stop being invisible in
Oracle's Lens. This is the root-cause fix for the backlog item
"OpenFIGI matcher silently drops mega-caps whose CUSIP has no US-composite
listing", surfaced by the `HIGH_IMPACT_CUSIP_UNRESOLVED` guardrail (PR #119).

## Why a curated override, not a smarter heuristic

The backlog sketched two options: (a) a consensus heuristic over US-venue
listings, or (b) a curated override seed. Live OpenFIGI evidence (2026-07-10,
via Rate Guard) proves **(a) is unsafe and cannot work for this class**:

| CUSIP | Issuer | Forward `mapCusips` result | Correct US ticker present? |
|---|---|---|---|
| `30231G102` | ExxonMobil | 14 listings; `XOM` is plurality (6) under venue codes `PE/CB/CX/UZ/OU/QU`, mixed with foreign `EXMOC/XOMCHF/XOM_KZ/1XOMM`. **No `US` row.** | yes, but only as a plurality among foreign variants |
| `438516106` | Honeywell | 4 listings, **all** `exchCode=X1`, tickers `HONGBP/HONEUR/HONGBX/HONRUB`. | **no** — `HON` is absent entirely |
| `143658300` | Carnival Corp | 29 listings, **all** currency-variant `CCL1EUR/CCL1USD/CCL1GBX`. | **no** — `CCL` is absent entirely |

Constraining the request with `exchCode=US` **or** `micCode=XNYS` returns **zero**
listings for XOM and HON — OpenFIGI simply has no US-composite indexed under
these CUSIPs. A consensus/plurality heuristic would (i) find nothing to confirm
for HON/Carnival, and (ii) risk auto-confirming a **wrong foreign-currency
ticker** (`HONGBP`, `CCL1USD`). A wrong link is strictly worse than a known-
unresolved CUSIP: it silently corrupts Lens with a garbage identity, violating
the project's "financial data: unknown is not zero / correctness over coverage"
invariant. So we refuse the heuristic and build the deterministic override.

The just-shipped `HIGH_IMPACT_CUSIP_UNRESOLVED` guardrail is the **detection**
half of a closed loop; this curated seed is the **safe resolution** half:
guardrail flags a widely-held unresolved CUSIP → an operator verifies the
identity → adds it to the seed → it links. Neither half can mis-link.

## How it works (leverages existing machinery — no new precedence logic)

`upsert_cusip_mapping(source="manual", confidence="manual")` is already rank 4
in `_CONFIDENCE_RANK` (`cusip_enrichment.py`). A curated row therefore:

1. **beats and deactivates** any existing OpenFIGI `review_needed:*` / `high`
   row for the same CUSIP (`(cusip, valid_from=NULL)` unique interval), and
2. **can never be downgraded** by a later OpenFIGI enrichment run
   (`new_rank <= existing_rank` returns the row unchanged → idempotent), and
3. passes the `~confidence.like("review_needed:%")` filter in **both**
   `bootstrap_stocks_from_cusip_map` and `_apply_mappings_to_holdings`, so the
   `Stock` is auto-created and holdings flip to `linked`.

We add only: the seed file, a loader that mirrors `seed_confirmed_managers`, and
one call site inside `enrich_all_unmapped_holdings` (which already runs
enrich → bootstrap → backfill). No changes to `evaluate_openfigi_matches`, the
precedence ranks, or the link path.

## Acceptance criteria

- [ ] `seed_data/curated_cusip_overrides.json` exists with **operator-verified**
  entries (XOM, HON to start), each carrying `cusip`, `ticker`, `issuer_name`,
  `reason`. A CI test asserts the file is structurally valid.
- [ ] `seed_curated_cusip_overrides(db)` upserts each entry as
  `source="manual", confidence="manual", valid_from=None`; returns a diff report;
  is idempotent (re-running is a no-op); takes an advisory lock like the manager
  seed.
- [ ] It is folded into `enrich_all_unmapped_holdings` as the first step, so a
  full enrichment pass applies overrides → bootstraps → backfills → links.
- [ ] Regression tests (test-first) prove: (1) a curated override resolves a
  CUSIP whose OpenFIGI response has **no US listing** and links its holdings;
  (2) a later OpenFIGI run with a **conflicting foreign ticker never overrides**
  the curated row; (3) idempotency; (4) the seed file is valid.
- [ ] Dev verification: running the loader on dev is a **no-op** for XOM/HON
  (already linked via the manual stopgap) — i.e. the seed re-derives exactly
  what was applied by hand, proving idempotency with zero regression.
- [ ] Every canonical CI command green in-container.
- [ ] `docs/BACKLOG.md` entry cleared in this PR.

## Scope

**In:** the seed file + loader + one call site + tests + backlog clear.
**Out:** changing `evaluate_openfigi_matches` heuristics (deliberately not
touched — the evidence shows a heuristic is unsafe here); an admin UI to edit
overrides; expanding the seed beyond operator-verified entries. Carnival Corp
(`143658300` → `CCL`, verified by reverse lookup: `TICKER=CCL exchCode=US` → a
single US common "CARNIVAL CORP LTD") is a **documented, verified-ready
candidate** for an operator to add next — not included here to keep the initial
population to the backlog-named, guardrail-flagged (≥3-manager) cases.

## Files to change

- `backend/app/services/seed_data/curated_cusip_overrides.json` (new)
- `backend/app/services/cusip_enrichment.py` — `seed_curated_cusip_overrides()`
  loader + call site in `enrich_all_unmapped_holdings`
- `backend/tests/unit/test_13f_curated_cusip_overrides.py` (new)
- `docs/BACKLOG.md` — clear the matcher entry

## Test plan (Docker)

- `docker compose exec -T -e DATABASE_URL=…valuepilot_test api pytest -q tests/unit/test_13f_curated_cusip_overrides.py`
- Full backend suite, frontend tests, lint, production build (canonical CI).
- Dev idempotency probe: run `seed_curated_cusip_overrides` on `valuepilot`,
  assert XOM/HON stay `linked`, no duplicate map rows, report before/after.

## Sign-off trail

- 2026-07-10 — OpenFIGI evidence gathered (XOM/HON/Carnival forward + filtered
  lookups); design locked on curated override; flow mapped against
  `cusip_enrichment.py`.
