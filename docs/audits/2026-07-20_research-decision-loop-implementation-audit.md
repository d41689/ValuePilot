# Research Decision Loop implementation audit

Date: 2026-07-20  
Branch: `codex/research-decision-loop-roadmap`  
Roadmap: `docs/plans/research_decision_loop_product_roadmap.md`  
Status: complete; canonical gate and post-build browser acceptance passed

## Audit standard

This audit treats a requirement as complete only when it has current production
code plus at least one of: PostgreSQL behavior tests, authorization/adversarial
tests, migration round-trip evidence, source-contract tests, or rendered browser
evidence. A configured external provider, licensed proprietary source, production
deployment, real Slack/email send, commit, push, or PR is not inferred.

## Requirement traceability

| Roadmap requirement | Implementation evidence | Verification evidence | Result |
| --- | --- | --- | --- |
| Phase 0: truthful 13F/value semantics | `oracles_lens_signal_policy.md`; versioned manager reviews; canonical valuation service; corrected Value Line percentage normalization | `test_13f_manager_representativeness.py`, `test_13f_mvp4_distinctive_consensus.py`, `test_valuation_product_source_guard.py`, parser/mapping tests | Pass |
| Phase 0: complete quarterly 13F chain | active-filing authority, real parse-run holdings, quality, ownership changes and Lens score bodies | real stored-SEC two-quarter/three-manager chain in `test_13f_job_scheduler.py`; zero-DB/Dataroma audits | Pass |
| Phase 1: explainable targeted coverage | `research_coverage_requirements`, policy versions, Watchlist/open-case/top-Lens prioritization, user/admin APIs | `test_research_coverage.py`; `/admin/coverage` and workspace browser states | Pass |
| Phase 1: canonical price/currency/freshness | `market_data_service.py`, price currency migration, market-calendar freshness, fail-closed production provider | `test_market_data_freshness_policy.py`, `test_market_data_refresh.py`, `test_market_data_product_source_guard.py` | Pass |
| Phase 2: cases/origins/revisions/events | one-active-case partial index, state CHECKs, append-only origins/events, optimistic revision save, evidence authorization/redaction | `test_research_cases.py`; migration constraint assertions; browser create/save/reopen flow | Pass |
| Phase 2: qualified decision metric | explicit `decision_action=draft|decision|review`; immutable metric event and per-user weekly endpoint | `test_qualified_decision_metric_counts_transitions_and_explicit_reviews_not_drafts` | Pass |
| Phase 2: Research Inbox | durable ranked action projection/events, explainable reasons, bounded snooze/dismiss, home ticker search | `test_research_inbox.py`, `researchDecisionLoop.test.js`; desktop/narrow browser acceptance | Pass |
| Phase 2: every discovery surface opens one case | canonical `OpenResearchCaseButton` on Watchlist, Lens, Inbox, manager, screener and stock summary | frontend source contract plus browser duplicate-action observation | Pass |
| Phase 3: unified research workspace | current data, provenance, Value Line, Piotroski, 13F changes/streaks/caveats, valuation separation, thesis/risk/evidence, revision history | workspace service tests through case/valuation/13F suites; browser missing-data and saved-revision states | Pass |
| Phase 3: historical decision integrity | recorded stock identity and full immutable snapshot; source-unavailable rendering; audited redaction exception | `test_research_cases.py`, append-only DB triggers and migration rehearsal | Pass |
| Phase 4: follows/logical notifications | user-owned follows, immutable logical source version, corrections, in-app read/dismiss projection | `test_research_notifications.py`, manager workbench source/browser evidence | Pass |
| Phase 4: external destinations | exact Slack URL policy, encrypted/versioned secrets, verified TLS email, explicit consent/test, no secret serialization | notification service/API tests and frontend source guard | Pass |
| Phase 4: frequency/quiet/cooldown | immediate outbox plus timezone-aware daily/weekly catch-up digests; DST quiet hours and cooldown | daily/weekly digest, quiet-hours and delivery tests in `test_research_notifications.py` | Pass |
| Phase 4: delivery correctness/visibility | committed lease before send, typed transient retry, no blind resend after ambiguous outcome, user delivery audit, aggregate admin operations, audited key rotation | retry/expired-lease/exception/rotation/API privacy tests; notification browser loading/empty/error/admin-denial states | Pass |
| Phase 4: independent operation | research scheduler runs every 15 minutes independently from EDGAR and skips unconfigured rotation cleanly | `test_scheduler_alignment.py` | Pass |
| Phase 5: manual portfolio/journal | long-only Decimal projection, currency, case/revision links, optimistic version, append-only open/resize/close/review events and post-mortem | `test_manual_portfolios.py`, `manualPortfolios.test.js` | Pass |
| Phase 5: no broker/tax/FX claims | matching-currency-only current value; typed unavailable/mismatch; explicit manual-copy boundary | portfolio service/API/UI tests and copy guard | Pass |
| Phase 6 allowed obligation | source/license ADR: EDGAR authorized; Value Line upload-only; production EOD requires configured commercial provider | `coverage-source-policy.md`; fail-closed provider tests | Pass by recorded licensing block |
| Authorization/privacy | all new user resources derive identity from auth; non-disclosing cross-user 404; admin endpoints aggregate only | case/inbox/coverage/notification/portfolio/account-erasure authorization tests | Pass |
| Abuse/resource bounds | durable operation limits and 10 MiB PDF cap before ingestion | `test_api_abuse_limits.py` | Pass |
| Account erasure | password-confirmed one-transaction revocation, redaction/tombstone, pseudonymization and minimal audit retention | `test_account_erasure.py`; privacy UI source/browser acceptance | Pass |
| Migration safety | ten additive migrations with downgrades and explicit constraints/indexes | isolated PostgreSQL legacy -> head -> base -> head representative fixture test | Pass |
| Developer runtime integrity | dev chunks use `.next-dev`; production build keeps `.next` for standalone deploy | `buildIsolation.test.js`; browser smoke after build | Pass |

