# T1-FU active-filing authority — review results

**Review date:** 2026-07-09  
**Reviewed worktree:** `claude/13f-t1fu-active-filing-authority` (`git diff HEAD`
plus untracked `backend/tests/unit/test_13f_active_filing_authority.py`)  
**Latest verdict:** **review findings resolved in the backend scope checked.**
See the fourth-review section below; earlier sections are preserved as
historical findings from prior iterations.

## Fourth review after follow-up fixes — 2026-07-09

**Reviewed worktree:** `claude/13f-t1fu-active-filing-authority` after the
third follow-up fixes in `git diff HEAD` plus untracked
`backend/tests/unit/test_13f_active_filing_authority.py`.

**Verdict:** **review findings resolved in the backend scope I checked.** The
third-review `13F-NT/A` consumer mismatch is fixed, the targeted rollback-only
reproductions now return the expected notice semantics, and full backend tests
pass. I did not run the frontend canonical gates in this review turn, so this
is not a full repository closing-gate sign-off.

Targeted repro after the fix:

```text
quarters reported_elsewhere
holdings.reason.code NOTICE_REPORTED_ELSEWHERE
lens {'is_nt_quarter': True}
```

The earlier `holdings {'code': None}` reproduction was a script mistake: the
user API nests the reason under `payload["reason"]["code"]`, and the fixed path
now returns `NOTICE_REPORTED_ELSEWHERE` there.

Relevant code now uses the shared NT family constant:

- `backend/app/services/thirteenf_user_api.py` imports `NT_FORM_TYPES` and uses
  it for holdings unavailability, quarter status, and filing caveats.
- `backend/app/services/oracles_lens/base_primitives.py` uses `NT_FORM_TYPES`
  in `_is_nt_quarter`.
- `backend/app/services/thirteenf_ownership_changes.py` uses `NT_FORM_TYPES`
  for prior-quarter NT unavailable reason.
- `backend/app/services/thirteenf_filing_detail.py` uses `NT_FORM_TYPES` for
  notice report/coverage normalization when an NT/A row is present.

Verification run:

```bash
TEST_URL='postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test'
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q
```

Result: `1151 passed, 3 warnings in 82.80s`.

Targeted set also passed before the full run:

```bash
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q \
  tests/unit/test_13f_active_filing_authority.py \
  tests/unit/test_13f_user_api.py \
  tests/unit/test_13f_mvp4_base_primitives.py \
  tests/unit/test_13f_ownership_changes_compute.py \
  tests/unit/test_13f_amendment_policy.py \
  tests/unit/test_13f_nt_handler.py
```

Result: `113 passed in 2.11s`.

### Remaining note

`INGESTION_FORMS` / daily index ingestion still do not ingest `13F-NT/A`
directly. That appears consistent with the current ingestion scope; the fixes
above make already-present or admin-applied `13F-NT/A` rows safe for active
filing consumers. If product wants first-class automated NT/A ingestion, that
should be a separate explicit scope item.

## Third review after follow-up fixes — 2026-07-09

**Reviewed worktree:** `claude/13f-t1fu-active-filing-authority` after the
second follow-up fixes in `git diff HEAD` plus untracked
`backend/tests/unit/test_13f_active_filing_authority.py`.

**Verdict:** **still not fully clean.** The two findings from the prior
re-review are fixed, but the `13F-NT/A` support path is still inconsistent:
one consumer was fixed while other exact-`13F-NT` consumers still misclassify an
active `13F-NT/A`.

Targeted verification:

```bash
TEST_URL='postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test'
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q \
  tests/unit/test_13f_active_filing_authority.py \
  tests/unit/test_13f_amendment_policy.py \
  tests/unit/test_13f_nt_handler.py \
  tests/unit/test_13f_mvp3_controlled_reparse.py \
  tests/unit/test_13f_filing_detail.py \
  tests/unit/test_13f_value_units.py \
  tests/unit/test_ingest_job_failloud.py
```

Result: `92 passed in 1.89s`.

### Confirmed fixed from the prior re-review

- Admin `defer` now writes a dedicated `deferred` terminal status and Rule 1
  excludes it from automatic RESTATEMENT competition
  (`backend/app/services/thirteenf_admin_dashboard.py:489-496`,
  `backend/app/services/thirteenf_filing_detail.py:623-630`). The prior
  rollback-only reproduction now returns:

  ```text
  {'orig_active': True, 'rst_active': False, 'rst_status': 'deferred'}
  ```

