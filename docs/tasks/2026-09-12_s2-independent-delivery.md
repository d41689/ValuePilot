# S2 independent delivery

Date: 2026-09-12

## Goal / Acceptance Criteria

Deliver committed S2 financial reading and guided research notes independently
to `main`, then permit the separate MCO repair PR to target that dependency.
This advances understanding business quality, reconstructing trustworthy
historical economics, and disconfirming a thesis through traceable evidence.

- Preserve the exact committed S2 product scope from
  `1065f692a3b1453fa221c1da42cedbc4ab85a9fb` and the original dirty workspace.
- Reconcile S2 and reading-first acceptance evidence through independent review.
  Historical agent walkthroughs do not imply personal user acceptance.
- Pass fresh full canonical CI for the final PR head/base; no skipped commands.
- Resolve actionable in-scope findings before the delivery lead's merge checkpoint.
- Preserve ancestry so MCO #148 can have an MCO-only diff against main.

## Scope and authorized side effects

In scope: new task-owned worktree
`/Users/dane/projects/ValuePilot-s2-delivery`, branch
`codex/s2-annual-financials-delivery`, Draft PR #149 to main, delivery records,
and the exact already-approved CI timeout repair (30 to 45 minutes).
The user authorized the S2/MCO PR sequence and acknowledged that successful
main CI triggers the existing production deployment. Each merge still has an
internal delivery-lead checkpoint.

Out of scope: uncommitted BusinessEconomics/draft changes, product expansion,
source fetching, retained-data replay, local/shared/production business-database
tests or migrations, deployment configuration changes, manual deployment, and
cleanup (owned by the delivery lead).

## References and files

- [S2 acceptance](2026-09-10_s2-annual-financials-evidence.md)
- [Reading-first acceptance and browser evidence](2026-09-10_reading-first-research-path.md)
- [Research architecture](../architecture/research-decision-support.md)
- [Existing deferrals](../BACKLOG.md)
- Delivery edits: this file and `.github/workflows/ci.yml` only.

## Test plan

Run GitHub Actions CI against its isolated ephemeral PostgreSQL instance. Its
workflow executes the canonical commands in order, without changing any command:

```sh
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

Also retain the existing Rate Guard tests and topology check. Inspect PR
head/base, diff, review state, and full successful job steps before merging.

## Execution / sign-off

- Starting main: `15f4ba02944a6fe29962136665d9e906010c422a`.
- Starting S2 product commit: `1065f692a3b1453fa221c1da42cedbc4ab85a9fb`.
- Draft PR: <https://github.com/d41689/ValuePilot/pull/149>.
- S2 product diff: 37 files, 3,391 insertions and 113 deletions.
- Original S2 and historical MCO dirty worktrees were inspected read-only and
  remain untouched. No local runtime or business data was changed.
- CI timeout repair matches MCO commit `69c1b9ac7a18e6217aa9341697abfb8a77141a23`
  exactly. MCO CI run `34722371022` needed 33 minutes 10 seconds for the full
  job, proving that the old 30-minute limit can terminate a valid full gate.
  This grants bounded execution headroom without weakening test coverage.
- Independent review, current full CI, acceptance reconciliation, and merge
  checkpoint remain pending. Stop when all have evidence and no in-scope risk
  remains; do not represent historical results as a current gate.

## Review correction: unavailable evidence must not retain partial proof

Terra identified an in-scope PRD H.9 violation: statement locator/text failure
changed the evidence state to unavailable but retained a canonical value and
legacy operand inputs. The delivery lead independently reproduced the API
contract failure with synthetic inputs in a read-only, network-disabled Docker
container. The current UI fails closed; this is not evidence of unauthorized
data exposure. Merge is held until corrected and independently re-reviewed.

Authorized minimal scope adds only `sec_financial_evidence.py` and its existing
unit test file. Unify unavailable responses, including nonpublished results,
so identity/status remain while numeric payloads and partial input/locator
proof do not. No PRD weakening, source fetching or database writes are needed
for the pure regression. The existing real-publication DB regression will also
assert the corrected contract in the fresh full remote gate.

Regression evidence: added six failure-stage/reason cases before the service
change; the unchanged implementation failed all six (five retained numeric
payloads, one lacked consistent status metadata). After the minimal helper
change, the six new cases plus six existing pure safety/graph/reference cases
passed: **12 passed, 9 deselected, 0.91 seconds**. Docker used the existing API
dependency image with this worktree's backend bind-mounted read-only,
`--network none --read-only --tmpfs /tmp`, synthetic unused database settings,
and pytest `--noconftest -p no:cacheprovider`; no database fixture or app startup
was invoked. The first invocation lacked PYTHONPATH and failed collection;
setting `/code` corrected the harness before recording red/green evidence.
`git diff --check` passed. These pure tests are iteration evidence only; final
full remote CI and independent review remain required on the resulting head.

## Full CI exposed two stale unavailable-evidence expectations

Run [34726068693](https://github.com/d41689/ValuePilot/actions/runs/34726068693)
on `876737f0c5183792c6db66ab4e548e6ec05cff1d` failed: **2 failed, 2,813 passed,
2 warnings, 1,523.88 seconds**. Subsequent frontend/Rate Guard gates did not run;
this is a failed full gate, not a pass. Both failures were in
`test_sec_canonical_read_api.py`: the missing-statement-label fixture still
expected filing/input proof, and an unresolved publication still expected
inputs. These assertions contradicted the independently accepted PRD H.9 fix.

The delivery lead authorized alignment of only that test file and this record.
Keep the original fixtures and all privacy, owner visibility, source-conflict,
and recursive forbidden-content checks. Assert explicit unavailable reasons,
preserved identity/status metadata, and empty/null numeric, input, locator and
filing proof. Remove only the now-unused parser-version import. The positive
authenticated readable-evidence endpoint and bound retained-statement fields
remain covered by `test_sec_financial_evidence.py`; its tests are unchanged.
No production code or safety scanner is weakened. The failed remote run is the
red evidence; another full remote run must prove the aligned final tree.
