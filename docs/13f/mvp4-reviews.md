第一份review：

Tech Lead Cross-Task Review — MVP4 (13F Oracle's Lens)
  
  Verdict: APPROVE-WITH-FIXES

  Two pre-merge actions are required. Neither touches the critical path of existing tests, but both must land before MVP5 can safely introduce a v1.1 score or add a new scoring
  service.

  ---
  Concern-by-Concern Findings

  ---
  1. score_version Evolution Path

  Finding: documentation debt — pre-merge fix required.

  The compute side is clean. The upsert key (stock_id, report_quarter, score_version) and the JobRun lock key oracles_lens_score:{quarter}:{score_version} both include the version,
  so a shadow v1.1 compute run genuinely can proceed alongside v1.0 without conflict.

  The read side does not match that promise. The HTTP endpoint /api/v1/oracles-lens (oracles_lens.py:14–47) has no score_version parameter — it always delegates to
  build_oracles_lens_dashboard → _apply_persisted_scores(score_version=SCORE_VERSION). Similarly, build_oracles_lens_response defaults to SCORE_VERSION and the admin endpoint for
  the signal-weighted read helper does not expose the version. So the scenario described in constants.py:23 — "a v1.0 production run and a v1.1 shadow run can proceed concurrently"
  — is true for compute but not for reads. Bumping SCORE_VERSION to "v1.1" immediately switches the production read path with no rollback option short of a redeploy.

  Pre-merge action: Annotate constants.py (near line 24) with an explicit note: "Bumping this constant is a one-way production switch — all read paths follow the constant; 
  shadow-computing v1.1 while serving v1.0 is not supported without exposing score_version as an API parameter." If shadow-compute capability is desired before MVP5, add an optional
   score_version query param on the dashboard endpoint (admin-only, no frontend exposure). The comment as-written will mislead whoever ships v1.1.

  ---
  2. ORM Upsert vs. IntegrityError Translator Consistency

  Finding: intentional and correctly differentiated — no action required.

  The two patterns serve semantically distinct purposes:

  - ORM upsert (INSERT ... ON CONFLICT DO UPDATE) is used for score writes in _upsert_signal. Score recompute is idempotent by definition: callers always want the latest result
  overwriting the old one; an IntegrityError would carry no useful information.
  - IntegrityError → typed error is used for JobRun lock-key races in enqueue_signal_weighted_backfill:863–870. Here the conflict means "another job is already active," which is a
  domain event callers must distinguish from success.

  The MVP4 enqueue pattern is explicitly documented as "matches MVP3-05 / MVP3-07" in signal_weighted_score.py:17–21, so this is not a silent re-litigation. The inconsistency is
  intentional and correct.

  Follow-up (not blocking): A single architectural note in CLAUDE.md or a module docstring explaining the rule — "upsert for idempotent writes; IntegrityError translation for
  exclusive-lock guards on JobRun" — would prevent the next contributor from re-raising this question.

  ---
  3. _HolderContribution Coupling Debt
  
  Finding: coupling is benign by design — no action required.

  The concern about "modifying all three call sites" when adding a component is slightly misstated. _HolderContribution has exactly one construction site: _contributions_for_stock
  in signal_weighted_score.py:512–527. The three consumers (signal-weighted, conviction, distinctive) are all read-only. If a future scoring component needs a new field:

  - Add the field to the frozen dataclass (one place in signal_weighted_score.py).
  - Populate it in _contributions_for_stock (one place).
  - Consume it in the new module only; existing consumers are untouched unless they also need it.

  The TYPE_CHECKING-only imports in conviction_score.py:33 and distinctive_consensus.py:41 correctly avoid the circular import. The holding_streak_quarters and add_intensity fields
  on the dataclass (signal_weighted_score.py:247–248) exist precisely because MVP4-04 needed them without re-querying the DB — this is the documented "passenger" pattern.

  The genuine long-term risk is a bloated shared struct if scoring grows to 10+ algorithms. At three it's the right trade-off. Flag for V2 re-evaluation if a fourth scoring
  algorithm needs more than two new fields on the struct.

  ---
  4. Conftest Savepoint Hardening Reality Check

  Finding: correctly exercised — no action required.

  MVP4-10's join_transaction_mode="create_savepoint" recipe is genuinely exercised by MVP4-08, not bypassed.

  - test_dry_run_backfill_stamps_is_dry_run_true_and_source_job_id calls execute_historical_backfill, which internally calls session.commit() multiple times via _run_quarter →
  _finalize_run. Under the savepoint fixture, each commit() operates on a SAVEPOINT, not the outer connection transaction. This is exactly the warning class MVP4-10 fixed.
  - The harder case — IntegrityError → session.rollback() → re-raise — is exercised by test_enqueue_translates_unique_index_race in test_13f_mvp3_historical_backfill.py:170–183.
  That test monkeypatches the pre-check to None, forces the partial-index collision, and confirms the typed error. The rollback inside the service unwinds to the savepoint, not the
  outer transaction. The 0-warning baseline confirms this works end-to-end.

  MVP4-08 does not introduce a new IntegrityError-prone write path on QualityReport13F (the model has no unique constraint that dry-run writes could collide against), so there is no
   new stress needed there.

  ---
  5. Dashboard Formula Divergence Backlog
  
  Finding: correctly framed as an escape hatch — follow-up only.

  The divergence is documented: dashboard.py:602 uses min(holding.position_weight * 4, 1.0) as the position base (scaling a 5% position to 0.20), while MVP4-03 uses the raw
  portfolio_weight decimal (a 5% position contributes 0.05 base). These produce scores on incompatible numeric scales. The frontend in oraclesLens.js:77–82 defaults to
  persisted=true, so the legacy formula is dormant in production.

  One genuine issue: The /api/v1/oracles-lens endpoint at oracles_lens.py:23–31 defaults use_persisted_scores=False. The frontend always overrides this, but a developer calling the
  API directly (e.g., curl, Postman, or a future API consumer) gets the legacy formula by default. The API default is misaligned with the production intent.

  Follow-up (MVP5): Flip the API default to True. When the legacy path is retired, release notes should explicitly state the score-magnitude change — the *4 scaling means
  pre-migration scores were numerically larger than post-migration persisted scores for the same stock, and users must not compare historical rankings across the cutover.

  ---
  6. Rule_code Constants Module Reuse

  Finding: partially centralized — pre-merge fix required.

  thirteenf_quality_codes.py correctly owns the three quality_findings_13f.rule_code strings, and test_writer_modules_use_canonical_module_as_source_of_truth verifies the three
  historical producers (edgar_quality, corporate_action_mapping, historical_backfill) all bind to the canonical module.

  The gap is in the scoring services. base_primitives.py:60 declares:

  HISTORICAL_BACKFILL_NEEDS_VALIDATION_CAVEAT = "HISTORICAL_BACKFILL_NEEDS_VALIDATION"

  as an independent local string, even though the same module already imports the canonical constant three lines earlier (line 38: _BACKFILL_FINDING_RULE_CODE). It uses the import
  for finding DB lookups but a re-declared literal for caveat emission. Similarly, caution_flags.py:44 redeclares CAVEAT_HISTORICAL_BACKFILL_NEEDS_VALIDATION = 
  "HISTORICAL_BACKFILL_NEEDS_VALIDATION" without importing from thirteenf_quality_codes.

  The risk: renaming the constant in thirteenf_quality_codes (which the module says not to do, but still) would break finding lookups loudly via ImportError but would silently leave
   the caveat emission emitting the old string — a DB/UI divergence that tests would not catch because the MVP4-09 sentinel test only covers the three historical writers, not the
  scoring services.

  Pre-merge actions:

  a) In base_primitives.py, replace the local literal:
  # was:
  HISTORICAL_BACKFILL_NEEDS_VALIDATION_CAVEAT = "HISTORICAL_BACKFILL_NEEDS_VALIDATION"
  # fix:
  from app.services.thirteenf_quality_codes import HISTORICAL_BACKFILL_NEEDS_VALIDATION as HISTORICAL_BACKFILL_NEEDS_VALIDATION_CAVEAT
  (The existing _BACKFILL_FINDING_RULE_CODE alias can stay — it's a readability alias for DB lookup context, which is fine per the module's "local aliases permitted" rule.)

  b) In caution_flags.py, either import from thirteenf_quality_codes or add caution_flags to the MVP4-09 sentinel test's test_writer_modules_use_canonical_module_as_source_of_truth
  to pin the value at the same string.

  c) Extend the MVP4-09 test to cover base_primitives.HISTORICAL_BACKFILL_NEEDS_VALIDATION_CAVEAT after the fix.

  ---
  7. is_dry_run Filter Coverage

  Finding: complete — no action required.

  All consumers of QualityReport13F are correctly filtered:

  ┌───────────────────────────────────────────────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────────┐
  │                                     Consumer                                      │                                  Filter?                                  │
  ├───────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ build_quality_reports (admin list endpoint)                                       │ ✓ is_dry_run.is_(False) default                                           │
  ├───────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ _latest_quality_report (quarter detail, readiness rollup, quality-check endpoint) │ ✓ always filtered                                                         │
  ├───────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ get_quality_report_for_quarter → calls _latest_quality_report                     │ ✓                                                                         │
  ├───────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ edgar_quality.persist_quality_report — writes real runs                           │ ✓ is_dry_run defaults to False (server_default)                           │
  ├───────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ thirteenf_corporate_action_mapping quality report write                           │ ✓ is_dry_run defaults to False — corporate action runs are never dry-runs │
  ├───────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ Readiness service                                                                 │ n/a — reads QualityFinding13F directly, not QualityReport13F              │
  └───────────────────────────────────────────────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────┘

  The migration's server_default=false() means rows written before MVP4-08 are correctly treated as real runs. No additional filter sites needed.

  ---
  8. Test-Suite Shape

  Finding: consistent — no action required.

  All nine DB-touching MVP4 test files follow the _CIK_SEQ = count(N) / _ACC_SEQ = count(M) pattern with non-overlapping starting values (9990500000, 9991100000, 9992200000,
  9993300000, 9994400000, 9995500000, 9996600000, 9997700000, 9941000000). No cross-file PK collisions are possible.

  MVP4-08 (quality_report_source_linkage) omits _ACC_SEQ and _STOCK_SEQ — this is correct; it uses mock accession strings in the discovery callback and never creates stock rows
  directly. MVP4-09 (quality_rule_codes) has zero DB interaction and no counters — also correct. These are not new fixture styles; they're the correct fixture tier for their test
  scope.

  No "choose between two patterns" ambiguity exists for future contributors.

  ---
  Summary

  APPROVE-WITH-FIXES

  Pre-merge (must land before MVP5 opens):

  1. constants.py:23 — clarify the version-bump contract. The comment promising concurrent v1.0/v1.1 read+compute is not supported by the read path. Add a doc note stating version
  bumps are coordinated deploys, or expose score_version as an optional admin query param on the read endpoint.
  2. base_primitives.py:60 + caution_flags.py:44 — eliminate the string re-declaration. Import HISTORICAL_BACKFILL_NEEDS_VALIDATION from thirteenf_quality_codes for caveat emission,
   matching what the same file already does for finding lookups. Extend the MVP4-09 sentinel test to cover base_primitives.

  MVP5 backlog (file as follow-ups):

  3. Flip /api/v1/oracles-lens default for use_persisted_scores to True and retire the legacy in-memory formula path once persisted scores cover all active quarters.
  4. Add score_version to admin read endpoints if shadow-compute capability is wanted before the next version bump.
  5. Class B caution flag suppression (whole-holder exclusion for amendments, confidential treatment, NT/combination reports) — already documented in MVP4-03 task log.
  6. Architecture note (CLAUDE.md or module docstring) explaining the two-pattern rule: ORM upsert for idempotent rewrites, IntegrityError translation for exclusive-lock guards.

  第二份review：
  Tech Lead Cross-Task Review: 13F Automation MVP 4
