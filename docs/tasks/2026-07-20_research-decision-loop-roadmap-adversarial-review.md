# Adversarial review — Research Decision Loop roadmap

Date: 2026-07-20  
Target: `docs/plans/research_decision_loop_product_roadmap.md`  
Status: signed off

## Review method

Each round attempts to falsify the roadmap from seven perspectives:

1. PO / value-investor usefulness and scope discipline;
2. 13F and financial-data semantics;
3. database integrity, migrations, concurrency, and recoverability;
4. API authorization, privacy, secrets, and abuse cases;
5. frontend workflow, accessibility, and misleading copy;
6. jobs, delivery, retries, observability, and rollback;
7. testability, external dependencies, and completion evidence.

A round passes only after each finding is either fixed in the roadmap or shown
not to be a real issue with concrete evidence. “Deferred” is not a disposition
unless the affected behavior is explicitly removed from the program's
completion definition.

## Round 1 — contract and feasibility attack

Result: **FAIL — valid findings found**

| ID | Severity | Finding | Required resolution |
| --- | --- | --- | --- |
| R1-01 | high | The case lifecycle says `decided -> archived`, but scheduled reviews require an owned/watched thesis to return to active research. The current model either loses the prior decision or creates ambiguous duplicate cases. | Define valid state transitions, terminal behavior, review reopening, and the exact partial-uniqueness predicate. |
| R1-02 | high | Phase 1's 80% Value Line coverage exit can be impossible without a licensed source or user-provided reports. It conflates implementation readiness with external data availability. | Split capability gates from post-configuration efficacy targets; never count `blocked` as covered. |
| R1-03 | high | User-controlled Slack with an unspecified destination model risks sending one user's research to a shared deployment webhook or storing webhook secrets unsafely. | Define user-owned destinations, encryption/key readiness, host allowlist, masking, rotation, SSRF controls, and zero-send behavior. |
| R1-04 | high | Email delivery requires a verified recipient, but the roadmap does not define verification or prevent activation for an unverified account. | Add a verification gate and explicitly leave external email disabled until it passes. |
| R1-05 | high | Manual portfolio fields have no multi-currency policy. Aggregating prices, values, or P&L across currencies would create false precision. | Require currency on money, forbid cross-currency aggregate claims without a sourced FX conversion layer, and keep V1 per-position/per-currency. |
| R1-06 | medium | `at most one non-archived case` conflicts with starting a new research cycle after a prior `pass`. | Define active states and enforce the partial unique index only over those states. |
| R1-07 | medium | Valuation ranges lack ordering, precision, and “partial range” rules. | Define decimal precision, currency, `low <= base <= high`, all-or-none values, and explicit unavailable reason. |
| R1-08 | medium | Evidence validation says “visible to the user” but does not state how a global fact linked to another user's source document avoids leaking private document text. | Define evidence snapshot/access behavior and prohibit exposing an inaccessible source document through a global fact. |
| R1-09 | medium | Notification audit is underspecified for in-app read state, logical event identity, and per-channel attempts. A single existing `notification_events` row cannot safely represent all three. | Separate logical notifications, destinations/subscriptions, and delivery attempts/read state at contract level. |
| R1-10 | medium | Quiet hours say timezone-aware but do not specify IANA zones/DST or UTC scheduling. | Require IANA timezone validation and compute persisted next-attempt times in UTC with DST-safe library behavior. |
| R1-11 | medium | Phase 0 requires “user-approved exclusion” for every medium issue even though the user delegated PO responsibility and several items can be resolved by explicit product decisions. | Require recorded PO disposition; ask the user only for new authority, licensing, or locked-design contradictions. |
| R1-12 | medium | Existing APIs accept `user_id`; the roadmap correctly forbids that for new authority but does not say integrations with legacy Watchlist endpoints must not trust query ownership. | Include touched legacy endpoints in the authorization migration/compatibility scope and add cross-user regression tests. |
| R1-13 | medium | External URL evidence can enable stored-XSS/phishing even without server-side fetch. | Normalize schemes, allow only safe `https`/explicit `http` policy, render as text, add rel/sandbox behavior, and display the external-domain boundary. |
| R1-14 | medium | Research revision “complete snapshot” does not define whether mutable source labels/names are snapshotted or re-read, so historical display may drift. | Snapshot user-authored decision content and durable source IDs; render historical source facts as recorded plus an optional clearly labeled current comparison. |
| R1-15 | low | The first task doc names expected files but the plan does not require a route-level contract test for navigation and deep links. | Add route/deep-link/back-button acceptance to frontend gates. |

