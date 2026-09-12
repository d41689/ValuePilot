# MCO Plan A — delivery preparation

## Outcome and stop rule

Prepare the already validated Plan A changes for a bounded, reviewable delivery without adding EPS functionality, altering existing evidence, or mixing in unfinished economics work. Acceptance is a verified dependency baseline, explicit inclusion/exclusion list, final-diff review, and an exact next-action authorization request. Preparing this package is not permission to commit, push, open/merge a PR or deploy.

## Independently checked remote state

On2026-09-12, read-only `git ls-remote` and `gh pr list` returned:

- Remote `main`: `15f4ba02944a6fe29962136665d9e906010c422a` (S1, PR147).
- S2 local commit: `1065f692a3b1453fa221c1da42cedbc4ab85a9fb`, directly atop that main. No remote `codex/s2-annual-financials-evidence` branch.
- A repair branch: `codex/mco-plan-a`, still at main plus uncommitted changes. No remote branch of that name.
- No open PRs were returned. The GitHub repository is public.
- The successfully tested application is committed S2 plus A repairs in the separate integration worktree, not A alone on main and not the original dirty economics worktree.

The original S2 task explicitly retains user AC9 walkthrough and remote CI as outstanding; MCO local acceptance does not silently close those separate conditions.

## Delivery order

1. Obtain authorization for scoped local commits, pushes and two review PRs. Do not infer merge/deployment permission.
2. Publish the existing S2 commit as its own review PR; exclude all original workspace uncommitted changes. Preserve its outstanding user acceptance and verify its exact remote CI SHA.
3. Prepare A as an independent commit on top of that exact S2 baseline (stacked review), preserving the tested combination. Do not fold S2 and A into an unexplained monolithic diff.
4. Review both PRs against their actual bases. Resolve real in-scope findings, retain accepted gaps and disclose local-only evidence. The internal assistant review is not GitHub third-party approval.
5. Before any requested merge, resolve S2's user acceptance, rerun required gates on the actual final tree, check remote CI, and obtain merge authorization. If S2 is squash-merged or main moves, integrate A onto the resulting main without force-pushing or rewriting user work silently.

## Files and evidence boundary

Include only A's explicit changed/new files in the repair worktree:

- Backend services: SEC statement/ingestion/publication compatibility; mapping spec; typed optional calculation outcomes; document API projection.
- Four new migrations20260912100000–20260912130000; associated SEC/VL/ingestion/API regressions and the bounded test fixture changes.
- Reviewed mapping/taxonomy, PRD, BACKLOG and this task's documentation/reports.
- Frontend document-processing helper and tests; UploadZone, document list and AppShell disclosure changes.

Do not use `git add .` or an entire-worktree blanket stage. Inspect the exact staged paths before committing. Exclude:

- All `storage/` files, original/retained PDFs, raw SEC artifacts, database copies, acceptance JSON/logs, temporary upload files and local Compose/runtime configuration. They remain local evidence; they are not automatically licensed for a public PR.
- Credentials, session state, `.env` files and the earlier wrong-target disposable account/token. Their cleanup remains unauthorized.
- Original workspace uncommitted BusinessEconomics, S2 follow-ups, next-env/tsconfig build changes and unrelated reports/tasks.
- User-authored cases/notes and any production/shared business data.

Reviewable documentation can state results and limitations, but remote reviewers must be told which evidence is local-only and not independently accessible to them. Do not attach the proprietary Value Line PDF or upload complete raw evidence to the public repository to make review easier.

## Verification record

The preceding stable-clock gate executed all six exact AGENTS commands in isolated CI Compose: backend2941 passed, frontend263 passed, migrations/lint/production build passed. [Full report](../reports/2026-09-12_mco-plan-a-stable-acceptance.md) binds the integrated source baseline, real31-number evidence check,25+2 core denominator,24 VL revenue values, browser save/reopen and budget limits.

Final review subsequently required the small product correction described below. A second complete gate was therefore started against the corrected integration tree, with migrations and tests restricted to the disposable CI database/schema. No business-data replay was performed. The preceding gate cannot establish readiness for the corrected tree.