- `nt_only_manager_ids` now treats active `13F-NT/A` as NT-family
  (`backend/app/services/thirteenf_holdings_query.py:14-20,65-70`). The prior
  denominator reproduction now returns:

  ```text
  {'nt_active': False, 'nta_active': True, 'nta_status': 'applied', 'nt_only_has_mgr': True}
  ```

### P2 — `13F-NT/A` is only partially treated as NT-family

**Files:** `backend/app/services/thirteenf_holdings_query.py:14-20`,
`backend/app/services/thirteenf_user_api.py:86,445,506`,
`backend/app/services/oracles_lens/base_primitives.py:159-168`.

The new `NT_FORM_TYPES = ("13F-NT", "13F-NT/A")` comment says an active
`13F-NT/A` must be treated as a notice everywhere exact `"13F-NT"` was. The
readiness denominator path now does that, but user-facing manager APIs and
Oracle's Lens streak logic still use exact `"13F-NT"`.

Rollback-only reproductions in `valuepilot_test` with an active `13F-NT/A`:

```text
quarters unavailable
holdings {'status': 'unavailable', 'code': None, 'message': None}
{'is_nt_quarter': False}
```

Expected results:

- manager quarter status should be `reported_elsewhere`, not generic
  `unavailable`;
- holdings response should return `NOTICE_REPORTED_ELSEWHERE`, not
  `NO_CURRENT_HOLDINGS` / unstructured unavailable;
- Oracle's Lens `_is_nt_quarter` should return true so the NT quarter breaks
  the streak with the intended NT caveat instead of being treated like a normal
  no-holding quarter.

**Required fix:** import and use `NT_FORM_TYPES` in the remaining exact-NT
consumers, at least `thirteenf_user_api` and
`oracles_lens/base_primitives.py`. Add tests for active `13F-NT/A` in those
paths, not only `nt_only_manager_ids`.

### Non-blocking observation — `deferred` is intentionally outside pending counts, but document the product choice

The new `deferred` status is terminal for pipeline purposes and no longer
appears in the pending-amendments queue or health/readiness pending counts,
which still key on `amendments_pending` / `amendment_failed`. That can be a
valid product choice if "defer" means "park and do not block scoring." It
should be documented in the task/PR because it is a visible semantic change
from the old `defer -> amendments_pending` behavior.

## Re-review after fixes — 2026-07-09

**Reviewed worktree:** `claude/13f-t1fu-active-filing-authority` after the
follow-up fixes in `git diff HEAD` plus untracked
`backend/tests/unit/test_13f_active_filing_authority.py`.

**Verdict:** **still not ready.** Most previously reported issues are fixed, but
one admin lifecycle bug remains P1 and one `13F-NT/A` path still reproduces the
P2 denominator mismatch. I also verified that the relevant targeted tests pass:

```bash
TEST_URL='postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test'
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q \
  tests/unit/test_13f_active_filing_authority.py \
  tests/unit/test_13f_amendment_policy.py \
  tests/unit/test_13f_mvp3_controlled_reparse.py \
  tests/unit/test_13f_filing_detail.py \
  tests/unit/test_13f_value_units.py \
  tests/unit/test_ingest_job_failloud.py
```

Result: `77 passed in 1.83s`.

### Fixed from the prior review

- Admin `apply` / `reject` now take the period advisory lock first and converge
  through `apply_active_filing_policy` instead of writing the active flag
  directly (`backend/app/services/thirteenf_admin_dashboard.py:478-501`).
- Rule 2 now selects one applied amendment owner and demotes rejected stray
  actives (`backend/app/services/thirteenf_filing_detail.py:671-681`).
- Mixed `accepted_at` NULL/non-NULL restatement pools no longer auto-switch;
  the disputed pool and kept active filing are flagged
  (`backend/app/services/thirteenf_filing_detail.py:631-640`).
- Restatement ties now flag the kept-active filing
  (`backend/app/services/thirteenf_filing_detail.py:642-658`) and resolved ties
  clear stale residue group-wide.
- Controlled reparse validation failure now persists `rejected` and reconverges
  through the authority (`backend/app/services/thirteenf_controlled_reparse.py:259-268`).
- `ACCEPTANCE-DATETIME` is parsed as Eastern wall time and converted to UTC, and
  filing-date logic uses the Eastern calendar date.