Date: 2026-05-12 Milestone: MVP 4 (Oracle's Lens Base Scoring & Consensus) Verdict: APPROVE

The MVP 4 increment correctly implements the complex domain rules for signal-weighted consensus, conviction, and distinctive scoring, and integrates cleanly into the admin and dashboard surfaces.

Below is the assessment of the 8 specific cross-cutting concerns raised for review.

1. score_version Evolution Path
The evolution path is extremely clean. The unique constraint uq_oracles_lens_signals_stock_quarter_version securely isolates multiple versions for the same stock/quarter. In build_unknown_manager_priority, if we ship v1.1 before backfilling it, _latest_scored_quarter simply returns None, allowing the admin UI to gracefully degrade to "no persisted scores yet" instead of stranding the queue or crashing. No architectural changes are needed before bumping to v1.1.

2. ORM Upsert vs. IntegrityError Translator Consistency
The inconsistency is intentional and architecturally correct.

JobRuns (IntegrityError): Job enqueueing is a mutual exclusion lock. If two identical requests hit the system, the loser must get an IntegrityError so it can abort ("I am already running"). An upsert here would destructively steal locks.
Oracle's Lens Signals (ORM Upsert): Scoring is purely idempotent data persistence. Two identical jobs calculating AAPL's score at the exact same time yield mathematically identical rows. An upsert ensures "last writer wins" with no error noise.
3. _HolderContribution Shared Dataclass Coupling
Currently, signal_weighted_score.py loads holding_streak_quarters and add_intensity natively into _HolderContribution strictly so the passenger services (MVP4-04 Conviction and MVP4-06 Distinctive) don't have to re-query the database. This is a deliberate "data bus" optimization to ensure 1 DB pass per stock. It is the right performance trade-off for 13F data volumes, but introduces coupling debt. Follow-up: In MVP 5, extract the database loading step into a dedicated score_data_loader.py module to decouple the scoring formulas from the data aggregation.

4. Conftest Savepoint Hardening Reality Check
The join_transaction_mode="create_savepoint" implementation is working flawlessly. It does not "dodge" the warning class; rather, it resolves the underlying SQLAlchemy 2.0 transaction abort issue. By emitting a native SAVEPOINT around the test block, catching the IntegrityError (like in test_enqueue_translates_unique_index_race) simply rolls back the savepoint without poisoning the global test transaction, eliminating the SAWarning safely.

5. Dashboard Formula Divergence
The dashboard's in-memory base (min(weight*4, 1.0)) differs from the raw portfolio_weight persisted by MVP4-03. This technical debt is well-framed. The use_persisted_scores=True debug flag is a smart escape hatch to allow the frontend to migrate to the canonical persisted scores safely. Follow-up: Remove the legacy in-memory formula in MVP 5 once the persisted scores are fully validated in production.

6. Rule_code Constants Module Reuse
The caution flags in MVP4-05 did not route through thirteenf_quality_codes.py. However, this is perfectly compliant: the docstring of thirteenf_quality_codes.py explicitly scopes itself to QualityFinding13F.rule_code constants, expressly declaring that score-level caveats (e.g. PARTIAL_COVERAGE) are out of scope and should remain local to the emitting service. The literal strings floating in caution_flags.py are therefore correct per the module's contract.

7. is_dry_run Filter Coverage
The is_dry_run.is_(False) filters added to build_quality_reports and _latest_quality_report provide complete coverage. I verified that the readiness service does not query the QualityReport13F table at all (it derives readiness directly from active Filing13F records), so there are no hidden consumers improperly treating dry-run rows as production health signals.

8. Test-Suite Shape
MVP4-07b and MVP4-08 correctly adhere to the established, isolated test patterns. Files like test_13f_mvp4_unknown_manager_priority.py utilize the module-local _CIK_SEQ / _ACC_SEQ iterators alongside dedicated _manager() and _holding() database fixture helpers. They did not introduce competing test harnesses, ensuring future contributors do not have to "choose" between fixture styles.

Action Plan
Pre-Merge Action Items (Must Land Before MVP5)
None. The branch is green, constraints are respected, and test isolation is clean. Clear for merge.
Follow-Up List (File to MVP5 Backlog)
Tech Debt: Extract the _HolderContribution data-loading logic from signal_weighted_score.py into an isolated oracles_lens_data_bus.py to decouple data fetching from scoring math.
Tech Debt: Once frontend validation completes via ?persisted=1, delete the legacy in-memory scoring formula from dashboard.py and promote use_persisted_scores=True to the default path.
Feature: Implement the Class B "whole-holder exclusion" caveat suppressions (currently only Class A delta-only suppressions are implemented).

第三份review：
Product Owner MVP4 Milestone Closure Review
  
  Date: 2026-05-12

  ---
  1. D1–D6 Closure — Row-by-Row Verdict

  D1 — Oracle's Lens V1 scope (signal-weighted + conviction + caution + distinctive only)
  CONFIRMED CLOSED — with one documentation correction needed.

  The four score metrics are real: signal_weighted_consensus_score, conviction_score, caution_flag_codes, distinctive_consensus_score. No Value Line plumbing, no out-of-scope
  metrics. However, the verification doc's exact claim — "four score columns... are the only persisted metrics" — is technically inaccurate. The migration also created add_intensity
   and holding_streak_quarters as reserved columns. Neither is populated by _upsert_signal (confirmed: neither field appears in the INSERT values in
  signal_weighted_score.py:625–638). They're correctly nulled placeholders for future backfill, not scope leakage — but calling them absent when they exist in the schema is sloppy.
  The D1 closure document should be annotated: "add_intensity and holding_streak_quarters are reserved-null schema columns; they are not populated by V1 scoring." Fix the doc before
   archiving the verification file.

  D2 — No pre-2023 production backfill
  CONFIRMED CLOSED — clean.

  The DEFAULT_BACKFILL_START_QUARTER guard, the 400 response on pre-2023 without dry_run=True, and the MVP4-08 is_dry_run stamp are all in place and tested.
  PRE_2023_PRE_HISTORY_UNAVAILABLE is emitted correctly by compute_holding_streak and compute_add_intensity when the lookback hits the 2023-Q1 floor. The D2 SME remediation is fully
   delivered.

  D3 — V1 metric surface + distinctive visible-but-off
  CONFIRMED CLOSED — UX matches the gate exactly.

  Verified directly in the shipped code. page.tsx:157 initializes sort: 'signal_weighted_consensus' as the default state. Distinctive consensus appears as a <SelectItem> in the sort
   dropdown at line 525, selectable by the user. The reset button at line 540 returns to signal_weighted_consensus. This is exactly the PO D3 clarification:
  "visible-but-off-by-default sort option in the UI dropdown, not hidden behind an admin toggle." MVP4-07a did not make it default-on.

  The five SME caveat-propagation rules (a–e) are confirmed live: Class A delta-only suppression in compute_position_signal_weight, determine_score_confidence worst-tier logic, and
  the per-holder amendment caveat injection in _contributions_for_stock:488–495.

  D4 — Value Line overlay deferred
  CONFIRMED CLOSED — clean.

  No Value Line schema, service, or frontend code anywhere in the MVP4 diff. The existing value_line_coverage_count field on the dashboard payload is pre-MVP4 and untouched.

  D5 — Config module + separate component-audit table + score_version + manager_type taxonomy
  CONFIRMED CLOSED — all four sub-items verified.

  - app/services/oracles_lens/constants.py is a typed Python module with SCORE_VERSION: str = "v1.0" and MANAGER_SIGNAL_WEIGHTS as named Decimal constants. No JSON, no TOML, no DB
  override table — exactly the TL revision.
  - oracles_lens_score_components exists as a separate table (not a JSONB blob), keyed on (score_id, component_name, manager_id).
  - score_version is VARCHAR(20) on the score row from day one.
  - MVP4-11 reconciled the three-surface taxonomy mismatch to one canonical 8-value vocabulary, and its D3 decision (multi_strategy = 0.60 conservative fallback) is written
  explicitly in constants with a comment.

  D6 — Three carryover backlog tickets + IntegrityError as MVP4-01 design note
  CONFIRMED CLOSED — all four items resolved.

  MVP4-08 (dry-run source linkage), MVP4-09 (rule_code constants), MVP4-10 (conftest savepoint hardening) all shipped. The IntegrityError strategy was decided in MVP4-01: ORM upsert
   for score writes, IntegrityError translator for JobRun lock-key races — both are documented in signal_weighted_score.py:16–21 explicitly referencing MVP3-05/07 parity.

  ---
  2. Scope-Freeze Tally — Confirmed Zero, With One Precision Note
  
  All five deferred items have explicit anchor points in task files, not vague "we'll get to it" language. Tally is real:

  ┌──────────────────────────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                Deferred item                 │                                                         Anchor                                                         │
  ├──────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Class B caveat exclusion                     │ mvp4-03-signal-weighted-score.md §"Class B Caveat Backlog" lines 302–333, with six specific Class B members enumerated │
  ├──────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Behavior-derived manager_type admin override │ mvp4-07b scope-out + mvp4-11 D5 "V1-only caveat" (V2 re-tuning using behavior evidence)                                │
  ├──────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Formula reconciliation                       │ mvp4-03b scope-out + mvp4-07a scope-out both name it explicitly                                                        │
  ├──────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ NT page-level banner                         │ mvp4-05 scope-out lines 126–128                                                                                        │
  ├──────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Pre-2023 production backfill                 │ D2 holds; no execution started                                                                                         │
  └──────────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  The precision note: the MVP4-03 backlog says Class B should land "before any production launch that exposes the signal-weighted score externally." This is not vague — it is a
  conditional trigger. The tally is zero precisely because MVP4 is an internal admin milestone, not an external launch. But this means the five deferred items are not all equal;
  some are MVP5 candidates and some are launch-gate candidates. See item 7 below.

  ---
  3. ?persisted=0 Debug Flag Lifecycle — Decision Required Now
  
  The phrase "one release cycle" in MVP4-07a is undefined and must be closed here, not carried as-is into MVP5.

  Decision: The flag retires at MVP5 close, contingent on two explicit conditions both being met:

  1. Formula reconciliation is complete: the legacy _position_signal_weight in dashboard.py (which uses min(weight*4, 1.0)) is either retired or aligned with the persisted MVP4-03
  formula. The two formulas produce scores on different numeric scales (the *4 multiplier means a manager with an 8% position sees a 0.32 base in legacy vs 0.08 in persisted). Users
   should not be able to flip the flag and see a 4× score change without a label.
  2. One full scoring cycle observed without discrepancy: "discrepancy" is defined as any stock that appears in the top 10 under persisted mode but falls below position 20 under
  legacy mode, or vice versa. This is testable — a side-by-side comparison job can be run against the current active quarter before MVP5 closes.

  On the observability path: the MVP4-07b admin priority queue is the wrong surface for this. It shows which unknown-type managers drag score confidence, not whether the two scoring
   formulas produce coherent rankings. What's needed for flag retirement is a lightweight comparison utility — not a new product feature, just a one-off script or admin endpoint
  that computes both paths for the latest scored quarter and reports ranking divergences. This should be the first deliverable of MVP5's formula reconciliation task, not an
  afterthought.

  Who confirms "no discrepancy observed": the product owner reviews the comparison report and signs off. This is not delegatable to an automated pass/fail because the threshold for
  "material discrepancy" is a product judgment, not a technical one.

  ---
  4. Class A vs Class B — Right Decision, Scope Confirmed
  
  The Class A design is correct and stays. The PO rationale is sound: a manager who genuinely holds AAPL at 8.2% portfolio weight in their top 10 with a 6-quarter streak is a real
  snapshot signal even when the cross-quarter delta is stale. Zeroing the whole contribution would discard valid evidence. The snapshot-only contribution plus a low_confidence label
   is the honest representation.

  Class B in MVP5: yes, but narrow.

  Not all six Class B members carry equal risk. Rank by actual harm:

  - High risk, include in MVP5: pending amendments (AMENDMENTS_PENDING) and failed amendments (AMENDMENT_FAILED). A holder with a pending amendment may have filed a position that
  will change materially. Their portfolio_weight base is potentially wrong, not just their delta. This is the scenario where the Class A design makes a factually incorrect snapshot
  claim.
  - Medium risk, include in MVP5: unresolved CUSIP mapping. A holding with no stock_id link (cusip_mapping_status != "linked") cannot contribute a meaningful position_signal_weight
  because the stock identity is unknown. These should already be excluded by the eligibility filter (filter(Holding13F.cusip_mapping_status == "linked")), so this may already be
  handled. Verify before scoping.
  - Lower risk, defer to V2: 13F-NT (no direct holdings — these managers don't appear in the direct-holdings query anyway), combination report weight incompleteness (already handled
   by the PARTIAL_COVERAGE caveat demoting confidence), and confidential treatment omissions (already caveat-flagged; the holder's known holdings still provide evidence).

  MVP5 Class B scope: amendments only, with a fallback to "exclude from score and count separately in response." This is a two-week task, not a two-sprint track.

  ---
  5. multi_strategy=unknown=0.60 V1 Fallback — Still Correct

  The conservative fallback is right and no regression is visible. Here is why no concern applies today:

  Per the MVP4-11 D1 decision record: "Live DB audit shows all 80 managers are currently unknown." No manager is currently admin-typed as multi_strategy. The fallback weight of 0.60
   does not apply to any live manager yet — the behavior-derived profile (derive_manager_signal_profile) provides the type for all current managers, and that profile produces
  long_term_fundamental, value_concentrated, high_turnover, or unknown — not multi_strategy. The 0.60 fallback exists for when an admin explicitly sets a manager to multi_strategy,
  which has not happened.

  The admin priority queue (MVP4-07b) surfaces unknown-type managers by affected_signal_count. If the MVP4-11 conservative fallback were causing a visible regression (e.g., a
  manager who should be long_term_fundamental at 1.00 weight but is stuck at 0.60), it would appear in that queue as a high-priority classification target. The queue is the correct
  monitoring surface for this. No corrective action needed now; review after the first quarter of type classification activity.

  ---
  6. MVP4-07b CTA Absence — Right Product Semantics
  
  Confirmed: the priority queue Card without a "classify" button is the correct design. The task file's rationale is sound — "there is no existing manager_type edit surface to 
  deep-link into yet, so adding a fake CTA would be misleading." A classification button that goes nowhere, or worse opens a generic edit form without taxonomy guidance, would harm
  the admin UX rather than help it.

  MVP5 should add: a lightweight manager-type editor on the manager detail page — a single dropdown showing the canonical 8-value taxonomy with the current value pre-selected and a
  "save" action that writes InstitutionManager.manager_type. The priority queue's role is prioritization (which manager to classify first); the manager detail page's role is the
  action itself. These are correctly separate surfaces. Once the editor exists, the priority queue rows can deep-link to it.

  This is a one-sprint task, not a new decision gate. File it as MVP5-07b-follow-up.

  ---
  7. Pre-MVP5 Candidate Ordering — With Owners and Blockers
  
  Revised ordering from the verification doc's recommendation section:

  Rank 1 — Formula reconciliation (owner: engineering; unblocked)

  This gates the ?persisted=0 flag retirement (item 3 above), corrects the API default mismatch (use_persisted_scores=False server default vs frontend always sending true), and
  eliminates a 4× numeric scale difference that will confuse users the moment the legacy path is shown. No data or stakeholder input needed — the persisted formula is already
  defined in constants.py and the legacy formula is in dashboard.py:602. The delta is the min(weight*4, 1.0) scaling. This is engineering-owned and unblocked. First deliverable: the
   comparison utility described in item 3. Second deliverable: retire the legacy formula.

  Rank 2 — Class B caveat exclusion (amendments only) (owner: 13F domain SME for scope confirmation, engineering for implementation; one pre-condition)

  Pre-condition before opening this task: confirm whether the CUSIP-unresolved case is already effectively excluded by the eligibility query's cusip_mapping_status == "linked"
  filter. If yes, the MVP5 Class B scope is purely amendment-driven (pending + failed). That confirmation requires one query against the production schema, not a stakeholder
  meeting. Once confirmed, the task is unblocked. The MVP4-03 backlog language ("before any production launch that exposes the score externally") makes this a launch-gate item, not
  a nice-to-have — rank it above pre-2023 for that reason.

  Rank 3 — Pre-2023 historical backfill productionization (owner: product owner decision; blocked on demand signal)

  This is gated on one question: does any investor data ask require pre-2023 holdings? If yes, scope it. If no, it stays at "curated dry-run only" indefinitely. The dry-run path
  works correctly (MVP4-08 confirmed), so there is no operational pressure. This is the only item on the list that requires a product owner decision before it can be scoped — not a
  technical decision. Request the demand signal from the investor side before MVP5 opens, not after.

  Bonus item not in the verification doc:

  Rank 4 — Manager-type editor on manager detail page (owner: engineering; unblocked, one sprint)

  This completes the MVP4-07b prioritization loop. Without it, the admin priority queue shows which managers to classify but provides no path to do so. This is fast, entirely
  in-scope for MVP5, and unlocks the usefulness of the admin Card that already shipped.

  ---
  Decision on MVP5 Gate

  Recommendation: open the MVP5 decision gate this week.

  The milestone is complete. All D1–D6 closures are real against shipped code. The scope-freeze tally is zero. The test baseline is clean at 754 passed / 0 warnings. The one
  documentation correction (D1 add_intensity/holding_streak_quarters reserved-null annotation) is a doc edit, not a code change — it can land in the same commit that opens the MVP5
  gate document.

  Before opening the gate document, resolve three items that should be inputs to the gate, not outputs:

  1. The PO demand signal on pre-2023 backfill (does an investor data ask exist?) — answers whether Rank 3 above is in MVP5 or perpetually deferred.
  2. Explicit Class B scope confirmation (amendments only, or include CUSIP-unresolved after the query audit) — the 13F SME needs 30 minutes to confirm, not a review cycle.
  3. The ?persisted=0 retirement condition is now defined (item 3 above) — transcribe it into the MVP5 gate document as a hard acceptance criterion for the formula reconciliation
  task, not a soft backlog note.

  If those three inputs are in hand, the MVP5 decision gate can open Friday.


第四份：
Product Owner MVP4 End-to-End Review
Date: 2026-05-12 Milestone: MVP 4 (Oracle's Lens Base Scoring & Consensus)

This document serves as the formal Product Owner review of the MVP 4 closure, addressing the decision gate verifications, scope freezes, and prioritization for MVP 5.

1. D1–D6 Closure Verification (Verdict per row)
D1 (Oracle's Lens V1 scope): REOPEN / SCOPE LEAK. The verification doc claims the four score columns are the only persisted metrics, but a spot-check of the oracles_lens_signals table schema reveals that add_intensity and holding_streak_quarters sneaked in as top-level columns. These were defined in the PRD as base primitives/components, not top-level signal dimensions. This is minor schema bloat that we will accept for now to avoid a rollback, but it violates the strict D1 scope freeze.
D2 (No pre-2023 production backfill): CLOSED. is_dry_run is correctly stamped, keeping experimental backfills out of production UX.
D3 (V1 metric surface & visible-but-off distinctive): CLOSED. I verified frontend/app/(dashboard)/13f/oracles-lens/page.tsx. sort: 'signal_weighted_consensus' is indeed the default, with distinctive_consensus available only as an explicit user dropdown selection.
D4 (Value Line overlay deferred): CLOSED. No Value Line contamination.
D5 (Config module): CLOSED. backend/app/services/oracles_lens/constants.py is correctly implemented as typed Python (SCORE_VERSION="v1.0"). No JSON/TOML or DB-table config was smuggled in.
D6 (Backlog tickets accepted): CLOSED. All required technical debt and conftest hardening (MVP4-08, 09, 10) shipped as requested.
2. Scope-Freeze Tally Confirmation
Status: CONFIRMED. The scope-freeze tally of "zero new debt opened" is accurate. I cross-checked the task logs:

Class B caveat exclusion is explicitly logged in 2026-05-11_13f-mvp4-05-caution-flags.md.
Formula reconciliation is explicitly deferred in 2026-05-11_13f-mvp4-03b-dashboard-persisted-scores.md.
Pre-2023 backfill and NT banner integration trace directly to their respective tasks.
No vague promises; everything maps to an accountable task backlog.

3. ?persisted=0 Debug-Flag Lifecycle
PO Decision: The "one release cycle" means the closure of MVP 5.

Retirement Condition: If the use_persisted_scores=true default path triggers zero user-reported data omissions and the admin priority queue remains functional throughout the MVP 5 development cycle, the legacy in-memory formula will be permanently deleted at the end of MVP 5.
Validation Surface: The admin priority queue is sufficient for observability. No new observability paths are required.
4. Class A vs Class B Caveat Decision
PO Decision: Pull Class B into MVP 5 scope.

While Class A (delta-only suppression) was correctly kept as a "snapshot bonus preservation," Class B caveats (e.g., pending amendments, unresolved CUSIPs) fundamentally corrupt the snapshot integrity. Leaving them unhandled risks surfacing false-positive holdings to users. This is a critical trust vector and must be tackled immediately in MVP 5.
5. multi_strategy=unknown=0.60 V1 Fallback
PO Decision: Confirm the fallback.

This conservative fallback was a deliberate choice. A multi_strategy firm does not emit a pure directional signal. Because multi_strategy is a distinct taxonomy type, it does not match manager_type == "unknown", meaning these managers will not flood the MVP4-07b admin priority queue. The design works precisely as intended.
6. MVP4-07b CTA Absence (No "Classify" Button)
PO Decision: This is the correct product semantics for V1.

The admin priority Card is a reporting queue, not an inline editor. Routing the user to the existing InstitutionManager edit surface is an acceptable operator workflow. An inline classification CTA is out of scope for MVP 5 and can be re-evaluated in the V2 Admin track.
7. Ordered Pre-MVP5 Candidate List
Here is the prioritized list of deferred items to pull into MVP 5, ranked by impact on data trust:

Class B Caveat Handling (Owner: Implementation Agent)
Why: Missing this compromises the accuracy of the snapshot itself.
Blocked: No. The flags are already available on Filing13F; the scorer just needs to drop the holder contribution.
Formula Reconciliation (Owner: Frontend/Backend Dev)
Why: We must burn the legacy in-memory formula bridge before we accumulate more technical debt.
Blocked: No. Requires math synchronization between frontend and backend.
Pre-2023 Historical Backfill Productionization (Owner: PO/Tech Lead)
Why: Expanding the backfill window.
Blocked: YES. I need to request stakeholder input on whether our launch strategy requires > 3 years of historical depth. Keep deferred until I get that confirmation.
Final Recommendation
The MVP 5 decision gate is cleared to open this week. Despite the minor schema bloat identified in D1, the milestone effectively stabilizes the Oracle's Lens V1 core, respects the decision gates, and sets a clean stage for the MVP 5 aggregation features.

第五份：

13F Domain SME Review: MVP 4 Scoring Stack
Date: 2026-05-12 Scope: MVP 4 (Oracle's Lens base primitives, signal-weighted consensus, conviction, distinctive consensus, caveats, taxonomy)

This is the Domain SME review verifying financial data correctness, formula fidelity, and caveat propagation against the PRD and Product Plan.

1. Plan §7.2 Signal-Weighted Consensus Formula Fidelity
Verdict: APPROVE

Finding: The formula in signal_weighted_score.py matches the PRD line-for-line. position_signal_weight correctly incorporates the raw portfolio_weight + bonuses + action adjustments. The manager_signal_weight is correctly pulled from the approved 8-value MANAGER_SIGNAL_WEIGHTS table and multiplied against the complete position signal weight.
Conclusion: The legacy min(weight*4, 1.0) logic currently living in the dashboard in-memory path is indeed a divergence. The MVP4-03 backend implementation is the correct canonical source of truth.
2. Conviction Score §7.9 Component Caps
Verdict: APPROVE

Finding: compute_conviction_components implements all 5 components perfectly. They are individually capped at the documented maximums (30, 25, 20, 15, 10). Importantly, the code correctly reads holding_streak_quarters and add_intensity from _HolderContribution to compute fractions using sub-threshold precision, avoiding the binary truncation issue from earlier drafts.
3. Distinctive Consensus §7.11 Multiplier
Verdict: APPROVE

Finding: compute_distinctive_consensus correctly calculates concentration_factor, persistence_factor, and anti_crowding_factor, capping each at [0, 1]. The anti_crowding_factor uses the mean manager_weight across the holding cluster, which naturally resolves through the post-MVP4-11 8-value taxonomy.
4. Class A Caveat-Propagation Rules
Verdict: FLAG

Finding: The logic to suppress action_adjustment while preserving snapshot bonuses is correctly implemented. However, PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT is incorrectly placed in the _MEDIUM_CAVEATS set.
Impact: Instead of demoting the score confidence to "low" as specified for Class A caveats, it only demotes it to "medium". (Note: The action_adjustment still happens to evaluate to 0 because add_intensity returns None for pre-2023 history, triggering an elif fallback, but the caveat membership itself fails to enforce the Class A contract).
Action: Move PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT to _LOW_CAVEATS in MVP 5 backlog.
5. score_confidence Demotion Contract
Verdict: FLAG

Finding: Worst-tier wins logic successfully sets the overall confidence label. However, the reason-aggregation logic in _build_score_explanation contains a silent truncation bug.
Impact: If a score resolves to "low_confidence", the code only appends caveats from _LOW_CAVEATS into confidence_demotion_reasons. If a holding has both a low caveat (e.g., stale_until_recompute) and a medium caveat (e.g., PARTIAL_COVERAGE), the medium caveat is silently dropped from the API payload. The UI loses visibility into the full set of caveats on the holder.
Action: Refactor the loop in _build_score_explanation to append all triggered caveats, regardless of which tier won the overall label.
6. Manager_type 8-Value Taxonomy Mapping
Verdict: APPROVE

Finding: resolve_manager_type perfectly implements the precedence contract: admin (if not unknown) → behavior (if not unknown) → fallback_unknown. The canonical weights apply cleanly, including the deliberate multi_strategy=0.60 conservative fallback.
7. Kahn Brothers $-not-$K Trap
Verdict: BLOCK (Requires Pre-MVP5-Open Fix)

Finding: compute_portfolio_weight calculates weight = Decimal(holding.value_thousands) / Decimal(denominator). There is no explicit guard in the scoring stack capping this weight at 1.0, nor does it check for the VALUE_UNIT_SANITY finding.
Impact: If a manager leaks into the pipeline reporting in dollars while the denominator resolves to reported_total_value_thousands (in $K), the calculated portfolio_weight will be 1000× too large (e.g., 50.0 instead of 0.05). This uncapped weight will violently bias the downstream distinctive_consensus_score by maxing out the concentration_factor.
Action: Add an explicit defensive guard min(weight, Decimal("1.0")) in compute_portfolio_weight, or suppress the contribution entirely if VALUE_UNIT_SANITY is open. This must be fixed before opening the MVP 5 gate to prevent corrupting the newly launched consensus ranks.

第六份：

13F Domain SME Review — MVP4 Scoring Stack

  Verification baseline: 754 passed / 0 warnings, alembic head 20260512120000

  ---
  Item 1 — §7.2 Signal-Weighted Formula Fidelity

  APPROVE (persisted path) / FLAG (dashboard divergence addendum)

  The MVP4-03 persisted scorer uses raw portfolio_weight decimal as the position base — correct per plan §7.2, which specifies portfolio weight as a fraction in [0,1]. The
  dashboard's legacy _position_signal_weight (score = min(holding.position_weight * 4, 1.0)) was already flagged in the verification doc.

  Additional finding not in the verification doc: the dashboard's action magnitude bonuses are inverted relative to MVP4-03. Dashboard has new=+0.10, add=+0.20; MVP4-03 has
  new=+0.20, add=+0.10. A manager opening a new position is more decisive than adding to an existing one — MVP4-03's ordering is semantically correct. The dashboard's inversion
  predates MVP4 and is the stronger argument for retiring ?persisted=0 quickly.

  Flag for MVP5 backlog: Document the action-magnitude inversion explicitly in the formula-reconciliation ticket so the reconciler knows which direction to normalize toward.

  ---
  Item 2 — Conviction Score §7.9 Component Caps

  APPROVE

  All five component caps are correct and individually enforced:

  ┌─────────────────────┬─────┬───────────┐
  │      Component      │ Cap │ Plan §7.9 │
  ├─────────────────────┼─────┼───────────┤
  │ position_importance │ 30  │ ✓         │
  ├─────────────────────┼─────┼───────────┤
  │ holding_persistence │ 25  │ ✓         │
  ├─────────────────────┼─────┼───────────┤
  │ manager_quality     │ 20  │ ✓         │
  ├─────────────────────┼─────┼───────────┤
  │ recent_action       │ 15  │ ✓         │
  ├─────────────────────┼─────┼───────────┤
  │ agreement           │ 10  │ ✓         │
  └─────────────────────┴─────┴───────────┘

  holding_streak_quarters (raw integer) and add_intensity (raw Decimal) are passed through on _HolderContribution and used directly in persistence and recent-action scoring. This
  preserves sub-4-quarter precision for emerging positions rather than flattening to a binary. add_intensity > 0 as the recent-action signal correctly captures the underlying
  behavior even when action_adjustment was zeroed by a Class A caution flag — the two signals are independently computed.

  ---
  Item 3 — Distinctive Consensus §7.11 Multiplier Factors

  APPROVE / FLAG (naming semantics)

  Three factors correctly bounded in [0, 1]:
  - concentration_factor: aggregate portfolio weight / 0.10 — rewards high-conviction aggregate positioning
  - persistence_factor: median streak / 4 — rewards long-term holders 
  - anti_crowding_factor: mean manager_weight ≤ 1 — uses post-MVP4-11 _HolderContribution.manager_weight, correct

  Flag for MVP5 backlog: anti_crowding_factor is a misleading name. The factor doesn't measure crowding volume (number of holders or AUM concentration in a stock) — it measures the
  aggregate quality of the holders (their signal weights). "High-quality manager agreement factor" would be accurate. This is a naming/documentation issue, not a formula error, but
  it will confuse any SME or investor reading the scoring spec. Rename in the §7.11 comment block and dashboard tooltip before GA.

  ---
  Item 4 — Class A Caveat-Propagation Rules

  APPROVE

  _LOW_CAVEATS and _MEDIUM_CAVEATS are correctly populated:

  - Low (→ low_confidence, action_adjustment=0): STALE_UNTIL_RECOMPUTE_CAVEAT, HISTORICAL_BACKFILL_NEEDS_VALIDATION_CAVEAT — both correct; stale data and unvalidated historical data
   should suppress action signals entirely
  - Medium (→ medium_confidence): PARTIAL_COVERAGE, NT_QUARTER_STREAK_BREAK, PRE_2023_PRE_HISTORY_UNAVAILABLE, AMENDMENTS_PENDING, AMENDMENT_FAILED — correct; these degrade but
  don't invalidate

  PRE_2023_PRE_HISTORY_UNAVAILABLE landing in medium rather than low is the right call: pre-2023 data is missing but the current-quarter position itself is valid and the streak is
  just truncated. Low would be too aggressive.

  The Class A suppression mechanism at signal_weighted_score.py:192–205 works via action_adjustment = Decimal("0"), while add_intensity on _HolderContribution remains non-zero for
  conviction scoring. This is the correct dual-signal design: caution flags suppress the aggregate action bonus without corrupting the per-holder raw behavior record.

  ---
  Item 5 — Score Confidence Demotion Contract

  APPROVE / FLAG (UX nuance)

  The demotion contract is: if any caveat is in _LOW_CAVEATS, the stock gets low_confidence and the low-caveat codes populate confidence_demotion_reasons. If only _MEDIUM_CAVEATS
  are present, medium_confidence is emitted.

  Flag for MVP5 backlog: When a stock triggers both a low-caveat and medium-caveats, the confidence_demotion_reasons list will contain only the low-caveat codes — the medium codes
  are omitted because low wins. An investor seeing low_confidence with only STALE_UNTIL_RECOMPUTE in the reasons drilldown won't know there's also an AMENDMENTS_PENDING. Acceptable
  for V1 since low confidence is the dominant signal, but the drilldown panel should surface all active caveats, not just the tier-determining ones, before external launch.

  ---
  Item 6 — Manager-Type Taxonomy Mapping and Precedence

  APPROVE (weights and taxonomy) / FLAG (SOURCE_BEHAVIOR dead code)

  The 8-value canonical taxonomy and weights are correct:

  ┌───────────────────────┬────────┬───────────────────────────────────┐
  │         Type          │ Weight │             Rationale             │
  ├───────────────────────┼────────┼───────────────────────────────────┤
  │ long_term_fundamental │ 1.00   │ Highest signal quality            │
  ├───────────────────────┼────────┼───────────────────────────────────┤
  │ value_concentrated    │ 1.00   │ Highest signal quality            │
  ├───────────────────────┼────────┼───────────────────────────────────┤
  │ activist              │ 0.80   │ High signal, shorter horizon      │
  ├───────────────────────┼────────┼───────────────────────────────────┤
  │ unknown               │ 0.60   │ Conservative fallback             │
  ├───────────────────────┼────────┼───────────────────────────────────┤
  │ multi_strategy        │ 0.60   │ V1 conservative; equals unknown ✓ │
  ├───────────────────────┼────────┼───────────────────────────────────┤
  │ quant                 │ 0.40   │ Lower signal per share move       │
  ├───────────────────────┼────────┼───────────────────────────────────┤
  │ high_turnover         │ 0.30   │ Noise-heavy                       │
  ├───────────────────────┼────────┼───────────────────────────────────┤
  │ index_like            │ 0.10   │ Near-zero signal value            │
  └───────────────────────┴────────┴───────────────────────────────────┘

  multi_strategy=0.60 equaling unknown=0.60 is correct for V1 — multi-strategy managers have genuinely ambiguous intent and the conservative fallback is the right prior until
  behavior profiling is live.

  Flag for MVP5 backlog (critical): resolve_manager_type is called at signal_weighted_score.py:510 with derived_profile=None always. The three-tier precedence (admin → behavior →
  fallback_unknown) collapses to two tiers in production: admin-set type if non-unknown, otherwise unknown. derive_manager_signal_profile and manager_signal.py are tested but
  unreachable in the live scoring path. This means:
  - High-turnover managers with ≥0.60 turnover who haven't been admin-typed get unknown weight (0.60) instead of high_turnover weight (0.30) — they are over-weighted
  - Long-term fundamental managers not yet admin-typed get unknown (0.60) instead of 1.00 — they are under-weighted

  The error is conservative in that it doesn't catastrophically mis-rank, but it reduces the taxonomy to an admin-only configuration system, defeating the behavior-derived fallback
  design. Wire derive_manager_signal_profile into the scoring path before the scoring stack is presented as fully operational to investors.

  ---
  Item 7 — Kahn Brothers Dollar-Not-Thousands Trap

  APPROVE / FLAG (undocumented safety assumption)

  The scoring stack is safe. portfolio_weight is computed as value_usd / total_portfolio_value_usd — both numerator and denominator use the same raw value_thousands field in the
  same unit. For Kahn Brothers, both are in raw dollars (not thousands), so the ratio is unit-invariant. The 1000× error cancels in the division.

  value_usd at thirteenf_holdings_ingest.py:153–156 is correctly adjusted for display (×1000 when value_unit=="thousands", ×1 when value_unit=="dollars"), so the holding-level
  dollar value is accurate. The scoring stack uses portfolio_weight (the ratio), not value_usd directly, so even the unit-adjusted value is never used raw in score computation.

  Flag for MVP5 backlog: This safety property is implicit — nothing in signal_weighted_score.py or constants.py documents that the scoring stack is ratio-based and therefore
  unit-agnostic. A future developer adding an absolute-value-based signal component (e.g., AUM threshold gate) would inherit the Kahn Brothers trap without warning. Add a one-line
  comment at the portfolio_weight usage site: ratio-based; unit error from filers like Kahn Brothers (reports in dollars not thousands) cancels in the division.

  ---
  Summary Verdict

  ┌───────────────────────────────┬────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │             Item              │    Verdict     │                                                     Action                                                      │
  ├───────────────────────────────┼────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 1. §7.2 formula fidelity      │ APPROVE + FLAG │ File MVP5: document action-magnitude inversion (new vs add) in formula-reconciliation ticket                    │
  ├───────────────────────────────┼────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 2. Conviction caps            │ APPROVE        │ None                                                                                                            │
  ├───────────────────────────────┼────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 3. Distinctive §7.11          │ APPROVE + FLAG │ File MVP5: rename anti_crowding_factor → manager-quality-agreement factor                                       │
  ├───────────────────────────────┼────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 4. Class A caveat propagation │ APPROVE        │ None                                                                                                            │
  ├───────────────────────────────┼────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 5. Confidence demotion        │ APPROVE + FLAG │ File MVP5: surface all active caveats in drilldown, not just tier-determining ones                              │
  ├───────────────────────────────┼────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 6. Taxonomy / precedence      │ APPROVE + FLAG │ File MVP5 (critical): wire derive_manager_signal_profile into production scoring path before investor-facing GA │
  ├───────────────────────────────┼────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 7. Kahn Brothers              │ APPROVE + FLAG │ File MVP5: add ratio-design comment at portfolio_weight usage site                                              │
  └───────────────────────────────┴────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  No BLOCKs. MVP5 gate can open. The two most consequential flags — action-magnitude inversion (Item 1) and SOURCE_BEHAVIOR dead code (Item 6) — should both be triaged at MVP5
  kick-off, not deferred to the end of the milestone.

  第七份：

  Frontend / UX Review: MVP 4 Oracle's Lens & Admin Queue
Date: 2026-05-12 Scope: MVP4-07a (persisted scores wire-up) & MVP4-07b (admin priority queue insertion)

1. Persisted-mode default + debug opt-out
Verdict: APPROVE

Assessment: The implementation avoids Suspense boundaries by reading window.location.search synchronously in useEffect and defaulting to true.
User Impact: Standard users (who have no ?persisted=0 query param) will see true immediately and experience no flash of wrong-mode content. The only users who experience a split-second flash are admins explicitly opting out via the URL parameter. This is a correct and pragmatic trade-off to avoid penalizing 100% of production users with a layout shift or boundary fallback for a temporary debug escape-hatch.
2. Persisted badge attribution
Verdict: APPROVE

Assessment: Rendering the persisted badge adjacent to the confidence badge via the standard shadcn Badge variant="outline" creates a clear, distinct visual grouping without overpowering the primary score_confidence coloring.
A11y: The Badge component survives keyboard navigation and screen readers (it reads cleanly as text). For an internal/expert dashboard, explicitly declaring "persisted" is sufficient semantic meaning.
3. confidence_demotion_reasons drilldown
Verdict: RECOMMEND-CHANGE

Assessment: The drilldown panel successfully enumerates the codes, but surfacing raw UPPER_SNAKE_CASE strings like HISTORICAL_BACKFILL_NEEDS_VALIDATION or PARTIAL_COVERAGE is hostile to non-technical users.
Action: Add a friendly string-mapping dictionary in frontend/lib/oraclesLens.js (e.g., HISTORICAL_BACKFILL_NEEDS_VALIDATION → "Historical backfill pending validation"). If a rule code isn't in the dictionary, fallback to the raw string.
4. MVP4-07b admin Card placement
Verdict: APPROVE

Assessment: Inserting the "Unknown Manager Type Priority" card directly below "Needs Validation" and above "Batch Reparse" is the correct cognitive and operational flow. It groups actionable, high-priority queues at the top of the page (Validation backlog → Manager-typing backlog → Reparse operations), separating them from the general "Managers" reference table (#managers) further down.
5. Empty states
Verdict: APPROVE

Assessment: Both empty states are accurate and reachable:
"No persisted Oracle's Lens scores yet" correctly appears on a fresh instance, guiding the admin up to the Historical Backfill section.
"No unknown-typed managers contribute..." correctly appears when Inbox Zero is achieved, confirming to the admin that their priority queue is clear. The copy successfully guides the admin in both scenarios.
6. No CTA on the admin Card
Verdict: RECOMMEND-CHANGE

Assessment: A priority queue is an operational workflow tool; an inert row breaks the workflow. Even if the dedicated "Edit Manager" surface is slated for MVP 5, the admin must be able to act on the queue without memorizing names and manually CTRL+F searching the reference table below.
Action: Wrap the manager name in a deep link (e.g., <Link href={"/admin/managers/" + row.manager_id}>) or add an explicit "View Manager" button in the table actions. This link can point to a placeholder or simply anchor-jump and filter the bottom Managers table until the dedicated edit page exists.
7. A11y / responsive baseline
Verdict: APPROVE

Assessment: The implementation heavily leverages standard shadcn UI components (Table, Badge, Card). The new UI regions (drilldown list, priority table, outlier badges) use standard Tailwind tokens (text-muted-foreground, bg-background) which inherently preserve the established contrast ratios and focus ring behaviors from MVP 3. No regressions found.

第八份：

Frontend / UX Review — MVP4 User-Facing Surface
  
  Files reviewed: oracles-lens/page.tsx (1088 lines), oraclesLens.js (459 lines), oraclesLens.test.js (476 lines), admin/13f/page.tsx (3300+ lines)

  ---
  Item 1 — Persisted-mode default + debug opt-out

  APPROVE

  The implementation at page.tsx:144–150 is correct for the stated purpose:

  const [usePersistedScores, setUsePersistedScores] = useState(true);
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const flag = new URLSearchParams(window.location.search).get('persisted');
      setUsePersistedScores(flag !== '0');
    }
  }, []);

  The flash concern is theoretical, not practical. The sequence on ?persisted=0 is: (1) initial render fires the use_persisted_scores=true request; (2) useEffect fires synchronously
   after mount, before the network response arrives; (3) queryParams recomputes, old query is abandoned, correct query starts. The user sees the loading state the entire time —
  never persisted data. The only real cost is one wasted network request, which is acceptable for a debug escape hatch.

  The flag !== '0' expression is also correct: null (no param) → true; '0' → false; anything else (e.g., ?persisted=1) → true. This is intentional and fine.

  The comment at line 138–143 accurately describes the trade-off. No change needed, but add one-line retirement note: when ?persisted=0 is removed, delete the useEffect block and
  the useState — usePersistedScores can be inlined as true in buildOracleLensQueryParams.

  ---
  Item 2 — Persisted badge attribution

  RECOMMEND-CHANGE

  The badge renders at page.tsx:648–652:

  {row.scoreSource === 'persisted' ? (
    <Badge variant="outline" className="ml-1 mt-2 rounded-md">
      persisted
    </Badge>
  ) : null}

  Two issues:

  Label is jargon. "Persisted" means nothing to an analyst or investor user. The word is an implementation detail (the score came from the DB table vs. computed in-memory). The
  coverage panel at line 393–401 gets this right — it explains "items use the canonical Oracle's Lens score table" — but the row badge doesn't carry that context. Change the label
  to "v1 scored" or "canonical score". If "persisted" must stay for operator clarity, add title="Score computed by Oracle's Lens v1.0 backfill and read from the canonical table" for
   hover/screenreader context.

  Visual hierarchy is crowded. The Signal Score cell stacks: large number → confidence badge → persisted badge. The persisted badge uses ml-1 (inline with the confidence badge),
  which works visually but creates a three-element cluster where all three have equal visual weight. The confidence badge is the signal users should act on; the persisted badge is
  metadata about the score's source. Consider moving the persisted badge to the Company cell (below the ticker, same mt-1 text-xs row as the company name) to remove it from the
  primary rank signal area.

  Screenreader: The Badge renders as a <span>. Screenreaders will announce "persisted" mid-sentence in the cell, which is fine structurally but confusing without context. title or
  aria-label resolves this.

  Specific change: In oraclesLens.js:normalizeOracleLensRows, the scoreSource is already normalized as a string. No normalizer change needed. Fix is rendering-only in page.tsx.

  ---
  Item 3 — confidence_demotion_reasons drilldown

  RECOMMEND-CHANGE

  The panel at page.tsx:885–904:

  <li key={reason.code}>
    <span className="font-mono">{reason.code}</span>
    {reason.demotedTo ? ` → ${reason.demotedTo}` : null}
  </li>

  Produces output like:
  PARTIAL_COVERAGE → medium_confidence
  AMENDMENTS_PENDING → medium_confidence

  Two problems:

  1. Raw codes are opaque. PARTIAL_COVERAGE and AMENDMENTS_PENDING are database rule_code strings. A non-technical user will not know what these mean. The normalizer already has
  changeStatusLabel() as a precedent for label mapping. Add a parallel DEMOTION_REASON_LABELS constant to oraclesLens.js:

  const DEMOTION_REASON_LABELS = {
    PARTIAL_COVERAGE: 'Partial filing coverage',
    AMENDMENTS_PENDING: 'Amendment not yet ingested',
    AMENDMENT_FAILED: 'Amendment ingestion failed',
    NT_QUARTER_STREAK_BREAK: 'NT filing broke holding streak',
    HISTORICAL_BACKFILL_NEEDS_VALIDATION: 'Historical data needs validation',
    PRE_2023_PRE_HISTORY_UNAVAILABLE: 'Pre-2023 history not available',
    STALE_UNTIL_RECOMPUTE: 'Score is stale — recompute needed',
  };

  1. Use it in normalizeOracleLensRows to add a label field alongside code, then render reason.label in the <li> (keep reason.code in a title attribute for operator debugging).
  2. demotedTo has underscores. medium_confidence rendered with underscores is jarring even to technical users. Replace underscores: reason.demotedTo?.replaceAll('_', ' '). Also the
   → arrow is meaningful only if the user knows what it's pointing from — consider "→ score confidence: medium" for clarity.
  3. font-mono on the raw code. Some screenreaders spell out PARTIAL_COVERAGE character by character when the element has font-mono styling (specifically NVDA with certain
  settings). After switching to the label, font-mono on the label string is unnecessary — drop it. If you keep code visible (in a <details> or title), keep font-mono there only.

  ---
  Item 4 — MVP4-07b admin Card placement

  RECOMMEND-CHANGE (conditional on Item 6)

  The card sits at admin/13f/page.tsx:2061, between "Needs Validation" (~line 2018) and "Batch Reparse" (~line 2151). The intended cognitive flow: validation backlog →
  manager-typing backlog → reparse operations.

  This ordering has internal logic — both Needs Validation and Unknown Manager Priority are outstanding quality-debt queues that degrade confidence scores. But there's a practical
  UX problem: without a CTA (Item 6), the admin sees the priority list at line 2061 and then has to scroll ~1300 lines to the managers section (~line 2344) to act on it. The current
   placement assumes a CTA will close the loop; without one, it creates dead-end awareness.

  Conditional verdict:
  - If Item 6 (deep link) lands in the same follow-up task, the current position is acceptable. The queue is conceptually a quality-debt surface, not a manager-management surface,
  and belongs near other quality-debt cards.
  - If Item 6 is deferred past MVP5, move the card to immediately above or below the managers section (~line 2344). An admin working through the priority list should be one scroll
  away from the edit surface.
  
  File this as one follow-up task covering both Items 4 and 6 so they land together.

  ---
  Item 5 — Empty states

  RECOMMEND-CHANGE

  State 1 (page.tsx:2087–2090, no quarter data):
  "No persisted Oracle's Lens scores yet — run a backfill to populate this list."

  This is reachable on a fresh instance. The copy is accurate but directionless — "run a backfill" doesn't tell the admin where or how. The Historical Backfill card is far up the
  page. Suggested copy:

  ▎ No Oracle's Lens scores computed yet. Use the Historical Backfill section above to generate scores for a quarter, then return here.

  Or add a <Link href="#historical-backfill"> anchor if the historical backfill card gets an id attribute.

  State 2 (page.tsx:2091–2094, quarter data exists but no unknown managers):
  "No unknown-typed managers contribute to the latest scored quarter."

  This is reachable when all managers are typed — which is the success condition. The current copy is neutral; it should read as a positive all-clear:

  ▎ All contributing managers are typed for {quarter}. Signal weights are fully resolved.

  The quarter value is available from unknownManagerPriorityQuery.data.quarter (already rendered in the card header), so it can be injected directly.

  Neither empty state is a blocking issue, but State 1's copy will confuse a first-time admin and State 2 will cause an operator to wonder if something is wrong.

  ---
  Item 6 — No CTA on the admin Card

  RECOMMEND-CHANGE

  The table row at page.tsx:2118–2143 shows manager name and ID (#{row.manager_id}) but no link. The admin sees that "Acme Capital Partners" affects 14 signals with low confidence
  but has no path to fix it without separately navigating to the managers section and searching.

  The manager_id is already surfaced. The minimum acceptable change is wrapping the manager name in a link:

  <Link
    href={`/admin/13f#manager-${row.manager_id}`}
    className="font-medium hover:underline"
  >
    {row.canonical_name}
  </Link>

  This requires adding id={manager-${manager.id}} to the manager rows in the managers section (~line 2356). The anchor link is zero-cost to add and survives even when the dedicated
  manager-edit page doesn't exist yet.

  If a /admin/managers/{id} page is planned for MVP5, stub the route now — a 404 with a "not yet available" message is more intentional than a dead table with no interaction at all.
   The priority-queue pattern only works when a user can go from awareness to action without context-switching.

  ---
  Item 7 — A11y / responsive baseline

  RECOMMEND-CHANGE (three concrete issues)

  7a. Slide-out panel is not marked as a dialog (page.tsx:756–1085).

  The panel uses fixed inset-0 z-50 with a backdrop overlay, which is modal in behavior, but is missing ARIA semantics:
  - No role="dialog" on the panel <Card>
  - No aria-modal="true"
  - No aria-labelledby pointing to the "Candidate Review" title
  - Focus is not moved into the panel on open; tab order remains in the background document

  Screenreaders will not announce this as a modal and will let users tab through background content. Fix:
  <Card
    role="dialog"
    aria-modal="true"
    aria-labelledby="candidate-review-title"
    ...
  >
    <CardTitle id="candidate-review-title">Candidate Review</CardTitle>
  Add a useEffect that moves focus to the close button (ref + .focus()) on panel open, and restores focus to the triggering row button on close.

  7b. font-mono rule_code strings in the demotion panel (page.tsx:898–900).

  NVDA and some versions of VoiceOver will spell out PARTIAL_COVERAGE character-by-character when the element has font-mono styling. After the label-map change from Item 3 resolves
  this, the problem disappears. If label mapping is deferred, add aria-label={reason.label ?? reason.code.replaceAll('_', ' ').toLowerCase()} on the <span>.

  7c. Admin priority table missing overflow wrapper (page.tsx:2104–2145).

  The Unknown Manager Priority <Table> has no overflow-x-auto wrapper. The main Oracle's Lens table has one at page.tsx:613. On narrow viewports, the three-column admin table
  ("Manager" / "Affected signals" / "Worst score_confidence") will overflow and clip. The "Worst score_confidence" column in particular has long badge text (medium_confidence). Wrap
   the <Table> in <div className="overflow-x-auto">.

  No contrast regressions found. The variant="outline" persisted badge and variant="warning" confidence badge both use Tailwind-standard color tokens. The caution flag tiers (danger
   / warning / secondary) match the existing pattern from MVP3. No new color introductions.

  ---
  Summary

  ┌───────────────────────────────┬──────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │             Item              │     Verdict      │                                                Follow-up action                                                │
  ├───────────────────────────────┼──────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 1. Persisted-mode default     │ APPROVE          │ Add retirement comment in code                                                                                 │
  ├───────────────────────────────┼──────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 2. Persisted badge label      │ RECOMMEND-CHANGE │ Change label; add title; move badge out of rank-signal cluster                                                 │
  ├───────────────────────────────┼──────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 3. Demotion reasons drilldown │ RECOMMEND-CHANGE │ Add DEMOTION_REASON_LABELS map to oraclesLens.js; remove underscores from demotedTo; drop font-mono on labels  │
  ├───────────────────────────────┼──────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 4. Admin Card placement       │ RECOMMEND-CHANGE │ Conditional on Item 6; file as single task                                                                     │
  ├───────────────────────────────┼──────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 5. Empty states               │ RECOMMEND-CHANGE │ State 1: add directional hint; State 2: reframe as success state                                               │
  ├───────────────────────────────┼──────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 6. No CTA                     │ RECOMMEND-CHANGE │ Add anchor-link to manager row; stub /admin/managers/{id} if MVP5 page is planned                              │
  ├───────────────────────────────┼──────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 7. A11y / responsive          │ RECOMMEND-CHANGE │ role="dialog" + aria-modal + focus trap on slide-out; aria-label on mono codes; overflow-x-auto on admin table │
  └───────────────────────────────┴──────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  No BLOCKs. All items are polish-tier follow-ups suitable for a single MVP5 frontend hardening task. Items 3 and 7b are coupled — resolving the label map in Item 3 eliminates the
  screenreader concern in 7b. Items 4 and 6 should land in the same PR. Items 2 and 3 can land together as a "badge + drilldown copy pass."