## Round 1 disposition

All findings are accepted as real. The roadmap must be revised before Round 2.

## Round 2

Result: **FAIL — valid findings found after Round 1 remediation**

Round 1 findings were re-read against the revised text and all fifteen are
addressed. A second attack focused on cross-feature interactions rather than
the isolated contracts.

| ID | Severity | Finding | Required resolution |
| --- | --- | --- | --- |
| R2-01 | high | The roadmap creates valuation ranges in research revisions while the existing Watchlist/Oracle's Lens read `metric_facts.metric_key='val.fair_value'`. Without one publication rule, the application has two conflicting “current” user intrinsic values. | Define the research revision as immutable decision history and an atomic publication path to the existing current manual fact; route Watchlist edits through the same service. Respect the canonical USD mapping. |
| R2-02 | medium | “Every update creates a revision” can create one immutable row per keystroke or encourage overwriting a server draft. | Define client-local draft behavior, explicit save boundaries, unsaved-change warning, and server concurrency at each save. |
| R2-03 | high | Notification dedupe is not defined for a 13F amendment that replaces a previously active filing and changes a user-visible action. A naive period/stock key either duplicates the alert or suppresses a material correction. | Define logical event identity, source version, correction/supersession semantics, and separate delivery idempotency. |
| R2-04 | medium | “Intrinsic-value threshold crossed” lacks prior-observation and hysteresis rules, so a price sitting near the boundary can alert daily or oscillate. | Require two canonical fresh observations, direction-aware crossing, configurable hysteresis/cooldown, and an initialization no-alert rule. |
| R2-05 | medium | Inbox dismiss/snooze is unconstrained. A user could permanently hide an overdue owned thesis, undermining the monitoring promise. | Preserve event history; allow permanent dismiss only for informational discovery, and bounded snooze for monitoring obligations. |
| R2-06 | medium | “Current Value Line report” has no freshness definition, so the 80% efficacy metric is not reproducible. | Add a visible configurable max-age policy with a documented product default; treat it as a freshness threshold, not a claim about vendor publication cadence. |
| R2-07 | medium | User-authored thesis, evidence, URLs, search/filter, batch IDs, and destination inputs have no length/count/rate boundaries. | Require schema limits, request-size limits, pagination caps, per-user rate limits for expensive/external operations, and abuse tests. |
| R2-08 | medium | Append-only research history conflicts with user privacy deletion unless retention/erasure behavior is stated. | Distinguish normal close/hide from account erasure; revoke destinations immediately and define tombstone/purge behavior without silently breaking financial source integrity. |
| R2-09 | medium | Copying a Value Line excerpt into every revision unnecessarily duplicates proprietary/user-private material and may outlive source access. | Snapshot only the permitted minimal decision evidence; keep proprietary document text behind the original access control and show unavailable provenance when access is gone. |
| R2-10 | medium | Manual portfolio review may accidentally calculate per-position value from a price whose currency is unknown, even if cross-currency totals are disabled. | Require known matching currency before any value/return calculation; otherwise show a typed currency-unavailable state. |
| R2-11 | low | Slack destination setup can itself send a test message. The roadmap must distinguish explicit user-requested verification from background delivery and current task authorization. | Require an explicit test action and consent in the product; use mocks in this task unless the user separately authorizes a real send. |
| R2-12 | low | The coverage queue defines priority but not a stable priority version, so results can reorder silently after code changes and become unauditable. | Version the priority policy and expose the rule/reasons on each queue item. |

## Round 2 disposition

All findings are accepted as real. The roadmap must be revised before Round 3.

## Round 3

Result: **FAIL — valid findings found after Round 2 remediation**

All Round 2 findings are addressed. Round 3 attacked the revised contracts
against the repository's current schemas and locked invariants.