- The concurrency test now directly probes `pg_try_advisory_xact_lock`, and the
  ingest sweep releases period locks per group (`backend/app/services/thirteenf_admin_dashboard.py:3659-3670`).
- A real bulk-ingest composition test was added.

### P1 — Admin `defer` is not honored; the authority immediately re-applies the restatement

**Files:** `backend/app/services/thirteenf_admin_dashboard.py:474-501`,
`backend/app/services/thirteenf_filing_detail.py:615-669`.

`resolve_amendment(..., action="defer")` sets
`amendment_status="amendments_pending"` and then immediately calls
`apply_active_filing_policy`. Rule 1 treats any parsed HR-family RESTATEMENT
whose status is not `rejected` or `informational` as competing. That includes
the just-deferred restatement, so the authority activates it and changes its
status to `applied`.

Rollback-only reproduction in `valuepilot_test`:

```text
{'orig_active': False, 'rst_active': True, 'rst_status': 'applied'}
```

Expected result for a defer action: the amendment remains deferred/pending and
does not start serving product holdings as an applied restatement. Current
result: the operator's defer action is erased in the same transaction.

**Why this blocks:** the admin workflow exposes `defer` as a valid resolution
action, but the new convergence makes it impossible to defer a parsed
RESTATEMENT. This is a product correctness issue in the same admin lifecycle
area as the original P1.

**Required fix:** make `defer` a state the authority excludes from automatic
RESTATEMENT competition, or remove/rename the action if the intended semantics
are “leave eligible for auto-apply.” Add a regression test mirroring the
timeline above.

### P2 — `13F-NT/A` can still become active through admin apply and then is missed by `nt_only_manager_ids`

**Files:** `backend/app/services/thirteenf_admin_dashboard.py:484-501`,
`backend/app/services/thirteenf_filing_detail.py:671-681`,
`backend/app/services/thirteenf_holdings_query.py:58-66`.

The follow-up fix prevents an automatically parsed `13F-NT/A` restatement from
winning Rule 1, because Rule 1 is restricted to HR-family forms. But Rule 2
still allows any amendment with `amendment_status == "applied"` to own the slot,
including `13F-NT/A`. The admin apply path can therefore activate an NT/A. The
consumer `nt_only_manager_ids` still recognizes only exact `13F-NT`, so an
NT/A-only active manager is excluded from the expected-filers denominator
incorrectly.

Rollback-only reproduction in `valuepilot_test`:

```text
{'nt_active': False, 'nta_active': True, 'nta_status': 'applied', 'nt_only_has_mgr': False}
```

**Required fix:** either make Rule 2 reject/ignore NT/A as an active owner, or
teach NT-only consumers to treat active `13F-NT/A` consistently as a notice
filing. The current state is neither “unsupported and guarded” nor “supported
end-to-end.”

### Non-blocking observation — conflicting non-NULL `accepted_at` still overwrites silently

**Files:** `backend/app/services/thirteenf_filing_detail.py:23-39`,
`backend/app/services/thirteenf_filing_detail.py:384`.

The new `merge_accepted_at` helper prevents NULL erasure and enables the
Eastern→UTC parser correction to propagate, which addresses the most important
data-loss case. It still overwrites any different non-NULL value without
recording a review warning. That is defensible for the intentional parser
correction, but it is looser than the prior review's suggested “preserve
existing value unless an explicit correction workflow authorizes overwrite.”
I would not block on this while the ET→UTC migration is intentional, but it
should be called out in the PR if retained.

The new authority improves the normal single-original / single-restatement path,
but the active-filing invariant is still bypassed by admin and controlled-reparse
writers. The admin status lifecycle can also leave a rejected filing active even
after a policy sweep. Because `is_active_for_manager_period` gates the whole
product surface, these are correctness failures rather than cleanup items.

## Findings

### P1 — Admin resolution bypasses both the authority and the period lock

**Files:** `backend/app/services/thirteenf_admin_dashboard.py:445-487`,
especially `:459-487`; authority lock and transition at
`backend/app/services/thirteenf_filing_detail.py:421-434,475-513`.

`apply` / `activate_as_original` directly demote and activate rows without the
period advisory lock. `reject` / `mark_informational` only change status and
commit, so an active rejected/informational restatement remains active until
some future sweep.

Concrete status failure:

1. Restatement R is active and `applied`.
2. Operator selects Reject.
3. The action commits `R.amendment_status='rejected'` but leaves
   `R.is_active_for_manager_period=true`.
4. Product queries continue serving R even though the operator rejected it.

Concrete deadlock:

1. Admin locks target X with `FOR UPDATE`.
2. Sweep takes the period advisory lock, loads the group, demotes original O,
   and flushes, thereby locking O.
3. Admin attempts to flush O=false and waits for sweep.
4. Sweep attempts to flush X=true and waits for admin.
5. PostgreSQL aborts one side as a deadlock.

A second interleaving can let admin commit X active after the sweep loaded stale
state; the sweep then activates W and hits
`uq_active_filing_per_manager_period`, rolling back the whole Phase-5
transaction.

**Required fix:** acquire the same period lock before any admin state transition,
then perform the resolution and group convergence in that transaction. Reject
and informational actions must immediately select the next eligible filing.
This finding alone blocks merge.

### P1 — Rule 2 does not identify an amendment owner and can preserve a rejected active filing

**File:** `backend/app/services/thirteenf_filing_detail.py:572-579`; contributing
admin lifecycle at `backend/app/services/thirteenf_admin_dashboard.py:459-481`.

Rule 2 means “any amendment row has status `applied`”, not “this unique applied
amendment owns the active slot.” It only demotes originals and never selects an
owner or demotes another amendment.

Timeline:

1. Admin applies NEW_HOLDINGS A: A is active/applied.
2. Admin applies B: B becomes active/applied; A remains inactive/applied.
3. Admin rejects B: B remains active/rejected.
4. Sweep sees historical A still `applied`, enters Rule 2, and touches only
   originals.

Wrong result: B remains active/rejected forever, A is inactive/applied, and the
original is inactive. A rollback-only test reproduction returned
`decision='amendment_owned', changed=false, active_id=B`.

**Required fix:** define and enforce a unique applied owner, including status
transitions for superseded amendments, and make Rule 2 converge all amendment
rows as well as originals.

### P1 — Missing `accepted_at` silently selects the wrong filing

**Files:** `backend/app/services/thirteenf_filing_detail.py:412-418,534-545`;
parse skip at `backend/app/services/edgar_ingestion.py:1354-1359`; unconditional
sweep at `backend/app/services/thirteenf_admin_dashboard.py:3534-3558,3631-3644`.

NULL maps to `datetime.min`. If a newer, currently active restatement's primary
document fails to load while an older sibling has `accepted_at`, the partial
success job ranks the newer filing last, demotes it, and activates the older
one. NULL is missing evidence, not evidence of earliest acceptance.

The NULL-NULL fallback is also not a safe SEC ordering guarantee. Accession
prefixes identify the submitting CIK, which may be a filing agent rather than
the manager; one manager can use different submitters. A later filing with
`0000899140-...` sorts below an earlier filing with `0001279936-...`.
SEC documentation describes the suffix as a sequence for the submitting CIK and
notes that the counter is “usually, but not always” reset annually.

The dev database currently has no NULL competitors and no resulting active
flip, but 231/373 accession prefixes differ from manager CIK. It also contains
three manager-period groups where accession lexical order and acceptance-time
order differ; current restatement precedence happens to avoid a flip in those
groups.

**Required fix:** when a competition pool contains missing acceptance metadata,
preserve the current active filing and raise a review warning (or skip that
group for the failed run). Add mixed NULL/non-NULL and different-submitter
tests.

### P1 — Restatement ties do not propagate uncertainty to the active product filing

**Files:** tie transition
`backend/app/services/thirteenf_filing_detail.py:540-560`; active-only query
`backend/app/services/thirteenf_holdings_query.py:17-39`; scoring status check
`backend/app/services/oracles_lens/signal_weighted_score.py:741-769`.

Timeline:

1. Original O is active with `no_amendments_seen`.
2. Parsed restatements R1/R2 have equal non-NULL acceptance timestamps.
3. Policy keeps O active and marks only R1/R2 `amendments_pending`.
4. Oracle's Lens loads only O and checks only O's status.

Wrong result: O continues contributing as a clean signal, with no pending
amendment caveat or MVP5-02 exclusion, even though two full restatements dispute
it. Global readiness/health warnings do not protect the score.

**Required fix:** persist unresolved status at manager-period level or make
product consumers check unresolved siblings. Add a policy-to-score composition
test.