## Final-diff review

A bounded independent read-only review found one in-scope P2: a first-page calculation warning followed by64 ordinary identity notes falls outside the reader's64-line window. The existing65-page test always called the aggregate writer and missed the path where later pages had no calculation outcomes. Root independently reproduced warning-count1→0 with the production reader/writer and ordinary-note append sequence, without a database connection.

The repair is owned only in `ingestion_service.py` and its calculation-outcome test file: retain the existing valid aggregate at the tail before completion, including when no new block occurs; preserve ordinary notes and do not invent empty diagnostics. Real failures still roll back. Add a failing production-path regression before implementation, then run focused Docker tests in the exact disposable CI database/schema, integrate the minimal change, and rerun all six canonical commands. Shared/retained business data and EPS scope remain unchanged.

The prior2941/263 gate is historical evidence for the preceding tree, not a gate for this correction. Independent verification and the new complete gate must finish before this delivery package is prepared. The reviewer found no other actionable issue in the bounded privacy/rollback/historical-replay checks; full parser/data review remains the separately recorded prior evidence.

Correction result: the implementer first observed4 failures (the65-page production upload path and three empty-diagnostic cases), then19 focused tests passed; the broader upload/reparse/multipage group passed34 tests. Root independently confirmed the pure-reader failure before the repair and inspected the production-path regression. A separate read-only verifier closed the P2 after checking final-commit ordering, rollback state, ordinary-note preservation and no-empty-diagnostic behavior. That verifier did not run tests and did not claim to independently reproduce the whole financial matrix.

Only5 production lines were added to the already-reviewed ingestion change: final empty-outcome aggregation and no-valid-outcome early return. The two changed files were synchronized and byte-compared against integration. New full gate logs use `delivery1`, separate from all prior logs. SHA256 for `ingestion_service.py` is `9818eb8f78bcc61923fc1006a1e8478340a6ab22fbcddab31dc4d4629aec1e07`; the test file is `515ba8ee56244ea79e71fb614bd88ee539e6a59153133b9b40996298c242bfdc`. All A runtime/test/config file hashes are recorded locally in `storage/mco_plan_a/source-files-delivery1.sha256`.

## First corrected-tree closing gate — historical clock failure

All six canonical commands were executed in order from the integration worktree's `storage/mco_ci` Compose project. Python/Node tooling ran only in containers. Results:

| Exact command | Result |
| --- | --- |
| `docker compose up -d --build` | Passed |
| `docker compose exec -T api alembic upgrade head` | Passed; disposable CI DB only, head20260912130000 |
| `docker compose exec -T api pytest -q` | **2897 passed,48 failed,2 warnings,1202.95s** |
| `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` |263 passed |
| `docker compose exec -T web npm run lint` | Passed |
| `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` | Passed; TypeScript and27 generated pages |

Full backend stdout/stderr is retained in local `storage/mco_plan_a/backend-full-delivery1.log`, despite the tool display truncating its final output. Frontend, lint and build logs have matching `delivery1` names. The code manifest check and both worktrees' `git diff --check` passed after the gate.

Read-only database clock sampling independently recorded13:22:11.003847 UTC→12:18:15.207795 UTC while monotonic time advanced15.41s, then12:18:30.616448→13:22:57.282124 over15.48s. The first failed cutoff was12:18:11.962334, rejected because it preceded the currentness authority.36 of48 failure sections directly contain the currentness-unverifiable error; the other12 show downstream workspace `coverage`/`missing_items` KeyErrors without logging the underlying response. Do not assert a directly observed root cause for those12. All48 exact failed node IDs were rerun with **unchanged code**, using a fresh automatically created/dropped CI schema: **48 passed,2 warnings,34.06s**. This strongly supports clock interference, but is diagnostic evidence, **not a passing full closing gate**. No time, cutoff, authority or test expectations were changed to obtain the rerun result.