| ID | Severity | Finding | Required resolution |
| --- | --- | --- | --- |
| R3-01 | critical | The intrinsic-value publication rule still says “demote the prior current slot” imprecisely. A global demotion would violate the locked per-period `metric_facts.is_current` contract; the current Watchlist endpoint already demotes too broadly. | Spell out the exact same-period/manual predicate and latest-read tiebreak. Make correcting the legacy path part of Phase 0/2. |
| R3-02 | high | A mistaken or abandoned active case can only become `pass`, polluting qualified-decision metrics and misrepresenting user judgment. | Add a terminal `voided` state with no investment decision, required reason, audit event, and metric exclusion. |
| R3-03 | high | Portfolio calculations require known price currency, but current `stock_prices` has no currency column. The roadmap promises a typed mismatch it cannot compute. | Add an explicit nullable currency migration/backfill policy; new provider writes must include validated currency, historical unknown stays unknown. |
| R3-04 | high | Existing one-to-one `notification_settings` and `notification_events` already power the filing-season digest. Replacing their meaning can lose current behavior or silently activate external email. | Define a compatibility migration: preserve legacy events, translate safe preferences to in-app only, and keep external channels disabled pending verification. |
| R3-05 | medium | “Email adapter” has no provider contract, so completion and transport security cannot be tested consistently. | Choose a V1 transport contract (TLS SMTP), required configuration, secret handling, timeouts, and failure classification. |
| R3-06 | medium | The successful EOD path is not an exit requirement; an implementation that labels every stock `blocked` could pass Phase 1. | Require a deterministic supported-equity fixture and configured-provider runtime probe proving fetch, currency, persistence, canonical read, and freshness. External coverage percentages remain efficacy metrics. |
| R3-07 | medium | `source_ref_id` historically means extraction/formula identifiers; using it for a research revision without updating the authoritative contract makes the polymorphic reference ambiguous. | Require PRD/model documentation of `source_type='manual'` + `source_ref_id=research_case_revision.id`, or add a typed reference field by migration. |
| R3-08 | medium | Closed/delisted stock handling is absent. A stock deactivation or identity review must not cascade-delete a case or silently refresh the wrong listing. | Restrict deletion, retain cases, disable automatic refresh for inactive/unresolved identity, and display a typed state. |
| R3-09 | medium | The roadmap requires exact Slack host/path validation but does not define webhook-secret key rotation behavior for existing ciphertext. | Require key-version on ciphertext, current+previous decrypt window, re-encryption workflow, and fail-closed unreadable-secret status. |
| R3-10 | low | The “120 days” Value Line threshold is configurable but no policy-version/time-of-evaluation is attached to a coverage result. Historical readiness could drift. | Persist freshness-policy version/evaluated-at with coverage results. |

## Round 3 disposition

All findings are accepted as real. The roadmap must be revised before Round 4.

## Round 4

Result: **FAIL — valid findings found after Round 3 remediation**

All Round 3 findings are addressed. Round 4 attacked multi-source workflows,
operator boundaries, and mutable projections.

| ID | Severity | Finding | Required resolution |
| --- | --- | --- | --- |
| R4-01 | high | An existing active case has only one `source_ref_json`. Opening it later from a different manager, Watchlist, or Lens mode would either discard the new context or overwrite the original origin. | Make origins append-only/idempotent many-to-one records; preserve initial and subsequent discovery context. |
| R4-02 | high | Inbox dismiss/snooze requires a durable logical action model, but no action identity/projection is defined. A computed-only list cannot reliably dedupe, snooze, correct, or audit actions. | Define user-owned Inbox actions with stable keys, source versions, priority reasons, state, snooze, correction, and history. |
| R4-03 | high | Admin behavior is unspecified. Existing admin power over operational data must not imply blanket access to private theses, valuations, destinations, or portfolios. | Deny user-content access to ordinary admin endpoints; expose aggregate operational metadata only. Any support-access mechanism is a separate audited/consented feature and out of scope. |
| R4-04 | high | Portfolio events do not define the current projection, concurrency, or position rules. Concurrent resize/close requests can corrupt quantity or event order. | Define long-only V1 states, fixed decimal constraints, expected-version concurrency, and atomic projection+event writes. |
| R4-05 | medium | DCF is called an input but its relation to immutable assumptions and published fair value is undefined, creating another possible valuation truth. | DCF remains a calculator draft; only an explicit save copies labeled assumptions/results into a research revision, and only that revision publishes current base value. |
| R4-06 | medium | Correcting the Watchlist writer alone is insufficient: all consumers must use the same latest-AS-OF tiebreak or they can show different current fair values. | Create one canonical valuation read/write service and add a source guard banning direct product reads/writes outside it. |
| R4-07 | medium | Append-only user notes provide no narrow remedy for accidentally saved secrets or sensitive personal content short of deleting the whole account. | Add a user-owned redaction workflow that removes content, preserves a non-content audit tombstone/hash, and never rewrites sourced financial facts. |
| R4-08 | medium | Stock ticker/name/identity can change after a decision. Rendering only current stock identity can rewrite historical meaning. | Snapshot canonical stock ID plus recorded ticker/name/exchange in each decision revision and label current identity separately. |
| R4-09 | low | Manager representativeness changes over time but the roadmap mentions only a current reviewed field. Historical scores and evidence could drift. | Version manager classification decisions with effective timestamps and persist the version used in each score/action. |

