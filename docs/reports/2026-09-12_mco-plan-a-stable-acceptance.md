# MCO Plan A — stable-clock acceptance

## Status

**Complete within the user-approved Plan A minimum scope.** Real-data/browser acceptance and all six ordered canonical gates passed. This is readiness for user review, not merge/deployment authorization or a claim that all historical data and mixed-source metrics are available. Earlier clock-failure reports are retained, not rewritten.

## Baseline and boundaries

- Repair worktree: `/Users/dane/projects/ValuePilot-mco-plan-a`, branch `codex/mco-plan-a`, HEAD `15f4ba02944a6fe29962136665d9e906010c422a` plus uncommitted repairs.
- Tested integration: `/Users/dane/projects/ValuePilot-mco-integration`, committed S2 HEAD `1065f692a3b1453fa221c1da42cedbc4ab85a9fb` plus the same repairs. It excludes the original workspace's uncommitted economics work.
- No product-code changes in this stable-clock continuation. Acceptance helpers were corrected/hardened, and this task/report/backlog updated. No commit, push, merge, deployment, or data promotion.
- Exact write targets: the existing task acceptance clone `valuepilot_acceptance_mcoplana` and recreated disposable `valuepilot_test_mcoplanaci`. Original MCO experiment, shared development and production remain read-only/unmodified by this work. No external SEC/13F acquisition or shared-service restart.
- At12:37:06 UTC the database clock was later than every retained parse, publication and identity timestamp. No timestamp, cutoff or clock was backfilled. A15-second read-only sampler records subsequent budget/clock checkpoints; samples are not proof of every instantaneous peak.

## Actual SEC and Value Line results

Normal v2.12 publication finalized run `27766134-e34b-5165-ba26-a05d443eb607` from9 eligible retained v2.12 runs. It appended198 canonical facts, taking the total275→473. Same-request publication replay returned the identical run/fact IDs and preserved473 facts. No additional SEC parsing/download was needed; the existing40 parse runs were reused. FY2018 remains a rejected filing, even though some historical duration observations may be available from other valid filings; this is not a claim of complete annual balance-sheet coverage.

The original frozen matrix remains unchanged, SHA256 `d5c852b16003012bcb0b8c3ea69286ec546e12be7e62f57ec0a4b196469c7a64`. The approved overlay keeps all27 core positions:25 exact numeric SEC actuals plus2 explicit nonnumeric current-debt gaps inFY2022/FY2023. Six additional EPS/operating-income positions also match exactly. All31 numeric positions passed authenticated original-evidence checks: fact/publication/raw IDs, period, unit/currency, source role, exact value and retained statement locator. An independent read-only reviewer checked actual artifacts and source-version bindings rather than accepting helper PASS flags.

Normal authenticated reparse of existing Value Line document1 returned HTTP200, `status=parsed`. All24 retained annual revenue/per-share revenue values match exactly; stock1, user1, FY, units/currency, actual through2024, estimates2025–2027 and parse-run lineage were verified. Piotroski remains typed unavailable because source reconciliation lacks fiscal identity. Its warning persists in the document list. Base facts survived; no blocked numeric score was published. This verifies mapping against the retained original parser output, not a new independent transcription of every PDF cell.

Mixed-source EPS is not usable as a numeric workspace series:20 VL quarterly candidates lack fiscal identity and the existing guard blocks the45-candidate comparison unit. This does not erase canonical SEC EPS or its authorized original evidence. AC1 covers six additional SEC positions/evidence; AC7 requires core browser reading. The final acceptance artifact explicitly lists all three EPS workspace limitations. The aggregate UI's2015 date is not the scope of the block. See BACKLOG; no policy weakening was made.

Source comparison preserves FY2022 EPS residual0.73 as unexplained. FY2023 is only a numerical footnote bridge, not an independently proven economic adjustment. FY2024 EPS and all three revenue amounts match. CFO is not Value Line cash-flow-per-share; weighted diluted shares are not ending shares; noncurrent debt is not total debt. No aggregate accuracy rate or fabricated adjustment is published.

## Browser observations

Exact isolated browser URL: `http://localhost:53230/research/cases/1`, dedicated task account/case. Original app `localhost:3001` was untouched.