Final read-only checkpoint `environment-deliveryposttests.json`: original retained comparison23 facts/10 parse runs, acceptance824 facts/40 runs, both unchanged. CI public facts/users/parse runs are0 and no `valuepilot_pytest_` schemas remain. The task-only CI migration database is retained.98 clock/budget samples had maximum cumulative1,096,109,297bytes and final sample725,386,102bytes against the unchanged3,735,552-byte original baseline and2GiB cap; sampled values do not prove unsampled instants. The task-only sampler was deliberately stopped (exit143), not a failed test. The first checkpoint invocation lacked PYTHONPATH and failed before connecting; the corrected Docker invocation succeeded.

**Historical delivery1 verdict: delivery closure was not complete.** The final-review defect was resolved, but the corrected tree still needed one uninterrupted green complete gate after clock stability was restored. No further business replay, shared-service restart, runtime API restart, commit, push, PR, merge or deployment occurred during delivery1. At that checkpoint the acceptance API had not been restarted to load the final five-line upload correction. The delivery2 continuation below supersedes this gate blocker, not the retained evidence. Original dirty economics work and the unauthorized old-test-account cleanup remain untouched.

## Next authorization

### Clock-restored continuation — delivery2

User reported the clock adjusted. Read-only preflight at13:40:59 UTC confirmed container and PostgreSQL times agreed, target `valuepilot_test_mcoplanaci`, public facts/users/runs0 and no residual pytest schemas. Worker/seed flags remain disabled; tests use injected network clients and isolated schemas. Original comparison23/10 and acceptance824/40 remained unchanged. Original-baseline cumulative budget started725,387,263bytes; no baseline reset. The A source hash manifest still matched. All six canonical commands were then rerun in order, with separate `delivery2` logs and clock/budget sampling. No new product changes or business-data replay were made.

**Final delivery2 result: local delivery gate PASS.** The tested composition remains committed S2 at1065f692a3b1453fa221c1da42cedbc4ab85a9fb plus uncommitted Plan A; this is not a remote CI result or standalone Plan A-on-main claim.

| Canonical step | Actual result |
| --- | --- |
| Build/start | Passed; only task CI API/web recreated |
| Migration | Passed; isolated CI DB already at20260912130000 |
| Full backend | **2945 passed,2 existing dependency warnings,1399.65s** |
| Full frontend `lib/*.test.js` | **263 passed** |
| Lint | Passed |
| Production build | Passed; TypeScript and27 generated pages |

The exact commands are the same six verbatim commands in the preceding table; retained logs are `compose-build-delivery2.log`, `migration-delivery2.log`, `backend-full-delivery2.log`, `frontend-full-delivery2.log`, `lint-delivery2.log`, and `build-delivery2.log` under the local-only evidence directory. Source-manifest verification passed after testing; no product code or test expectation was changed between the failed and successful full gates.

Read-only post-test check: CI public facts/users/runs0, no pytest schemas.93 samples from13:41:18.999728 to14:06:04.720778 UTC recorded **zero backward database-time steps**, maximum cumulative833,940,025bytes, final sample726,744,648bytes. Sample collection includes database/file-size query latency, so do not equate every wall/monotonic discrepancy with clock drift or claim unsampled instants were verified. The sampler was intentionally stopped (exit143). Final checkpoint `environment-delivery2final.json`: original23 facts/10 runs, acceptance824 facts/40 runs, cumulative726,744,799bytes; unchanged original baseline and2GiB limit. The task-only CI migration database is retained.

After all gate processes finished, only `valuepilot-mco-integration-api-1` was restarted to load the verified correction; its exact acceptance target and disabled worker/seed flags were checked first. Browser read-only smoke: reloaded MCO case1, current Revenue fact806 opened7,088,000,000 USD for FY2024 and the original consolidated-statement Revenue row, printed `$ 7,088` with1,000,000 multiplier; debt gaps remained visible. Document1 remained Parsed with explicit Piotroski-unavailable warning. No Save, Add evidence, Reparse or external SEC link was activated. This smoke does not repeat the earlier33-slot/full historical-reference matrix or replace user AC9 acceptance.

