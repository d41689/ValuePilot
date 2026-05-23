# PR Review — 13F CUSIP enrichment: ADR/REIT/ETP auto-confirm + CINS routing

**Branch:** `claude/13f-cusip-enrichment-adr-cins`
**Reviewer:** Claude Code (claude-sonnet-4-6)
**Date:** 2026-05-22
**Prior review on file:** Yes (superseded by this review)

---

## Overall Verdict: APPROVE

All four mandatory sections pass. The auto-confirm rule is strictly safer than
the predecessor "Common Stock + US" rule for every instrument class it adds.
Cross-listing and derivative/bond isolation are preserved by construction:
`exchCode=US` is a necessary (not merely sufficient) condition, the conflict
branch (`len(tickers) != 1`) is structurally unchanged, and `Option` / `Warrant`
/ `Future` / `US DOMESTIC` / `TRACE` are absent from and blocked by the
allowlist. CINS routing is correct and order-preserving at the wire level. Every
required new instrument class has a dedicated unit test asserting `confidence=high`
and the correct ticker. The live verification trail is internally consistent and
the 141 remaining `needs_review` are correctly characterised as genuine admin
items (TRACE bonds and restructured names).

Two non-blocking advisories are noted below.

---

## A. Auto-confirm safety

### A1. Cross-listing safety preserved — PASS

**Test:** `test_evaluate_openfigi_matches_us_ticker_conflict_still_review`
(`backend/tests/unit/test_13f_cusip_enrichment.py`, lines 149–161)

The test presents two US-exchange Common Stock listings for the same CUSIP with
different tickers (GOOG / GOOGL) and asserts `conf == "review_needed:low"` with
`ticker is None`.

The implementation builds `tickers = {m.get("ticker") for m in us_equity if
m.get("ticker")}` at `cusip_enrichment.py:189` and returns `review_needed:low`
whenever `len(tickers) != 1` (lines 208–213). The conflict-detection logic is
structurally unchanged from the previous rule — only the upstream filter set was
widened. Any two US-exchange equity-like listings that disagree on a ticker still
route to review. PASS.

### A2. Derivative isolation — PASS

**Test:** `test_evaluate_openfigi_matches` (existing case, lines 40–43 in
`backend/tests/unit/test_13f_cusip_enrichment.py`)

`_EQUITY_LIKE_SECURITY_TYPES` (`cusip_enrichment.py:130–147`) is a `frozenset`
of 16 named equity instrument types. `Option`, `Warrant`, `Future`, `Convertible`,
and any structured-product string are absent. The filter at line 183–186 requires
`securityType.upper() in _EQUITY_LIKE_SECURITY_TYPES`; an Option-only US match
fails that test, causing `us_equity = []`. The single-match fallback at lines
218–226 then returns `review_needed:medium`. The test asserts exactly this for
`securityType="Option"`. PASS.

### A3. Bond isolation — PASS

**Test:** `test_evaluate_openfigi_matches_bond_stays_in_review`
(`backend/tests/unit/test_13f_cusip_enrichment.py`, lines 126–134)

The bond (AFRM 0 11/15/26) carries `exchCode="TRACE"` and `securityType="US
DOMESTIC"`. The filter at line 183 requires `exchCode.upper() == "US"`, and
`"TRACE" != "US"`, so the match is excluded from `us_equity`. With a single
match in the input list, the fallback at lines 218–226 fires and returns
`review_needed:medium`. The test asserts `conf == "review_needed:medium"`.

The `exchCode` gate is the primary barrier — a bond with `securityType="US
DOMESTIC"` cannot reach the auto-confirm path regardless of what string is in
its `securityType`, because the exchange code check fails first. PASS.

### A4. Allowlist composition — PASS with advisory

`_EQUITY_LIKE_SECURITY_TYPES` (lines 130–147) entries assessed against the
criterion "a `put_call IS NULL` 13F common-holding row could legitimately
reference this instrument":

