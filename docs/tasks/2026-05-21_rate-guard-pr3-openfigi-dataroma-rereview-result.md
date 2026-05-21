# Rereview result — Rate Guard PR 3/4: OpenFIGI + Dataroma repoint

Branch: `claude/rate-guard-pr3-openfigi-dataroma`  
Baseline: `git diff main...HEAD`  
Rereview verdict: **PASS / approve**

The previous blocker is fixed. I found no remaining must-fix issues in the
prompt scope.

## Findings

None.

## Prior Blocker Resolution

1. **C6 lifecycle — PASS.** `enrich_unmapped_holdings` now records whether it
   owns the OpenFIGI client (`owns_client = client is None`), constructs
   `OpenFigiClient()` only for the self-owned path, and closes only that client
   in a `finally` block (`backend/app/services/cusip_enrichment.py:217-251`).
   This fixes the leaked persistent `httpx.Client` introduced by the new
   `OpenFigiClient` / `RateGuardClient` lifecycle
   (`backend/app/openfigi/client.py:24-28`,
   `backend/app/rate_guard/client.py:55-56`). Injected clients remain caller
   owned, which preserves the public dependency-injection contract.
2. **Lifecycle test coverage — PASS.** New tests cover both ownership paths:
   self-constructed clients are closed
   (`backend/tests/unit/test_13f_cusip_enrichment.py:158-172`), and injected
   clients are not closed
   (`backend/tests/unit/test_13f_cusip_enrichment.py:175-188`).

## Prompt Checklist Delta

- **A1-A2:** Still PASS. `RateGuardClient.fetch` and the thin OpenFIGI/Dataroma
  wrappers are unchanged from the first review in the relevant behavior.
- **B3-B5:** Still PASS. Exception parity and call-site construction remain
  sound; no `OpenFigiClient(api_key=...)` usage was found.
- **C6:** Now PASS, as above.
- **D7:** Still PASS. OpenFIGI `Content-Type: application/json` is present in
  both keyed and keyless Rate Guard config branches
  (`rate-guard/app/config.py:87-94`).
- **E8-F10:** Still PASS. Body passthrough, GET-without-body behavior, replay
  stub hermeticity, and explicit deferrals remain correct.
- **G11:** PASS. The original shared-client and thin-client coverage remains,
  and the previously missing lifecycle coverage is now present.

## Verification

- `docker compose run --rm --no-deps api pytest -q` — **PASS**:
  `889 passed, 3 warnings in 51.91s`.
- `docker compose run --rm --no-deps -v /Users/huawang/projects/ValuePilot/rate-guard:/rate-guard api sh -lc 'cd /rate-guard && pytest -q'` — **PASS**:
  `19 passed in 1.62s`.

I used the API container for the Rate Guard pytest run to avoid host Python
tooling while still executing the Rate Guard tests against the branch source.