1. RevenueFY2024 opens `7,088,000,000 USD`,2024-01-01→2024-12-31, SEC actual, statement `$7,088` ×1,000,000. Current fact806/publication454/raw60682/authority3933.
2. Added only this source reference to the dedicated draft and explicitly saved revision2. No thesis, valuation or investment decision was invented. Reload retained both new806 and old613 references.
3. Revision2 reopens806 with exact original evidence. Revision1 reopens613/publication262/raw34522/authority2166 and labels it historical/superseded, still authorized, not its replacement.
4. Annual table explicitly shows unavailable FY2022/FY2023 current-debt cells; no zeros. Debt components and share-count definitions remain qualified.
5. Document list shows Parsed plus the Piotroski unavailable/reconciliation warning. Financial details page8 of10 exposes EPS `unavailable: unresolved_source_reconciliation`, fiscal year unproven, with no numeric output.

This is browser sampling, not31 separate browser evidence interactions. All31 were separately checked through authenticated HTTP.

## Acceptance-tool corrections and evidence

The first workspace helper failed because it incorrectly expected `status=not_returned`; the real typed contract is `status=unavailable`, `reason_code=not_returned`. It also mistakenly required every additional EPS observation in the mixed workspace, exceeding AC7. Its failed output is retained as `approved-contract-v212stable.json`.

The corrected helper explicitly validates33 unique frozen slots, exact expected date/unit/currency, cross-file fact/publication/raw input IDs and the real gap shape. It requires core workspace numeric availability, separately verifies additional SEC/HTTP values, and records EPS workspace limits. Eight in-memory negative variants (missing gaps, duplicate slots, wrong unit/currency/date, mixed fact/publication IDs and HTTP fiscal year) are rejected before HTTP/DB access.

Artifacts under `storage/mco_plan_a/`:

- `clock-readiness-stable1.json`, `budget-clock-stable1.jsonl`.
- `publish-v212stable.json`, `canonical-matrix-v212stable.json`, `http-evidence-v212stable.json`.
- `approved-contract-v212verified.json`, `workspace-v212stable.json`, `source-comparison-v212stable.json`.
- `vl-reparse-approved-stable1.json` and unchanged earlier failed attempts.
- `backend-full-v212-stable1.log`: this run captures stdout/stderr to disk, avoiding the previous truncated-log limitation.

## Ordered canonical gate

Working directory: `/Users/dane/projects/ValuePilot-mco-integration/storage/mco_ci`.

| Exact command | This run |
| --- | --- |
| `docker compose up -d --build` | passed |
| `docker compose exec -T api alembic upgrade head` | passed, head20260912130000 |
| `docker compose exec -T api pytest -q` | 2941 passed,2 dependency deprecation warnings,1173.15s; exit0 |
| `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` | 263 passed,0 failed; exit0 |
| `docker compose exec -T web npm run lint` | exit0 |
| `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` | exit0; TypeScript and27 static pages passed |

These are local integration gates, not remote CI. Full backend/frontend/lint/build logs are saved with the `v212-stable1` suffix. `git diff --check` passed in both repair and integration; the production build left no tracked next-env/tsconfig changes. Changed/new backend and frontend files were compared across the two worktrees; the only byte difference is an extra trailing blank line in the integrated v2.11 migration, with no executable difference.

## Final state and limits

- Original experiment unchanged:23 facts/10 parse runs/head20260909150000. Task acceptance:824 facts/40 runs/head20260912130000; document1 contributes325 source facts and no Piotroski score; case1 has exactly2 revisions. The source and acceptance counts were checked read-only after all gates.
- CI public facts/users/parse runs all0; generated pytest schemas all cleaned by the fixture. The recreated disposable CI database remains with migrations only (about93MB whole DB), ready for another gate. No retained data was deleted.
- Original budget baseline remains3,735,552 bytes. Final checkpoint `environment-stablefinal.json` is596,767,270 bytes, including the entire CI database and task artifacts. The76 samples from12:38:55 through12:58:44 UTC moved strictly forward; their largest budget checkpoint is699,368,415 bytes. No instantaneous-peak guarantee is inferred between samples. The task's sampler was intentionally stopped after validation; no shared service was stopped or restarted.
- Preserved limitations:2 core debt gaps; mixed-source EPS unavailable; FY2018 filing rejected; FY2022 EPS0.73 residual unresolved; 2023 bridge economic interpretation unverified; PDF cells were not independently retranscribed this continuation; no expanded AAPL persisted/browser acceptance or uncommitted economics UI acceptance.
- The earlier wrong-target old-test account/token remains untouched pending cleanup authorization. That historical incident is recorded in the task and prior continuation report; it was not repeated here.

No remaining blocking finding was identified within the accepted minimum contract. Follow-ups are recorded in BACKLOG. Do not equate this conclusion with all-company/all-history accuracy, a complete investment analysis, remote CI approval, or permission to commit/push/merge/deploy.