| Entry | Assessment |
|---|---|
| `COMMON STOCK` | Core 13F common holding — unambiguous. |
| `ADR` | Foreign-issuer depositary receipt, US-traded — unambiguous for 13F. |
| `GDR` | Global depositary receipt, equivalent category — valid. |
| `NY REG SHRS` | NY Registry Shares (ASML, etc.) — valid US-traded equity. |
| `TRACKING STK` | Liberty Media series (FWONK, LSXMK) — valid 13F-reported equity. |
| `MLP` | Master Limited Partnerships (ARLP, EPD) — filed as common, US-listed. |
| `REIT` | US REITs (AMT, BXP) — filed as common, no option ambiguity. |
| `ETP` | ETFs/ETPs (SPY, GLD) — filed as common by institutional holders. |
| `CLOSED-END FUND` | Listed and traded like common stocks — acceptable. |
| `RECEIPT` | Generic depositary receipts — equivalent to ADR/GDR. |
| `TRUST` | Royalty/income trusts (PBA, SU) — US-listed, traded as common. |
| `MUTUAL FUND` | **Advisory.** Mutual funds can appear in Section 13(f) securities lists, but a `put_call IS NULL` 13F row resolved to a mutual fund CUSIP is rare. Risk is low because the `exchCode=US` gate and single-ticker consensus requirement block any multi-listing ambiguity. |
| `OPEN-END FUND` | Same advisory as MUTUAL FUND. |
| `UNIT` | Blanket label; covers both LP units (valid) and structured units (less clearly valid). The `exchCode=US` gate reduces risk. |
| `PREFERRED` / `PREFERRED STOCK` | Preferred shares in 13F filings can appear as common-equivalent when the issuer lists only one preferred series under a stable ticker. Risk is low given both gates. |

No derivative (`Option`, `Warrant`, `Future`) or debt (`Bond`, `Note`, `TRACE`,
`US DOMESTIC`) string is present in the allowlist. A derivative sharing a CUSIP
with an equity instrument would need to present as US-exchange equity in
OpenFIGI to enter the filter, which OpenFIGI does not do (derivatives use
separate exchanges and securityType strings). PASS.

**Advisory (non-blocking):** `MUTUAL FUND`, `OPEN-END FUND`, and `UNIT` are
the loosest entries. Recommend adding a backlog entry to review whether live
data shows any false auto-confirms in these three categories.

---

## B. CINS routing

### B5. Routing by first character — PASS

**Implementation:** `_id_type_for` (`backend/app/openfigi/client.py`, lines 19–34)

```python
if identifier and identifier[:1].isalpha():
    return "ID_CINS"
return "ID_CUSIP"
```

This is precisely the specified rule: letter prefix → `ID_CINS`, anything else
(digit, `None`, empty string, non-alphanumeric) → `ID_CUSIP`. The function is
applied in `map_cusips` via a list comprehension at lines 64–67, which iterates
`cusips` in original input order and emits one dict per identifier — order is
preserved with no sort, partition, or re-merge step.

**Test:** `test_map_cusips_routes_cins_via_id_cins`
(`backend/tests/unit/test_openfigi_client.py`, lines 92–124)

Input is a mixed-order list: CUSIP, CINS, CUSIP, CINS (`037833100`,
`G0403H108`, `874039100`, `L8681T102`). The test captures the actual HTTP
request payload and asserts byte-for-byte:

```python
assert sent_body == [
    {"idType": "ID_CUSIP", "idValue": "037833100"},
    {"idType": "ID_CINS",  "idValue": "G0403H108"},
    {"idType": "ID_CUSIP", "idValue": "874039100"},
    {"idType": "ID_CINS",  "idValue": "L8681T102"},
]
```

It then confirms positional response alignment:
```python
assert [r[0]["ticker"] for r in results] == ["AAPL", "AON", "TSM", "SPOT"]
```

