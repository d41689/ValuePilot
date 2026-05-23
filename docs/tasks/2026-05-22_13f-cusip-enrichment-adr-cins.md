# 13F CUSIP enrichment — ADR/REIT/ETF auto-confirm + CINS routing

## Goal

`/admin/13f/holdings` shows the dev 2025-Q4 linked-common ratio stuck at 78%
(2,927 / 3,761), with 502 holding rows in `needs_review` and 328 in
`unresolved`. Two systematic bugs in
`backend/app/services/cusip_enrichment.py` and `backend/app/openfigi/client.py`
explain almost the entire gap.

## Problems

- **B1 — auto-confirm too narrow.** `evaluate_openfigi_matches` only accepts
  `securityType=COMMON STOCK` AND `exchCode=US` for auto-confirm. ADRs (TSM,
  BABA, DEO, NVS, GSK, …), REITs (AMT, BXP, …), and ETFs (SPY, GLD, EFA, …)
  have well-known single US-exchange tickers, but OpenFIGI returns them under
  `securityType` `Depositary Receipt` / `REIT` / `ETP`. They fall through to
  the catch-all `review_needed:low` with reason
  `"Multiple (N) matches, no US Common Stock listing"`. Dev data: 323 unique
  US-CUSIPs / 502 rows, all unambiguous instruments dumped to human queue.

- **B2 — CINS always queried as ID_CUSIP.** `OpenFigiClient.map_cusips` sends
  `idType=ID_CUSIP` for every identifier. OpenFIGI exposes letter-prefixed
  CINS via a separate `idType=ID_CINS`. Result: 172/172 letter-prefixed
  identifiers return "No match found in OpenFIGI" (Aon plc → AON, Accenture →
  ACN, ASML, Spotify → SPOT, Medtronic plc → MDT, etc. all unlinked).

The pattern is unambiguous in `cusip_ticker_map`:

| First char | rows | with_ticker |
|---|---:|---:|
| 0–9 (CUSIP) | 1514 | 1303 (86 %) |
| A–Z (CINS) | 172 | **0** |

## Fix

1. `evaluate_openfigi_matches` — auto-confirm rule becomes "all listings with
   `exchCode=US` agree on a single ticker". securityType no longer required to
   be `COMMON STOCK`. Safety property preserved: cross-listing ambiguity is
   only ever between US-exchange tickers, which the new rule still rejects.
   The non-US single-match fallback (`review_needed:medium`) and the no-US +
   multi-match fallback (`review_needed:low`) stay as a last resort.
2. `OpenFigiClient.map_cusips` — split the batch by first-character category:
   digit → `idType=ID_CUSIP`, letter → `idType=ID_CINS`. Preserve input order
   in the returned list. Stub fallback path unchanged.
3. After deploy, run "Enrich CUSIPs" on the dev stack to backfill historical
   `needs_review` (B1) and CINS `unresolved` (B2). No migration; no data-model
   change.

## Acceptance criteria

- Single US-exchange match with `securityType` in {ADR, REIT, ETP, …} auto-
  confirms to `confidence=high` with the US ticker.
- Multiple US-exchange listings on different tickers still return
  `review_needed:low` (regression: cross-listed conflicts must not auto-link).
- CINS lookups for letter-prefixed identifiers (G/H/L/N/Y/…) succeed when
  OpenFIGI has the listing; no change for digit-prefixed CUSIPs.
- Canonical CI green; verified live on dev stack — linked-common ratio rises
  from ~78 % toward the expected ~98+ % for 2025-Q4.

## Test plan

- `pytest -q` on a fresh DB (in-container, `valuepilot_test`).
- Unit: ADR-only / REIT-only / ETP-only single-US match auto-confirms;
  multi-US-ticker still `review_needed:low`; CINS request batches by idType
  (digits → `ID_CUSIP`, letters → `ID_CINS`, mixed-order preserved).
- Live: clear historical CINS / needs_review caches, re-run "Enrich CUSIPs"
  on `/admin/13f`, confirm sample (TSM, BABA, SPY, AON, ACN, ASML) link to
  the correct ticker; confirm the `/admin/13f/holdings` linked ratio jumps.

## Log

- 2026-05-22: branch created; root cause confirmed against dev DB
  (`cusip_ticker_map` partitioned by first character — 0 % CINS success;
  500+ ADR/REIT/ETF entries dumped to needs_review with identical
  "Multiple matches, no US Common Stock listing" reason).
- 2026-05-22: implemented and live-verified. Final allowlist of US
  equity-instrument securityType strings (verified by probing OpenFIGI):
  ``Common Stock``, ``ADR``, ``GDR``, ``NY Reg Shrs``, ``Tracking Stk``,
  ``MLP``, ``REIT``, ``ETP``, ``Mutual Fund``, ``Open-End Fund``,
  ``Closed-End Fund``, ``Unit``, ``Preferred``, ``Preferred Stock``,
  ``Receipt``, ``Trust``. CINS routing splits the batch by first
  character. 9 new unit tests covering ADR / REIT / ETP / Tracking-Stk /
  NY-Reg-Shrs / MLP auto-confirm; bond (TRACE) and US-ticker conflict
  regression; CINS request routing.

## Verification (dev stack)

Cleared stale `cusip_ticker_map` rows (B1 candidates and every CINS row)
and re-ran "Enrich CUSIPs" on `/admin/13f` three times as the allowlist
was extended. `/admin/13f/holdings` 2025-Q4 progression:

| Step | LINKED COMMON | needs_review | unresolved |
|---|---:|---:|---:|
| Baseline (pre-fix) | 78.0 % (2,927) | 502 rows | 328 rows |
| After B1 (Common-only allowlist) + B2 | 90.1 % (3,389) | 368 rows | 4 rows |
| After ADR / ETP / REIT added | 95.3 % (3,585) | 172 rows | 4 rows |
| **After Tracking-Stk / NY Reg Shrs / MLP / Receipt / Trust added** | **96.1 % (3,616)** | **141 rows** | **4 rows** |

The 141 remaining `needs_review` are genuine admin items: TRACE-listed
bonds / convertibles (`AFRM 0 11/15/26`, `ABNB 0 03/15/26`, …) which
should NOT auto-link to common-stock tickers, plus a handful of
recently-restructured names (CARNIVAL, FUBOTV, HOLOGIC, SEALED AIR).
The 4 `unresolved` / `invalid_cusip` rows are pre-existing edge cases
outside this fix's scope.

Canonical CI on a fresh DB (`valuepilot_test`):
- `docker compose exec -T api pytest -q` — **927 passed** (918 + 9
  new).
- `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` —
  159 passed.
- `docker compose exec -T web npm run lint` — clean.
- `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`
  — clean. (Dev `web` container restarted afterward per the known
  dev-build-clobbers-server caveat.)
