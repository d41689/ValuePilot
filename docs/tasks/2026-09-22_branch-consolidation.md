# Branch consolidation — 2026-09-22

## Goal / acceptance

Integrate reviewed, independently deliverable work into main without losing local work or allowing dependent branches to drift. Preserve the investor's draft and source-traceable research before merging S2; carry those protections into MCO. Each merged implementation must pass the exact canonical Docker CI gates at its final reviewed revision. Inspect main CI and automatic deployment after merges. Finish with unique work assigned to an explicit branch, PR, or retained draft and no unclassified source changes.

## Scope and authorization

The user approved execution of the consolidation plan, including scoped fixes, commits, pushes, PR creation and merge, and post-merge deployment observation. Sequence: S2 #149, MCO #148, approved Agentic Investment Lab stories, then Business Economics. Preserve independent investment-memory proposals and historical reports as drafts. Preserve raw storage, local configuration and credentials. No data replay, deletion of business data, force push, or unrelated refactoring.

This advances research discipline and business-quality understanding: local observations must survive concurrent revisions; financial observations must retain precise, inspectable provenance.

## Baseline and preservation

- main: `15f4ba02944a6fe29962136665d9e906010c422a`.
- S2 #149: `2ede1926a7e6a7af8fabb4ad876b5289d0d38113`; previously passing CI, new draft-protection patch needs fresh gates.
- MCO #148: `69c1b9ac7a18e6217aa9341697abfb8a77141a23`; currently based on S2 evidence `1065f692`, must retarget main after S2 merge.
- Lab stories: local reviewed commit `144d42146943ada38bb5c0b162d6aff704126269`.
- Business Economics and investment-memory proposal remain uncommitted in source checkout.
- Private recovery snapshot taken before edits: binary tracked patches, untracked source/docs archives, original status inventories, and a bundle of all local branches. Raw storage remains in its existing directories.
- S1 data-readiness branch has exactly the same tree as main despite squash ancestry; treat it as delivered, not as 15 missing commits.

## Files / ownership

S2 draft fix is limited to the research-case page and `frontend/lib/researchDraftRefresh.test.js`; do not import Business Economics into S2. Root maintains this task log and delivery metadata. Later phases receive separate bounded ownership after their base is integrated. Read-only independent review precedes each substantive merge.

## Test plan

Targeted regression first (prove failure before the patch), then passing focused tests and adversarial review. Final gate uses GitHub CI's isolated PostgreSQL and these exact in-container commands, in order:

```sh
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

CI also runs Rate Guard tests and topology checks. Do not weaken point-in-time guards to accommodate the previously observed local VM clock instability. Production Compose explicitly runs `alembic upgrade head` before starting the API; migration execution is part of the existing deployment path.

## Sign-off trail

- 2026-09-22: execution authorized; preservation snapshot complete; final-revision gates and merges pending.
- S2 draft regression: adding the existing regression to the delivery checkout first failed because the explicit discard handler was missing. After the bounded page patch, all nine behavior tests pass in a read-only, network-disabled Docker container. The test executes actual page effects/callbacks and confirms dirty notes/thesis, original expected head, conflict persistence, and explicit fresh-data discard behavior. Independent review and fresh remote CI pending.
- Historical production blocker discovered before merging: deploy run 34502087251 failed at revision 20260904180000 because prior migration 170000 updates retained facts and queues the initially deferred SEC reciprocal trigger. The deployed 140000 baseline does not rerun 120000's immediate-constraint setting. Empty CI missed this populated upgrade path. User asked whether to include a separate bounded migration repair; merges held pending that scope decision. No production state changed.
- Removed obsolete S1 branches only after verifying PR147 merged, the data-readiness tree exactly equals main, the research-plan branch is an ancestor, and the recovery bundle validates. The squash commit history remains recoverable from that bundle.
- Independent S2 adversarial review reproduced a cached-head 409 gap: editing after a rejected save cleared the conflict flag while the query cache still showed the old revision. Added a failing regression (7/9 passed before fix), then latched the conflict and blocked direct save callbacks even when the cache head still matches. Both cached and refreshed-head editing cases now remain covered; nine tests pass. Independent reviewer repeated the actual callback reproduction and nine tests, reporting PASS with no remaining scoped finding. Full CI must use the subsequent commit, not the superseded 05276295 run.
- User explicitly approved the separate populated-upgrade repair and continued merges. Repair PR151 now has a regression from the deployed revision, focused5/5 tests and independent PASS; canonical CI is running. No additional approval is needed for the previously authorized sequence.
- Root's final draft-preservation check identified an existing save-in-flight loss path. Independent read-only simulation executed the actual save, edit, persistence, success and hydration callbacks: submit thesis A, type B while the request is pending, then success removes B's recovery key and the new head reloads A. Fix remains within the accepted draft-preservation scope: disable all draft-mutating controls while saving, gate the shared update callback, preserve error/retry behavior, and align the remaining lower Save button's conflict-disabled state. Add failing behavior regression first; no new server or state-machine architecture.
- Save-in-flight regression: before the patch, 9/12 tests passed and three new checks failed (direct callbacks, full A/edit-B/success/hydration lifecycle, and pending-state control coverage). After the bounded guards, 12/12 pass. Independent read-only reviewer repeated those 12 checks and verified that the existing error callback preserves draft/storage/loaded head and editing reopens after pending clears; PASS, no remaining scoped finding. The full frontend test glob also passes in the read-only Docker test environment (271 tests). The final combined branch still requires the canonical CI gate after merging the migration repair.
