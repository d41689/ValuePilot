# Review findings remediation

Date: 2026-08-26

Owner: Product / Engineering

Status: complete

## Goal

Validate and remediate the real authorization, point-in-time, append-only, and
historical audit defects reported against the stacked Research Decision Loop
branches, then repeat adversarial review until a complete pass finds no new
valid issue.

## Acceptance criteria

- Ordinary admin coverage APIs expose aggregate operational health only and no
  user-, stock-, case-, or requirement-level private research activity.
- Research and portfolio workspace APIs do not label current projections as a
  historical `as_of` view; unsupported historical requests fail closed.
- Manager representativeness review rows reject database `UPDATE` and `DELETE`;
  corrections append under a new policy version.
- Backdated quant coverage audits exclude post-cutoff PDFs/facts and prices, or
  fail closed where reliable knowledge-time filtering is unavailable.
- Tests prove each boundary with records on both sides of the relevant cutoff
  or authorization boundary.
- Repeated adversarial review finds no remaining valid defect in the changed
  authorization, PIT, immutability, or audit paths.
- Exact canonical Docker CI commands pass at the closing gate.

## Scope

### In

- Admin research-coverage response minimization.
- Research/portfolio workspace historical `as_of` fail-closed behavior.
- Database-enforced append-only manager representativeness reviews.
- Database-enforced insert-only `stock_prices`, so historical audits can rely
  on `created_at` without later in-place mutation.
- Quant audit cutoff propagation for document/fact and price coverage.
- Quant audit PIT reconstruction for 13F filing/parse authority and conservative
  exclusion of rows whose mutable state changed after the cutoff.
- Current-projection guards on coverage evaluation, price-refresh
  re-evaluation, and inbox regeneration found during adversarial review.
- The aggregate-only admin coverage frontend consumer.
- Migrations, schemas, tests, task/backlog records required by those changes.

### Out

- A complete historical research or portfolio reconstruction feature.
- New admin permission products or private per-user support tooling.
- New source-license, metric, valuation, or trading contracts.
- Broad refactors unrelated to the reported boundaries.

## Authoritative references

- `AGENTS.md`
- `docs/architecture/research-decision-support.md`
- `docs/architecture/quant-trading-pit-read-contract.md`
- `docs/architecture/data-layer.md`
- `docs/architecture/metric-facts-is-current.md`
- `docs/13f/oracles_lens_signal_policy.md`
- `docs/prd/value-pilot-prd-v0.1.md`, especially §G.2, §G.9, and §G.10

## Files expected to change

- `backend/app/api/v1/endpoints/coverage.py`
- `backend/app/api/v1/endpoints/research.py`
- `backend/app/services/research_workspace.py`
- `backend/app/services/manual_portfolios.py`
- `backend/app/services/quant_trading/data_audit.py`
- `backend/alembic/versions/20260826120000-representativeness-reviews-append-only.py`
- a successor Alembic migration enforcing immutable `stock_prices`
- `frontend/app/(dashboard)/admin/coverage/page.tsx`
- focused backend/frontend tests for the changed contracts
- this task record and `docs/BACKLOG.md` only if work is deferred

## Test plan

Write failing tests first, then implement. Iterate with focused tests inside the
`api`/`web` containers. At the closing gate run, verbatim:

1. `docker compose up -d --build`
2. `docker compose exec -T api alembic upgrade head`
3. `docker compose exec -T api pytest -q`
4. `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
5. `docker compose exec -T web npm run lint`
6. `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`

## Validated review findings

- VP-124-01: ordinary admin coverage detail disclosure.
- VP-124-02: research workspace false historical `as_of`.
- VP-124-03: portfolio workspace false historical `as_of`.
- VP-123-01: representativeness review lacks database immutability.
- VP-125-01: quant audit ignores cutoff for financial documents/facts/prices.
- VP-RR-125-02: a pre-cutoff price row can be modified after the cutoff because
  `stock_prices` lacks version history or database immutability.

## Decisions and sign-off trail

- All five submitted findings were accepted as real implementation defects.
  Existing Architecture, PRD, PIT, data-layer, and Oracle's Lens policy
  contracts already state the required behavior, so none was weakened or
  duplicated.
- Admin coverage now returns only policy-versioned aggregate counts by state
  and requirement kind. The frontend no longer requests or renders per-user,
  per-stock, or per-requirement data.
- Research and portfolio workspaces reject non-current `as_of` values after
  ownership resolution. Current coverage evaluation and inbox regeneration do
  the same; historical price acquisition no longer relabels the current
  coverage projection with the acquired session date.
- Representativeness review `UPDATE` and `DELETE` operations are rejected by a
  PostgreSQL trigger. Corrections remain append-only under a new policy
  version.
- Quant audit uses one timezone-aware UTC knowledge cutoff for PDFs, facts,
  prices, filings, parse runs, and holdings. It never relies on today's 13F
  active/current flags for historical authority. Rows created or mutably
  updated after the cutoff are conservatively excluded when no event replay is
  available.

### Adversarial review rounds

1. The submitted five findings reproduced as failing authorization, PIT, and
   database-boundary tests.
2. Cross-cutoff testing found a second 13F defect: today's amendment authority
   and current parse could erase or back-project the authority known at T.
   Historical filing and parse selection was reconstructed from knowledge-time
   fields and ambiguous authority now fails closed.
3. Cross-endpoint review found three current-projection bypasses: coverage
   evaluation, inbox regeneration, and post-refresh coverage re-evaluation.
   Each now rejects or removes false historical labeling.
4. Consumer review found the admin page still encoded the removed private
   detail contract. It was replaced with aggregate health only.
5. Mutable-row review found late parsing, fact corrections, filing metadata
   changes, and CUSIP mapping could still back-project knowledge. Tests now
   place creation/update timestamps on both sides of T; later state is
   excluded conservatively.
6. A final search across the changed authorization and historical-read paths
   found no additional valid issue. Focused regression result: 64 backend tests
   and 2 frontend tests passed.
7. The first full-suite run exposed one test-isolation integration issue: an
   advisory-lock concurrency test intentionally commits through independent
   sessions, and its teardown could no longer delete append-only review rows.
   The teardown now disables the trigger only inside its dedicated cleanup
   transaction; the production boundary and normal tests remain protected.
   The cross-file regression for that path passed 37 tests before the full
   closing gate was restarted from step one.
8. Re-review found that a pre-cutoff `stock_prices` row could still be changed
   in place after T. The finding was reproduced with direct SQL `UPDATE` and
   `DELETE`, then closed by migration `20260826130000`: PostgreSQL now rejects
   both operations unconditionally. A repository-wide write-path search found
   only inserts in production code, and the price refresh, canonical reader,
   coverage, and quant audit regression set passed 47 tests.

No issue discovered in these rounds was deferred; `docs/BACKLOG.md` does not
need an entry. Canonical closing-gate results will be recorded below.

### Canonical verification

Run in the required order after the final change:

1. `docker compose up -d --build` — passed.
2. `docker compose exec -T api alembic upgrade head` — passed; database already
   at revision `20260826120000` after the first successful upgrade.
3. `docker compose exec -T api pytest -q` — 1459 passed.
4. `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` — 216 passed.
5. `docker compose exec -T web npm run lint` — passed with no warnings or
   errors.
6. `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` —
   passed. The pre-existing stale Browserslist data notice remains
   non-blocking and was explicitly classified as non-defect by the submitted
   review.

### Re-review VP-RR-125-02

The finding is accepted. `stock_prices.created_at` proves insertion time only;
without an `UPDATE`/`DELETE` prohibition, the historical audit cannot prove
that the row still contains the state known at T. The Watchlist PRD already
defines the write side as insert-only, so the implementation will enforce that
existing contract at the database boundary rather than add a second versioning
model. Both mutation boundary tests failed before the migration and passed
after it.

Follow-up canonical closing gate, restarted from step one after the final
change:

1. `docker compose up -d --build` — passed.
2. `docker compose exec -T api alembic upgrade head` — passed at revision
   `20260826130000`.
3. `docker compose exec -T api pytest -q` — 1461 passed.
4. `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` — 216 passed.
5. `docker compose exec -T web npm run lint` — passed with no warnings or
   errors.
6. `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` —
   passed; only the already-classified non-blocking Browserslist notice was
   emitted.