### P1 — Controlled-reparse restoration is outside the lock and is not durable under the authority

**Files:** `backend/app/services/thirteenf_controlled_reparse.py:237-272`;
authority eligibility at
`backend/app/services/thirteenf_filing_detail.py:526-570`.

The validation-failure path directly restores the prior active pointer without
the period lock. It also does not persist a state that makes the successfully
parsed restatement ineligible. A later sweep therefore sees that restatement as
eligible and deterministically switches the active pointer back, undoing the
validation gate's explicit restoration. The current parse run is restored
separately, so this does not necessarily expose the rejected new holdings, but
the active-pointer rollback contract is still lost.

**Required fix:** serialize restoration with the period lock and persist a
validation-rejected/override state that the authority honors. A whitelist for
this direct writer is insufficient.

### P2 — Restatement tie recovery leaves the loser permanently pending

**Files:** `backend/app/services/thirteenf_filing_detail.py:547-569`; affected
readers `backend/app/services/thirteenf_admin_dashboard.py:1082-1117` and
`backend/app/services/thirteenf_health.py:99-102,239-260`.

R1/R2 first tie and both become pending/warned. After correcting R2's timestamp,
the policy activates R2 and clears only R2. R1 remains inactive with
`amendments_pending` and `amendment_sort_warning=true` forever, producing a
false admin task, daily count, and stale-restatement alert.

Reproduced in `valuepilot_test`:

```text
tie      [('amendments_pending', True), ('amendments_pending', True)]
resolved [(False, 'amendments_pending', True), (True, 'applied', False)]
```

**Minimal fix:** implement group-wide restatement tie recovery analogous to the
originals recovery at `:619-630`.

### P2 — `ACCEPTANCE-DATETIME` is Eastern wall time mislabeled as UTC

**Files:** parser `backend/app/edgar/parsers/primary_doc.py:79-82`; display and
date consumers at `backend/app/services/thirteenf_admin_dashboard.py:2492`,
`backend/app/services/thirteenf_user_api.py:467`, and
`backend/app/services/thirteenf_filing_detail.py:246-250,275-278`.

Both ingest paths are internally consistent because both use the same parser,
but the stored instant is four or five hours wrong. This ticket makes the field
populated and load-bearing, so the mistake now reaches APIs and future
cross-source comparisons.

**Minimal fix:** interpret the raw value in `America/New_York`, convert to UTC
for storage, and explicitly convert back to Eastern before SEC filing-date
rules call `.date()`. Add DST and post-20:00 Eastern tests.

### P2 — The three `accepted_at` writes do not share safe merge semantics

**Files:** `backend/app/services/edgar_ingestion.py:1366-1368`;
`backend/app/services/thirteenf_filing_detail.py:55-56,89,357-359`.

Backfill and metadata application overwrite on any non-NULL difference, while
`ingest_accession_filing_detail` unconditionally writes the parsed value,
including NULL. A temporary document missing the acceptance tag can therefore
erase known load-bearing metadata.

**Minimal fix:** use one merge helper: fill NULL, preserve an existing value,
and route conflicting non-NULL values to review unless an explicit source
replacement/correction workflow authorizes the overwrite.

### P2 — `13F-NT/A` activation and NT-only consumers disagree

**Files:** authority family handling
`backend/app/services/thirteenf_filing_detail.py:486-490,526-570`; consumer
`backend/app/services/thirteenf_holdings_query.py:43-66`.

A parsed `13F-NT/A` restatement can supersede active `13F-NT`, but
`nt_only_manager_ids` recognizes only exact `13F-NT`. The manager then appears
to lack both active HR and active NT and is incorrectly included in the expected
HR denominator.

Standard ingestion currently excludes `13F-NT/A`, so this is latent, but the SEC
explicitly defines `13F-NT/A` as the amendment form for a 13F Notice and the
repository's raw form indexes contain many such filings.

**Minimal fix:** either support the NT family consistently in ingestion,
authority, and consumers, or explicitly reject/document NT/A as out of scope and
guard the authority path.

### P2 — The concurrency test can pass without the advisory lock

**File:** `backend/tests/unit/test_13f_active_filing_authority.py:384-450`.

Session A demotes O and flushes, holding O's row lock. Without the advisory lock,
session B attempts the same demotion and blocks on that row lock, so the one
second “B is blocked” assertion and final convergence assertions can still
pass.