## Round 4 disposition

All findings are accepted as real. The roadmap must be revised before Round 5.

## Round 5

Result: **FAIL — valid findings found after Round 4 remediation**

All Round 4 findings are addressed. Round 5 attacked valuation semantics and
database-enforceable state.

| ID | Severity | Finding | Required resolution |
| --- | --- | --- | --- |
| R5-01 | high | The case still has `source_type/source_ref_json` while append-only origins now own source context. Two copies can diverge. | Keep one source-of-truth: origin rows, with immutable initial-origin identity on the case if needed. |
| R5-02 | critical | Saving `valuation_not_available` after a prior fair value does not publish a newer fact. Latest-value readers can silently continue showing the old value as current. | Publish an explicit newest manual null/tombstone fact with typed reason; readers select the newest row before inspecting value and must not fall through to an older manual value. |
| R5-03 | critical | Existing Watchlist treats a Value Line 18-month target fallback as fair value and calculates “MOS”, conflicting with the Oracle copy contract. | Separate user intrinsic value/MOS from system valuation reference/discount-to-reference in the canonical valuation result and UI; reconcile the authoritative PRD. |
| R5-04 | high | State/decision/review invariants are service prose only. A buggy writer could persist `monitoring + pass` or `closed + own`. | Require database CHECK constraints in addition to service validation and migration tests. |
| R5-05 | medium | Returning a monitoring case to research can leave the old published intrinsic value looking fully current. | Preserve it as “last user value, under review” with its date/state; alerts pause until a new monitoring decision is saved. |
| R5-06 | medium | A dismissed informational action has no rule for a materially newer source version. Permanent suppression could hide a new filing forever. | Scope dismissal to a logical source version; a materially new version creates/reopens a new action while preserving prior dismissal history. |
| R5-07 | low | The North-star event can be counted multiple times when one decided case is revised repeatedly. | Count distinct qualifying decision transitions/review decisions, not every saved revision; publish the metric definition/version. |

## Round 5 disposition

All findings are accepted as real. The roadmap must be revised before Round 6.

## Round 6

Result: **FAIL — four valid edge-condition findings remain**

All Round 5 findings are addressed. Round 6 tested schema constructability and
metric denominators.

| ID | Severity | Finding | Required resolution |
| --- | --- | --- | --- |
| R6-01 | high | `research_cases.initial_origin_id` plus `research_case_origins.case_id` creates an avoidable cyclic insertion/foreign-key problem. | Remove the reverse FK; derive the immutable first origin by ordered origin rows. |
| R6-02 | high | Research revisions are called append-only, but redaction/account erasure says content is removed. Both cannot be literally true. | Define privacy redaction/erasure as the narrow documented exception: overwrite authored content with a tombstone in one audited transaction while never mutating sourced financial facts or decision metadata. |
| R6-03 | medium | “Top 30” coverage is undefined when fewer than 30 eligible candidates exist. | Define denominator as `min(30, eligible candidates)` and report both counts. |
| R6-04 | medium | “User-entered cost” does not say unit cost vs total cost and can produce incorrect returns. | Choose an explicit field/meaning; V1 uses optional average unit cost, with no fees, lots, realized gain, or tax claim. |

## Round 6 disposition

All four findings are accepted as real. The roadmap must be revised before
Round 7.

## Round 7

Result: **FAIL — final invariant/time-semantics omissions found**

All Round 6 findings are addressed. The final contract read found four omissions
that would otherwise be left to implementer interpretation.

| ID | Severity | Finding | Required resolution |
| --- | --- | --- | --- |
| R7-01 | high | The roadmap references `AGENTS.md` but does not restate the no-user-raw-SQL/no-`eval` constraints in its own implementation gates. | Add them explicitly to API/query requirements. |
| R7-02 | high | Phase 0 includes parser fixes but the roadmap does not explicitly require preservation of immutable `metric_extractions`, normalized base-unit `value_numeric`, and field-level provenance during those fixes. | Add all three invariants to the phase/cross-phase gate. |
| R7-03 | medium | `next_review_at` is ambiguous: a value investor chooses a review date, while an instant introduces timezone/DST ambiguity. | Use `next_review_on` as a calendar date; materialize due actions in the user's IANA timezone, storing execution timestamps in UTC. |
| R7-04 | medium | A USD intrinsic-value threshold must not compare against a non-USD close merely because the price currency is known. | Require exact currency equality in alert eligibility; V1 research valuation therefore alerts only on USD price observations. |