## Implementation adversarial review log

The implementation was repeatedly attacked across financial semantics, user
authorization, concurrency, delivery failure modes, migration reversibility,
runtime UX and operations. Valid defects found and fixed were:

1. Oracle's Lens/stock valuation reads could cross a user boundary; all product
   reads now go through the authenticated canonical valuation service and a
   static source guard.
2. A valid empty SEC daily index was reported as an error/no-op ambiguously; it
   now distinguishes successful no-op, expected no-data and fetch failure.
3. An explicit destination test had no subscription and crashed quiet-hour
   evaluation; explicit tests now have a valid no-subscription path.
4. Notification leases were not durable before provider side effects, and an
   expired lease could blindly resend a message. Leases/attempt events commit
   first; ambiguous outcomes stop visibly rather than risk duplicates.
5. Destination-key rotation had no durable operational record; it now has a
   bounded advisory-locked `job_runs` audit and fail-closed unreadable state.
6. Delivery failures were not visible to the user/operator; scoped delivery
   audit and privacy-safe aggregate operations surfaces were added.
7. Account erasure and expensive-operation abuse controls existed only as
   roadmap prose; authenticated erasure, durable per-user limits and upload caps
   were implemented and tested.
8. The research scheduler was coupled conceptually to EDGAR; it is now a
   separately enabled 15-minute scheduler.
9. A real delivery test depended on wall-clock time and became flaky; the test
   now fixes the enqueue clock.
10. Production `next build` and the long-running dev server shared `.next`,
    corrupting dev chunks after the closing gate. Dev uses an isolated
    `.next-dev` volume while production deployment remains on `.next`.
11. Daily/weekly external frequency settings were accepted but never delivered.
    The scheduler now materializes idempotent, catch-up, local-time digests;
    in-app frequency is explicitly immediate and invalid digest input is
    rejected server-side.
12. The legacy filing-season summary did not enter the new user-scoped logical
    notification pipeline. It now preserves the legacy record and emits one
    idempotent logical notification only when the user follows a relevant
    manager, owns a relevant Watchlist item, or has a relevant open case.
13. A changed valuation or threshold policy could be interpreted as a market
    crossing. Alert state now versions the valuation fact and policy boundaries,
    reinitializes without an alert, and requires a later fresh close for a real
    crossing.
