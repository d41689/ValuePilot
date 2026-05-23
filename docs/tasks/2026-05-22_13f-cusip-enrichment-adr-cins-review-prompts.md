# Review prompt — bulk CUSIP enrichment for ADR/REIT/ETP + CINS routing

Paste the section below into a fresh reviewer session (human or agent). It is
self-contained. Pair it with
`docs/tasks/2026-05-22_13f-cusip-enrichment-adr-cins.md` and the diff on
branch.

---

## Reviewer brief

You are reviewing **PR (TBD)**, branch `claude/13f-cusip-enrichment-adr-cins`.
The `/admin/13f/holdings` page on the dev stack showed only **78 % linked**
common holdings for 2025-Q4 (2,927 / 3,761), with 502 rows in `needs_review`
and 328 in `unresolved`. Investigation traced the gap to two systematic bugs
in CUSIP → ticker enrichment. The diagnosis and fix are agent-authored —
scrutinise accordingly.

**This change moves what becomes auto-linked vs. routed to the admin review
queue** — i.e. the data contract the screener and Oracle's Lens read. Weight
your review on the safety of the new auto-confirm rule.

### What changed

- `backend/app/services/cusip_enrichment.py`:
  `evaluate_openfigi_matches` auto-confirm rule was previously
  ``securityType=COMMON STOCK`` AND ``exchCode=US``. Now it is
  ``exchCode=US`` AND securityType in an explicit equity-like
  allowlist (`COMMON STOCK`, `ADR`, `GDR`, `NY REG SHRS`,
  `TRACKING STK`, `MLP`, `REIT`, `ETP`, `MUTUAL FUND`,
  `OPEN-END FUND`, `CLOSED-END FUND`, `UNIT`, `PREFERRED`,
  `PREFERRED STOCK`, `RECEIPT`, `TRUST`). All listings in this filtered
  set must agree on a single ticker.
- `backend/app/openfigi/client.py`: `map_cusips` routes each identifier
  by first character — digit → `idType=ID_CUSIP`, letter → `ID_CINS`.
  Input order is preserved so the positional OpenFIGI response still
  aligns. Stub fallback unchanged.
- `backend/tests/unit/test_13f_cusip_enrichment.py`: 7 new unit tests
  (`_us_adr_auto_confirms`, `_us_etp_auto_confirms`, `_us_reit_auto_confirms`,
  `_tracking_stock_auto_confirms`, `_mlp_auto_confirms`,
  `_ny_reg_shrs_auto_confirms`, `_bond_stays_in_review`,
  `_us_ticker_conflict_still_review`); 1 existing case updated (Option-only
  match now `review_needed:medium`, formerly `review_needed:medium` — no
  net change but the assertion text is preserved).
- `backend/tests/unit/test_openfigi_client.py`: 1 new test
  (`test_map_cusips_routes_cins_via_id_cins`) — mixed-order request body
  must serialise digit → `ID_CUSIP`, letter → `ID_CINS`.

### Files in scope

- `backend/app/services/cusip_enrichment.py`
- `backend/app/openfigi/client.py`
- `backend/tests/unit/test_13f_cusip_enrichment.py`
- `backend/tests/unit/test_openfigi_client.py`
- `docs/tasks/2026-05-22_13f-cusip-enrichment-adr-cins.md`

### Baseline

`git diff main...HEAD`.

## Answer every question below with a verdict (PASS / FAIL / advisory) + evidence

### A. Auto-confirm safety — MANDATORY

1. **Cross-listing safety preserved.** When two US-exchange equity-like
   listings disagree on a ticker, the rule must still return
   `review_needed:low`. Confirm
   (`test_evaluate_openfigi_matches_us_ticker_conflict_still_review`).
2. **Derivative isolation.** A CUSIP whose only US-exchange listings are
   ``Option`` / ``Warrant`` / ``Future`` must NOT auto-link to any ticker.
   Confirm via the allowlist contents and the existing
   `test_evaluate_openfigi_matches` Option-only case.
3. **Bond isolation.** A single match on a TRACE bond exchange must stay in
   review (`test_evaluate_openfigi_matches_bond_stays_in_review`). Confirm
   the bond is never auto-linked even though `securityType='US DOMESTIC'` is
   technically a non-equity type — the rule must reject it because
   `exchCode='TRACE'` is not `US`.
4. **Allowlist composition.** Inspect `_EQUITY_LIKE_SECURITY_TYPES`. Confirm
   each entry corresponds to an instrument a 13F filer's common-holding row
   (``put_call IS NULL``) would legitimately reference. Flag anything that
   could pull in a derivative / debt / structured-product securityType.

### B. CINS routing — MANDATORY

5. **Routing by first character.** Confirm `_id_type_for` returns `ID_CINS`
   iff the first character is a letter; everything else is `ID_CUSIP`.
   Verify against
   `test_map_cusips_routes_cins_via_id_cins` — mixed-order input is preserved
   end-to-end (digit→CUSIP, letter→CINS, digit→CUSIP, letter→CINS).
6. **No idType regression for digit CUSIPs.** Confirm the existing
   `test_map_cusips_routes_through_rate_guard` still asserts
   `idType=ID_CUSIP` for digit-prefixed inputs.

### C. Auto-confirm correctness for the new cases — MANDATORY

7. For each of the following equity-instrument classes, confirm there is a
   unit test that asserts `confidence=high` and the correct ticker:
   ADR / REIT / ETP / Tracking Stk / NY Reg Shrs / MLP.

### D. Live verification trail

8. Read the "Verification (dev stack)" section of the task doc
   (`docs/tasks/2026-05-22_13f-cusip-enrichment-adr-cins.md`). Confirm the
   reported progression (78 % → 90.1 % → 95.3 % → 96.1 %) is internally
   consistent and that the remaining 141 `needs_review` are characterised
   (bonds + structured names).

## Verification

```
docker compose exec -T -e DATABASE_URL='postgresql://valuepilot:valuepilot@db:5432/valuepilot_test' \
  api pytest -q                                # 927 passed on a fresh DB
docker compose exec -T web sh -lc 'node --test lib/*.test.js'  # 159 passed
docker compose exec -T web npm run lint                        # clean
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'  # clean
```

## Pass bar

Approve only if **A** confirms the auto-confirm rule is strictly safer than
the previous "Common Stock + US" rule for the cases it adds, AND no
derivative / bond instrument can sneak into the auto-confirm set; **B**
confirms the CINS routing preserves input order; **C** confirms the new
allowlist members each have a test; and **D** confirms the live verification
trail is plausible. The bar is: "a 13F-filed common-stock row whose CUSIP /
CINS resolves to a single US-exchange ticker auto-links to that ticker, and
nothing else does."