**Minimal fix:** use an already-converged group that causes no UPDATE/flush and
assert B still blocks, or directly assert
`pg_try_advisory_xact_lock(hashtextextended(...))` is false before A commits and
true afterward.

### P2 — Sweep holds all period locks until one final commit

**Files:** `backend/app/services/thirteenf_admin_dashboard.py:3532-3561,3631-3644`.

The sweep accumulates every period lock in one transaction. A reparse holding
the last lock can block the sweep while the sweep blocks unrelated reparses on
all earlier locks. Sorted order prevents a common deadlock class but not
head-of-line blocking or unbounded wait.

**Minimal fix:** commit by group/small batch, or add an observable lock timeout
and retry policy.

### P2 test gap — No real bulk-ingest composition test covers the new path

The 15 new tests call the authority and metadata helpers directly. No test
drives a real stored primary document and infotable through Phase 2 routing,
Phase 2.5 metadata/policy, Phase 3 parsing, and Phase 5 sweep, then verifies the
active holdings query.

**Minimal test:** create stored primary/infotable documents, execute the ingest
job, and assert persisted `accepted_at`, successful parse, correct active filing,
and visibility through `active_hr_holdings_query`. Include a primary-parse
failure case proving a mixed-NULL group does not flip.

## Behavior-preservation audit

- Solo `13F-HR` activation: original pool and `_set_active`,
  `thirteenf_filing_detail.py:581-618`.
- Solo unresolved `13F-HR/A` non-activation: `/A` enters amendments and falls
  through to `none_eligible`, `:486-490,526-585`.
- Parsed RESTATEMENT supersedes original: competing filter and `_set_active`,
  `:526-570`.
- Applied amendment owns the slot in the simple one-amendment steady state:
  `:572-579`; the multi-resolution lifecycle is broken as described above.
- Terminal early return on metadata re-ingest:
  `apply_amendment_policy`, `:380-389`.
- Originals tie deactivates all: `:587-615`.
- Reconcile called on a losing restatement now converges the ranked winner;
  terminal state is preserved and no longer depends on call order.
- Rejected restatements no longer qualify in Rule 1, and HR originals now beat
  NT originals as intended.

## Domain judgments

- A valid parsed RESTATEMENT taking precedence over an admin
  `activate_as_original` NEW_HOLDINGS filing is reasonable: a restatement is the
  full corrected filing, while a new-holdings amendment is supplemental. An
  operator who determines the later restatement is invalid should reject it.
- Ranking back to the later restatement after an operator applies an earlier
  one is also defensible only if the workflow makes rejection of the unwanted
  filing immediate and reliable. The current reject action does not, so the
  product judgment is not safely implemented.
- HR beating NT is correct. When an HR appears, an active NT becoming inactive
  correctly removes the manager from `nt_only_manager_ids`; the HR becomes the
  holdings authority.

## Writer and consumer inventory

Direct active-flag writers outside the authority:

- `thirteenf_filing_detail.py:389,406` — per-filing normalization/no-period
  demotion; the period-bearing path subsequently calls the authority.
- `thirteenf_admin_dashboard.py:470,473` — admin override; unsafe and blocking.
- `thirteenf_controlled_reparse.py:263,270` — validation restore; unsafe without
  a durable authority-recognized state.

Direct status writers outside the authority:

- `thirteenf_filing_detail.py:391,393` — normalization.
- `thirteenf_admin_dashboard.py:474,477,479,481` — admin resolution.

A grep/AST guard that permits only explicit sanctioned writers would materially
protect the “single authority” contract after the above paths are redesigned.

`filings_activated`, `restatements_applied`, and `accepted_at_filled` have no
current UI/quality consumer, so the changed per-group counting basis causes no
confirmed downstream regression.

## Verification performed

- `valuepilot_test`: `pytest -q tests/unit/test_13f_active_filing_authority.py`
  — **15 passed**.
- Rollback-only reproduction confirmed restatement tie-recovery residue.
- Read-only dev audit: **373 filings / 355 manager-period groups**, zero NULL
  competitors, zero active-policy accession-vs-time inversion, zero equal-time
  ties in the actual competition pools.
- No production code or tests were modified as part of this review.

## Authoritative SEC references used

- [SEC Form 13F FAQ](https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f)
  (restatement vs new-holdings amendment semantics; `13F-NT/A` form).
- [SEC Webmaster FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions)
  (accession structure and Eastern acceptance timestamps).