14. Multiple destination rows could claim incompatible intrinsic-value
    thresholds despite sharing one user/stock crossing state. Those policy
    fields are now synchronized under an advisory lock; channel scheduling
    remains destination-specific.
15. The scheduler wrote a successful secret-rotation job on every interval even
    when no destination needed rotation. It now records rotation work only when
    ciphertext is outdated or configuration is invalid and otherwise reports a
    clean skip.
16. Editing a valuation on a monitoring case kept the old decision active and
    could alert from an unreviewed new value. Watchlist and saved-DCF valuation
    changes now reopen the case as researching, clear the current decision and
    review date, preserve the prior immutable revision, and pause alerts.
17. Re-entering monitoring with the same valuation could reuse pre-pause alert
    state and interpret the first close as a crossing. Alert state now also binds
    to the monitoring research revision; every newly confirmed decision
    initializes a fresh boundary before a later close may trigger.
18. Concurrent scheduler replicas could both observe no price-alert state and
    race the unique insert. Alert evaluation now serializes each user/stock
    projection with a transaction advisory lock before its first read/create.
19. The complete suite exposed that a real-commit manager-seed concurrency test
    deleted managers without first deleting newly introduced representativeness
    reviews. Its failed cleanup contaminated the ephemeral schema and caused a
    broad cascade; dependency-ordered cleanup now restores test isolation.
20. Stock-price evidence validation read an explicitly cited observation from a
    business service and tripped the canonical market-data source guard. The
    evidence lookup now lives inside the sanctioned market-data service, keeping
    all direct price-table access behind one boundary without weakening the
    guard.

After remediation, the same review matrix found no additional reproducible
correctness, authorization, financial-semantics, concurrency, privacy,
operational or workflow defect in roadmap scope.

## Browser evidence

Acceptance used a synthetic local user and the in-app browser against the
Docker dev stack. No real external message was sent and account erasure was not
executed because those destructive/outward actions were not separately
authorized.

- Desktop Research Inbox loaded a ranked top-30 candidate set with reasons and
  ticker search.
- Creating the first MSFT case navigated to `/research/cases/1`; reopening from
  Home showed `Open case` rather than a duplicate create action.
- The workspace rendered missing price/fundamental/value states, 13F delay and
  source caveats; saving evidence produced immutable Revision 1 and a success
  confirmation.
- Notification center rendered loading, empty, delivery-audit and forced API
  error states without exposing secrets.
- A non-admin direct visit to `/admin/notifications` redirected to `/home`.
- At 390 x 844, Inbox/workspace/notifications/privacy had no horizontal
  overflow, retained mobile navigation and preserved the key action hierarchy.
- Privacy settings kept the irreversible erase action disabled until exact
  password and phrase confirmation.

## External-state boundary

The implementation is complete with deterministic adapters and fail-closed
readiness. Production EOD credentials, notification encryption keys, SMTP,
Slack destinations, authorized proprietary Value Line acquisition, production
deployment and real sends remain operator/user configuration—not fabricated
test success. Their absence is visible in admin readiness and coverage states.

## Closing evidence

Targeted closing regression passed 64 notification, filing-season, scheduler,
research-case, valuation and migration tests. The isolated legacy -> head ->
base -> head migration rehearsal passed.

The final canonical sequence was restarted after the last code change and
passed in order:

- `docker compose up -d --build` — images rebuilt and services recreated;
- `docker compose exec -T api alembic upgrade head` — clean at head;
- `docker compose exec -T api pytest -q` — 1433 passed;
- `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` — 216 passed;
- `docker compose exec -T web npm run lint` — no warnings or errors;
- `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` —
  compiled, type-checked, and generated all 27 App Router pages.

Post-build browser smoke proved the running `.next-dev` application was not
corrupted by the production `.next` build. Research Inbox, MSFT Revision 1,
13F-delay caveats, notification delivery audit, and in-app immediate frequency
rendered without runtime/chunk errors; the 1280px viewport had no horizontal
overflow. Earlier desktop/narrow/error/permission/duplicate-state acceptance
remains recorded above. `git diff --check` passed after final documentation.