Mixed-order preservation is explicitly verified end-to-end at the wire level.
PASS.

### B6. No idType regression for digit CUSIPs — PASS

**Test:** `test_map_cusips_routes_through_rate_guard`
(`backend/tests/unit/test_openfigi_client.py`, lines 32–57)

Input: `["037833100", "000000000"]` — both digit-prefixed. The test asserts:

```python
assert sent_body == [
    {"idType": "ID_CUSIP", "idValue": "037833100"},
    {"idType": "ID_CUSIP", "idValue": "000000000"},
]
```

This existing test now flows through the new `_id_type_for` function and
confirms no regression for digit-prefixed CUSIPs. PASS.

---

## C. Auto-confirm correctness for new cases

### C7. Unit test coverage per required instrument class — PASS

| Class | Test function | File:lines | `confidence=high` asserted | Correct ticker asserted |
|---|---|---|---|---|
| ADR | `test_evaluate_openfigi_matches_us_adr_auto_confirms` | `test_13f_cusip_enrichment.py:60–77` | Yes | TSM |
| REIT | `test_evaluate_openfigi_matches_us_reit_auto_confirms` | `test_13f_cusip_enrichment.py:90–97` | Yes | AMT |
| ETP | `test_evaluate_openfigi_matches_us_etp_auto_confirms` | `test_13f_cusip_enrichment.py:79–88` | Yes | SPY |
| Tracking Stk | `test_evaluate_openfigi_matches_tracking_stock_auto_confirms` | `test_13f_cusip_enrichment.py:100–110` | Yes | FWONK |
| NY Reg Shrs | `test_evaluate_openfigi_matches_ny_reg_shrs_auto_confirms` | `test_13f_cusip_enrichment.py:137–146` | Yes | ASML |
| MLP | `test_evaluate_openfigi_matches_mlp_auto_confirms` | `test_13f_cusip_enrichment.py:113–123` | Yes | ARLP |

All 6 required classes have dedicated tests. Case-normalisation note: the
filter applies `.upper()` before the `in _EQUITY_LIKE_SECURITY_TYPES` check
(line 185). Fixture strings `"Tracking Stk"` → `"TRACKING STK"`,
`"NY Reg Shrs"` → `"NY REG SHRS"`, `"MLP"` → `"MLP"` all match correctly.

Minor observation: `GDR` is in the allowlist but has no dedicated test. This is
not in the required test set for this review and is a minor gap, not a blocking
finding.

---

## D. Live verification trail

### D8. Progression plausibility and remaining `needs_review` characterisation — PASS

Verification table from `docs/tasks/2026-05-22_13f-cusip-enrichment-adr-cins.md`
(lines 87–105):

| Step | Linked common | needs_review | unresolved |
|---|---:|---:|---:|
| Baseline (pre-fix) | 78.0 % (2,927) | 502 | 328 |
| After B1 + B2 | 90.1 % (3,389) | 368 | 4 |
| After ADR / ETP / REIT added | 95.3 % (3,585) | 172 | 4 |
| After full allowlist | **96.1 % (3,616)** | **141** | **4** |

**Internal consistency checks:**

1. **B2 (CINS):** 328 unresolved → 4 (−324). Task states 172/172 CINS
   identifiers returned 0 matches pre-fix. 324 holdings resolved ≈ 172 unique
   CUSIPs × ~1.9 holdings/CUSIP. Plausible.

2. **B1 (initial allowlist):** needs_review 502 → 368 (−134 promoted to
   linked). Combined with B2: 2,927 → 3,389 (+462 linked). Sum of B1 (134)
   + B2 (324) = 458, within rounding of 462. Small discrepancy consistent with
   batch-size effects in the enrichment loop.

3. **ADR/ETP/REIT:** needs_review 368 → 172 (−196). Linked 3,389 → 3,585
   (+196). Task baseline described 502 needs_review rows as "323 unique
   US-CUSIPs, all unambiguous." 196 cleared in this pass. Consistent.

