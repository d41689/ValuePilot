# Third-party review prompt — curated CUSIP overrides (PR #121)

You are an independent senior reviewer. A previous agent fixed a **high-severity**
13F bug: some US mega-caps have **no US-composite listing** in OpenFIGI, so their
CUSIPs never link to a stock and the names are invisible in Oracle's Lens. The
fix is a **curated, human-verified CUSIP→ticker override seed** (not a heuristic
change). Your job is to independently confirm the fix is correct, safe, and
cannot mis-link — and to find any real defect. Do **not** rubber-stamp.

## Ground rules

- Work in the repo at PR #121 branch `claude/13f-curated-cusip-overrides`.
- **Never run `pytest` against the dev DB.** Use the isolated test DB:
  `docker compose exec -T -e DATABASE_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test" api pytest -q …`
- The dev DB (`valuepilot`) holds real 13F data — read-only probes only, always
  `rollback()`. Do not re-seed or mutate it.
- All OpenFIGI calls route through Rate Guard (no IP-ban risk) — you may re-pull
  live responses to check the evidence.
- Report every finding with file:line, a concrete failure scenario, and a
  severity. Verdict: **mergeable** or **send back** with the specific blocker.

## What to verify (be adversarial)

1. **The precedence claim is the whole safety argument — verify it against the
   code, not the PR text.** Read `upsert_cusip_mapping` in
   `backend/app/services/cusip_enrichment.py`. Confirm that `source="manual",
   confidence="manual"` (rank 4 in `_CONFIDENCE_RANK`):
   - deactivates and replaces an existing lower-rank OpenFIGI row for the same
     `(cusip, valid_from=NULL)`, and
   - is itself **never** overwritten/downgraded by a later OpenFIGI run
     (`new_rank <= existing_rank` returns the existing row unchanged).
   Construct the adversarial case: curated override applied, then a later
   enrichment writes a `high`-confidence **wrong foreign ticker** for the same
   CUSIP. Does the curated identity survive? (`test_a_later_openfigi_run_never_
   overrides_a_curated_ticker` claims yes — prove or break it.)

2. **Can the override ever mis-link?** The entire justification is that a curated
   entry is deterministic and human-verified. Check `seed_data/curated_cusip_
   overrides.json`: is `30231G102 → XOM` and `438516106 → HON` correct? Are these
   the canonical US common-stock CUSIPs for ExxonMobil / Honeywell (not a bond,
   not an ADR, not the wrong dual-listing)? Independently confirm (e.g. OpenFIGI
   `TICKER=XOM exchCode=US`, issuer name on the real holdings). A wrong seed entry
   is a **blocker** — it would silently corrupt Lens with high confidence.

3. **Does the fix actually reach production, and stay inert until intended?**
   Trace `CUSIP_OVERRIDE_SEED_ENABLED`: it gates the seed call inside
   `enrich_all_unmapped_holdings`. Confirm (a) with the flag OFF the seed never
   runs (dev/test stay clean), (b) with it ON the seed runs first, then
   bootstrap + backfill link the holdings in the same pass. Is folding the call
   in there — with a mid-function `db.commit()` — safe w.r.t. the enrichment
   loop, the advisory locks, and the `owns_client` lifecycle? Any transaction or
   partial-commit hazard?

4. **Fail-loud vs silent-skip.** A malformed seed entry (missing field / invalid
   CUSIP) must raise, not silently drop a mega-cap the operator believes is
   covered. Confirm `test_a_malformed_seed_entry_fails_loud` really exercises the
   `raise`, and that the CI seed-validity test (`test_the_seed_file_is_
   structurally_valid`) would fail on a bad file. Is a missing file correctly a
   no-op (not a crash)?

5. **Conflict handling.** If an operator already manual-mapped a CUSIP to a
   **different** ticker, the seed must neither clobber it nor silently ignore it
   — it reports a `conflict`. Verify the classification logic (`prior_is_same_
   curated`, `mapping.ticker != ticker`) is correct for all four cases: no prior
   mapping, prior OpenFIGI review_needed, prior manual same-ticker, prior manual
   different-ticker. Any case misclassified (e.g. a real conflict reported as
   `applied`, or an idempotent re-run reported as `applied`)?

6. **Temporal / linking edge cases.** `_apply_mappings_to_holdings` leaves a
   holding in `pending_mapping` when `quarter_end_date IS NULL`, and picks the
   active mapping whose `[valid_from, valid_to]` window contains
   `quarter_end_date`. The curated rows use `valid_from=NULL, valid_to=NULL`.
   Confirm that window logic actually links a real holding (not just the
   synthetic test). Does a curated `valid_from=NULL` mapping correctly apply to
   every quarter?

7. **Idempotency for real.** Re-run `seed_curated_cusip_overrides` twice on the
   test DB and confirm no duplicate active rows, stable ticker, second run all
   `unchanged`. Then confirm the PR's dev-probe claim by re-running the loader on
   the dev DB **inside a rolled-back transaction** — it should report
   `unchanged=2, applied=0, conflicts=0` and change nothing (XOM/HON already
   resolved).

8. **Did they change `evaluate_openfigi_matches`?** They claim they did **not**
   (the heuristic is deliberately untouched because the evidence shows it's
   unsafe). Confirm the diff leaves that function alone, and that the evidence
   for "HON's correct ticker is absent from the response" holds — re-pull
   `mapCusips(["438516106"])` via Rate Guard and check.

9. **Run the canonical gates** and confirm green: full backend `pytest -q` on the
   test DB, `node --test lib/*.test.js`, `npm run lint`, and the production build.
   The PR defers the local production build to CI on the grounds that the
   frontend is byte-identical to `main` — verify `git diff --stat main...HEAD --
   frontend` is empty; if it is not, run the build.

## Deliverable

A short report: per-area findings (with file:line + failure scenario), the
canonical-gate results you reproduced, and a final **mergeable / send-back**
verdict. If send-back, name the single most important blocker precisely.