**Local Plan A delivery preparation is complete.** The clock-related gate blocker is closed based on this uninterrupted run, not a promise that the environment can never drift again. Prior accepted debt/EPS/source-comparison limitations, S2 user acceptance, actual remote CI and permission for outward delivery remain explicit. No commit, push, PR, merge or deployment was performed.

User confirmation is needed to create the scoped local A commit, push the committed S2/A branches and open two review PRs. Neither this document nor that approval authorizes merging, deploying, deleting branches/data or taking on the next EPS feature.

The clock/gate blocker is now closed by delivery2's complete run. S2 user acceptance and actual remote CI remain separate later conditions; the earlier diagnostic48-node rerun alone never established readiness.

## Authorized outward delivery

The user subsequently explicitly requested the MCO commit, push, independent Draft PR, remote CI verification and a third-party read-only adversarial review prompt. No merge or deployment was authorized. Preserve the tested composition by creating `codex/mco-plan-a-delivery` from the integration's exact S2 commit, publish the unchanged committed S2 base branch as the prerequisite for a MCO-only stacked diff, and open only the requested MCO Draft PR. Do not publish the original workspace's uncommitted economics work or create another feature PR implicitly.

The public commit includes only the explicitly reviewed source/tests/migrations, mapping/taxonomy and MCO documentation; excludes all local storage/artifacts/PDFs/runtime configuration. The authoritative third-party prompt is [MCO adversarial review](2026-09-12_mco-plan-a-final-review-prompt.md). Existing local results remain bound to the same runtime/test tree. Record actual remote head/base and Actions result in the PR and final handoff; a pending check is not a pass.

Pre-publication packaging review found no credential/raw-artifact inclusion or broken required document links. Staging exposed the previously recorded extra EOF blank line in the integrated v2.11 migration, which unstaged diff-check had not inspected while the file was untracked. Removed only that trailing blank line; runtime/test/config files now match the repair manifest exactly. No semantic implementation change was made. Remote CI must validate the actual published SHA, including this formatting cleanup and final documentation.

## PR #148 review follow-up — complete remote CI budget

The user requested minimal complete repair of independently confirmed review findings. The sole confirmed finding is a delivery blocker, not a demonstrated MCO product-code defect: Actions run [34701799760](https://github.com/d41689/ValuePilot/actions/runs/34701799760), head `e7850668bcdf309f74637d0724b2f34a4f74429e`, base `1065f692a3b1453fa221c1da42cedbc4ab85a9fb`, checked out merge `8f828e14623d8be96ef31eca49c85f8028683f60` and exceeded the job's 30-minute limit. Backend testing ran from 15:19:01Z to 15:48:05Z, with its last progress at 95%; frontend tests, lint, build and Rate Guard gates were skipped. This is not a passing run and progress alone does not establish correctness.

**Outcome / acceptance:** allow every existing remote gate to finish, and require a successful complete run on the final PR head/base combination before closing this finding. Record actual SHAs, run URL and results in the PR handoff. Local historical PASS does not replace remote acceptance.

**Minimal scope:** increase `.github/workflows/ci.yml` job timeout from 30 to 45 minutes, giving the near-complete backend suite and subsequent gates bounded headroom. Preserve every step, command, condition, runner, permission, concurrency rule and isolation setting. No MCO product changes, test omissions, relaxed assertions, migrations, data replay, shared-service restart, merge or deployment. Preserve the original dirty workspace and all retained evidence. Authorized delivery is a focused follow-up commit/push to the existing Draft PR; no additional feature PR.

**Validation / stop rule:** the existing timed-out run is the failing end-to-end signal. In a network-disabled disposable Docker container, first assert the revised budget against the unchanged workflow (expected failure), then assert it after repair and compare parsed workflow structures, permitting only that single timeout change. Run `git diff --check` and inspect the staged allowlist. Push and verify the full remote workflow, including all six exact canonical Docker commands and the existing additional Rate Guard gates. Do not call the finding resolved unless all required steps finish successfully. A stopped prior local CI container is not restarted; the YAML check has no database or host repository write access. Remote results are pending at this commit and will be recorded in the PR, without rewriting historical local results.