## Round 7 disposition

All four findings are accepted as real. The roadmap must be revised before
Round 8.

## Round 8

Result: **PASS — no new valid finding**

All 61 findings from Rounds 1–7 were traced back to the revised roadmap. Round 8
then repeated the full seven-perspective attack without relying on the earlier
finding list.

| Perspective | Evidence checked | Result |
| --- | --- | --- |
| PO / value investor | Primary user, job, non-goals, decision states, MOS/reference separation, monitoring loop, measurable gates | Pass |
| 13F / financial-data SME | delay/cost-basis language, amendment corrections, manager representativeness versions, price currency, Value Line freshness, per-period fair-value publication | Pass |
| Database / concurrency | constructable non-cyclic ownership, partial uniqueness, state CHECKs, Decimal fields, optimistic versions, append-only events, redaction exception, migration rehearsal | Pass |
| Authorization / privacy / security | session-derived ownership, admin privacy boundary, cross-user evidence, webhook encryption/allowlist, email verification, SSRF/XSS controls, rate/size limits, erasure | Pass |
| Frontend / accessibility | daily Inbox, explicit ranking reasons, draft/save boundary, stale/missing/error states, navigation, narrow layout, focus/keyboard, honest copy | Pass |
| Jobs / operations | durable actions/outbox, source/delivery idempotency, correction events, retries, leases/recovery, readiness, provider blocking, rollback | Pass |
| Test / completion | phase exit evidence, supported EOD success path, external-dependency separation, exact canonical commands, requirement traceability | Pass |

Mechanical verification also passed:

- every authoritative reference named by the roadmap exists;
- stale superseded terms (`next_review_at`, `source_ref_json`,
  `initial_origin_id`, and the old lifecycle) are absent;
- all required locked invariants are stated in the implementation gates;
- `git diff --check` is clean.

## Final sign-off

**Granted for roadmap implementation.** This sign-off proves the roadmap has no
remaining issue discoverable by the defined adversarial method. It does not
claim that the roadmap's product implementation is complete; implementation
must undergo the same find-fix-re-review loop and final requirement audit.

## Implementation adversarial review

The delivered code then underwent the same seven-perspective review. Each round
was repeated after its fixes rather than treating test success as proof of
product correctness.

| Round | Result | Material findings resolved |
| --- | --- | --- |
| I1 — ownership/data truth | Fail, fixed | Cross-user valuation overlays, empty-index sync semantics, canonical valuation source guard |
| I2 — delivery/concurrency | Fail, fixed | Non-durable send leases, ambiguous resend risk, missing failure visibility and rotation audit |
| I3 — security/operations | Fail, fixed | Account erasure, durable abuse limits, independent scheduler, secret/config fail-closed behavior |
| I4 — runtime/frequency | Fail, fixed | Dev/build artifact collision, accepted-but-inert daily/weekly digests, in-app frequency contract and settings hydration |
| I5 — event completeness | Fail, fixed | Filing-season summary bridge into scoped logical notifications and correction-safe identity |
| I6 — valuation alerts | Fail, fixed | Valuation/policy changes posing as crossings, cross-destination boundary disagreement, stale/currency rejection |
| I7 — decision lifecycle | Fail, fixed | Monitoring valuation edits retaining a stale decision; such edits now reopen research and pause alerts |
| I8 — resumed monitoring | Fail, fixed | A re-confirmed case could reuse pre-pause alert state; monitoring revision identity now resets the crossing boundary |
| I9 — replica concurrency | Fail, fixed | Two scheduler replicas could race initial alert-state creation; a user/stock transaction lock now serializes evaluation |
| I10 — closing gate | Fail, fixed | A committed-session test omitted new review-row cleanup and a price-evidence lookup bypassed the canonical source guard; both root causes were fixed |
| I11 — repeat matrix | Pass | 1433 backend and 216 frontend tests, migration round trip/head upgrade, lint, production build, post-build browser smoke, and mechanical checks found no new valid issue |

## Implementation sign-off

**Granted.** All valid implementation findings were fixed and the complete
review matrix was repeated after the last change. No reproducible correctness,
authorization, financial-semantics, concurrency, privacy, operations, migration,
runtime, or workflow defect remains in roadmap scope. External credentials,
licensed proprietary acquisition, production deployment, and real delivery are
configuration/authority boundaries rather than unperformed implementation work.