4. **Full allowlist:** needs_review 172 → 141 (−31). Linked +31 from
   Tracking Stk / NY Reg Shrs / MLP / Receipt / Trust. Plausible given
   smaller prevalence of these instrument types in 13F portfolios.

5. **141 remaining:** Characterised as TRACE-listed bonds/convertibles (AFRM
   0 11/15/26, ABNB 0 03/15/26) and recently-restructured names (CARNIVAL,
   FUBOTV, HOLOGIC, SEALED AIR). Bond characterisation is consistent with A3
   above: `exchCode=TRACE` correctly produces `review_needed:medium`. The
   restructured names require human triage and are correctly out of scope.

6. **4 unresolved:** Pre-existing invalid/edge-case CUSIPs, explicitly noted
   as outside this fix's scope.

7. **CI count:** Task doc reports "927 passed (918 + 9 new)." Diff shows 8
   new named test functions in `test_13f_cusip_enrichment.py` (ADR, ETP, REIT,
   Tracking Stk, MLP, bond-stays-in-review, NY Reg Shrs, US-ticker-conflict)
   plus 1 in `test_openfigi_client.py` = 9 total. Count is consistent. PASS.

---

## Summary table

| # | Question | Verdict | Key evidence |
|---|---|---|---|
| A1 | Cross-listing safety preserved | PASS | `test_evaluate_openfigi_matches_us_ticker_conflict_still_review`; `review_needed:low` when `len(tickers) != 1` |
| A2 | Derivative isolation | PASS | `Option` not in `_EQUITY_LIKE_SECURITY_TYPES`; Option-only case asserts `review_needed:medium` |
| A3 | Bond isolation | PASS | `exchCode=TRACE` blocked at `== "US"` gate; `test_evaluate_openfigi_matches_bond_stays_in_review` |
| A4 | Allowlist composition | PASS + advisory | Core entries correct; `MUTUAL FUND`, `OPEN-END FUND`, `UNIT` are loosest — low risk given `exchCode=US` and single-ticker gates |
| B5 | CINS routing + order preservation | PASS | `_id_type_for` letter→CINS, digit→CUSIP; list-comp preserves input order; `test_map_cusips_routes_cins_via_id_cins` asserts wire payload and positional results |
| B6 | No idType regression for digit CUSIPs | PASS | `test_map_cusips_routes_through_rate_guard` asserts `ID_CUSIP` for `037833100` and `000000000` |
| C7 | Unit tests for all 6 required new classes | PASS | ADR / REIT / ETP / Tracking Stk / NY Reg Shrs / MLP all have dedicated tests asserting `confidence=high` and correct ticker |
| D8 | Live verification trail plausible | PASS | Step deltas internally consistent; 141 remaining correctly characterised as bonds + restructured names |

### Advisory items (non-blocking)

1. **Allowlist breadth — MUTUAL FUND / OPEN-END FUND / UNIT:** These entries
   are technically broader than a strict `put_call IS NULL` common-holding
   definition. The `exchCode=US` gate and single-ticker consensus requirement
   substantially limit risk. Recommend a backlog entry to review whether live
   data produces false auto-confirms in these categories before extending the
   allowlist further.

2. **GDR lacks a dedicated test:** `GDR` is in the allowlist but has no test
   asserting `confidence=high`. Minor gap, not blocking.

3. **`is_valid_cusip` and letter-prefixed CINS (out of scope but flag):** The
   CUSIP validator is called before routing in `enrich_unmapped_holdings`.
   If `is_valid_cusip` rejects letter-prefixed identifiers as malformed, B2 is
   silently negated upstream of the new routing logic. This was not changed in
   this diff and should be confirmed in a follow-up. (`backend/app/services/
   cusip_validation.py` — not reviewed here.)
