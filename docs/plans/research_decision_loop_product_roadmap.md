# ValuePilot Research Decision Loop — product roadmap

Status: delivered and verified after roadmap and implementation adversarial review  
Owner: Product / Engineering  
Version: 1.1  
Last updated: 2026-07-20

## 1. Executive decision

ValuePilot's next product is not another 13F data browser. It is an auditable
research-decision loop for a serious, self-directed long-term investor:

```text
trusted filing signal
    -> prioritized research candidate
    -> fundamental and price coverage
    -> independent valuation and disconfirming evidence
    -> explicit user decision
    -> monitored thesis and scheduled review
```

The immediate engineering program is **Research Decision Loop V1**. Its first
release couples a targeted coverage flywheel with a Research Inbox; later
releases add the company research workspace, notification habit loop, and manual
portfolio/decision journal. Quant execution remains gated by the separate
data-sufficiency and out-of-sample research protocol.

This document controls product sequencing and acceptance for that program. It
does not redefine canonical metric semantics: the mapping spec remains supreme.
Before a phase introduces a new system/storage contract, that contract must be
incorporated into `docs/prd/value-pilot-prd-v0.1.md` in the same change.

## 2. Evidence-based baseline

### 2.1 Proven strengths

The current branch already contains:

- unattended EDGAR ingestion, historical backfill, amendment authority,
  attribution, CUSIP enrichment, quality reports, retries, watchdog recovery,
  and consumer readiness;
- 82 tracked value-investor managers;
- Oracle's Lens, new-buy clusters, filing-season digest, Watchlist × 13F;
- manager list, Holdings, Activity, Buys, Sells, History, and manager × stock
  timeline views;
- Value Line ingestion, normalized `metric_facts`, Piotroski calculations,
  screening, manual intrinsic value, DCF, and document review surfaces.

The isolated zero-database rehearsal produced 1,209 filings, 87,027 product
holdings, 81,610 ownership changes, and 7,934 Oracle's Lens signals. It completed
the final Dataroma reconciliation with zero suspected ValuePilot defects and
zero unclassified material differences. The final closing gate passed 1,332
backend tests and 198 frontend tests, lint, and production build.

### 2.2 Binding product constraints

Read-only inspection of the shared development database on 2026-07-20 found:

| Dataset | Current state |
| --- | ---: |
| Stocks | 2,841 |
| Active tracked managers | 82 |
| 13F filings | 1,209 |
| `holdings_13f` rows, including retained parse history | 136,966 |
| Oracle's Lens signals | 7,937 |
| PDF documents | 3 |
| Current `metric_facts` | 1,133 |
| Stocks with current facts | **3** |
| `stock_prices` rows | **2** |
| Stocks with price data | **1** |
| Watchlist memberships | **1** |

Consequences:

1. 13F discovery is materially more mature than fundamental and market-data
   coverage.
2. A broad quality/valuation UI would mostly display missing data.
3. Full-market acquisition is unnecessary for the first useful workflow;
   coverage should follow explicit user interest and high-value candidates.
4. The home route is only ticker search, while the product contract calls the
   Watchlist the daily decision surface. Navigation and workflow are not yet
   aligned.
5. Current product documents and backlog mix implemented, stale, resolved, and
   future work; they cannot be used as an execution queue without reconciliation.

## 3. User, problem, and value proposition

### 3.1 Primary user

A serious self-directed long-term investor who:

- follows a selected set of value-oriented managers;
- researches roughly 20–100 companies and owns a smaller subset;
- values source provenance, conservative language, and explicit uncertainty;
- wants to reduce low-value idea searching while preserving independent
  judgment;
- uses EOD data and does not need an intraday trading terminal.

Admin/operator workflows remain necessary but are not the user value metric for
this program.

### 3.2 Job to be done

> When a potentially meaningful investor or valuation event occurs, help me
> decide whether this company deserves work, show which evidence is missing,
> let me record a falsifiable thesis and valuation, and bring the case back when
> the evidence or review date changes.

### 3.3 Differentiated value

ValuePilot will not try to win on raw 13F tables, maximum manager count, or
opaque rankings. Its product wedge is:

```text
audited EDGAR lineage
+ investor-behavior context
+ Value Line provenance
+ user-owned intrinsic value
+ explicit disconfirming evidence
+ versioned decisions and reviews
```

## 4. Product principles and hard boundaries

1. **Research prompt, never recommendation.** No 13F event or score is labeled a
   buy/sell signal.
2. **User value is independent judgment.** System-derived references and Value
   Line targets are never relabeled as user fair value or margin of safety.
3. **Missing data is a visible state.** Missing, stale, blocked-by-license, and
   failed ingestion are distinct.
4. **Point-in-time truth is preserved.** Research history and source evidence
   are immutable; corrections append revisions.
5. **User ownership is enforced server-side.** IDs are never sufficient
   authorization for research, portfolio, follow, or notification resources.
6. **Targeted coverage before broad coverage.** Work follows open research cases,
   Watchlists, and top-ranked discoverable candidates.
7. **Explainability before composite scoring.** Consensus and distinctiveness
   are separate lenses; both expose inputs and caveats.
8. **No unlicensed acquisition.** The system can request, prioritize, accept,
   parse, and audit user-authorized documents. It cannot assume permission to
   scrape or redistribute proprietary content.
9. **External delivery is opt-in and fail-closed.** No configured destination or
   consent means no attempted delivery.
10. **No trading rails.** Portfolio records support reflection and review, not
    broker execution, position truth claims, or tax accounting.

## 5. Decision model and primary metric

### 5.1 North-star metric

`qualified_research_decisions_per_active_user_per_week`

A qualified decision requires all of:

- a stock and decision date;
- an explicit decision of `watch`, `pass`, or `own`;
- a written thesis or pass reason;
- a user intrinsic-value range or an explicit `valuation_not_available` reason;
- at least one risk or disconfirming item;
- evidence/provenance links or an explicit evidence-gap record;
- a next-review date for `watch` and `own`.

The metric is diagnostic, not a productivity quota. The UI must never encourage
low-quality decisions to increase it.

The versioned metric counts distinct qualifying decision transitions and later
explicit review decisions, not every revision saved while a case stays in the
same state. Voided cases, autosave attempts, and system-generated drafts never
count.

### 5.2 Funnel metrics

| Metric | Purpose |
| --- | --- |
| Candidate-to-case conversion within 14 days | Whether discovery produces work |
| Median time from queued case to decision | Workflow friction |
| Open cases with fresh price | Market-data readiness |
| Top-30 candidates with usable fundamentals | Fundamental coverage |
| Decisions with complete provenance | Trust and auditability |
| Notifications opened into a relevant case | Notification usefulness |
| Notification duplicate/suppression rate | Noise control |
| Overdue `watch`/`own` reviews | Whether the monitoring loop works |

### 5.3 Guardrail metrics

- zero cross-user resource disclosure;
- zero current facts globally deduplicated or mutated outside their locked
  per-period rules;
- zero user-facing claims of inferred guru cost basis;
- zero external sends without enabled consent and configured destination;
- zero portfolio copy implying broker reconciliation;
- zero hidden missing-data substitutions.

## 6. Information architecture

Primary navigation after V1:

```text
Research
  Home / Research Inbox
  Research Cases
  Watchlists
  Oracle's Lens
  13F Managers
  Screener

Companies
  Stock Research Workspace
  Documents

Portfolio
  Manual Portfolios
  Review Journal

Operations (admin only)
  13F Admin
  Coverage Queue
  Calibration
  Upload
```

Ticker search remains globally accessible. It is not the complete home page.

## 7. Domain contracts

Detailed schemas are finalized in the authoritative PRD and migrations before
production code. These are the roadmap-level contracts the implementation must
preserve.

### 7.1 Research case

`research_cases` is user-owned and represents one research cycle for one stock.
The case row is the mutable current projection used for filtering and Inbox
ordering; immutable revisions and events are the historical record.

Required behavior:

- lifecycle states are `queued`, `researching`, `monitoring`, `closed`, and
  `voided`;
- valid transitions are `queued -> researching|closed|voided`,
  `researching -> monitoring|closed|voided`, and
  `monitoring -> researching|closed|voided`; `closed` and `voided` are terminal,
  and a later revisit creates a new research cycle;
- `queued`/`researching` have no current decision; `monitoring` requires
  `watch` or `own`; `closed` requires `pass`;
- `monitoring -> researching` retains the old decision only in immutable
  history while the current projection becomes undecided for the new review;
- `voided` has no investment decision, requires a reason, remains in the audit
  trail, and is excluded from research-decision metrics;
- at most one **active** case in `queued|researching|monitoring` exists per
  `(user_id, stock_id)`, enforced by a PostgreSQL partial unique index;
- duplicate create is idempotent and returns the existing active case plus a
  typed `created=false` result;
- a closed case may be followed by a new cycle; prior history remains;
- `research_case_origins` records every initial or later discovery context as an
  append-only, idempotent source tuple. Opening an existing case from a new
  manager, Lens mode, Watchlist, or screener appends an origin/event instead of
  overwriting the first source or discarding the new context;
- the immutable initial origin is derived from origin rows ordered by
  `(created_at, id)`; the case does not hold a reverse foreign key that would
  create a cyclic insert dependency;
- `next_review_on` is a calendar `DATE`, required in `monitoring`, null in
  `closed`, and validated
  in the same transaction that writes the projection and revision;
- state and decision changes atomically append a revision and audit event.

### 7.2 Research revisions

`research_case_revisions` is append-only. Each row contains the complete
decision snapshot required to reproduce what the user believed at that time:

- thesis;
- variant/disconfirming view;
- risks and evidence references;
- user intrinsic-value low/base/high and currency, or a typed unavailable
  reason. Money is represented by fixed-precision decimal values and serialized
  as decimal strings, never binary float;
- decision and decision reason;
- material assumptions;
- review date;
- revision number and author/timestamps;
- the canonical stock ID plus the ticker, company name, exchange, and listing
  identity displayed when the revision was saved. Current identity may be shown
  separately but never silently replaces the recorded identity.

Updating a case creates a new revision. It never rewrites a prior revision.
Optimistic concurrency rejects an update based on a stale revision number with
a typed `409` response.

Editing happens in a client-local draft. A server revision is created only on
an explicit Save/Decide action; navigation with unsaved changes warns the user.
Each save supplies the expected head revision number, and the unique
`(case_id, revision_number)` constraint plus one transaction prevents two
writers from publishing the same next revision.

Draft revisions may omit valuation. If either range edge is supplied, both
edges and the base value are required and must satisfy
`low <= base <= high`; currency is required with any monetary value. A qualified
`watch`, `own`, or `pass` decision requires the complete range or one typed
`valuation_not_available` reason, never a silent blank.

#### Current intrinsic-value publication

Research revisions are the immutable source for what supported a historical
decision. The existing user-scoped `metric_facts` key `val.fair_value` remains
the current operational base intrinsic value consumed by Watchlist and Oracle's
Lens. A saved revision with a base value atomically:

1. appends the immutable revision;
2. demotes only rows matching the same `(user_id, stock_id, metric_key,
   period_type, period_end_date, source_type='manual')` slot under the locked
   per-period reconciliation contract;
3. inserts the new manual fact with `source_ref_id` pointing to the revision;
4. updates the case projection and appends the case event.

The Watchlist fair-value edit uses this same application service: it creates or
opens an active case, saves a valuation draft revision, and publishes the fact.
It does not maintain a second write path. V1 research valuation is USD because
the authoritative mapping defines `val.fair_value` as USD. Supporting another
currency requires a mapping/PRD decision before code; it is never coerced to
USD.

If that edit, or an explicit DCF save, changes the valuation of a case already
in `monitoring`, the same transaction moves the case back to `researching` and
clears its current decision and review date. The prior monitoring judgment
remains intact in its immutable revision, while the new value is labeled under
review and cannot drive intrinsic-value alerts until the user records a new
qualified monitoring decision.

Multiple current manual facts may therefore coexist across AS-OF dates by
design. Every current-value consumer uses the locked read tiebreak
`period_end_date DESC NULLS LAST, created_at DESC, id DESC`. The existing
Watchlist endpoint's broad demotion is corrected before this service ships.
The authoritative PRD/model contract also records that, for
`source_type='manual'` and `metric_key='val.fair_value'`, a non-null
`source_ref_id` may identify the publishing `research_case_revision`; it is not
silently interpreted as an extraction or formula run.

One canonical valuation application service owns every product read and write
of the current user `val.fair_value`; Watchlist, Oracle's Lens, stock summary,
and the workspace call it. A source guard rejects new direct product
reads/writes outside sanctioned low-level fact/reconciliation modules.

Saving an explicit `valuation_not_available`/clear decision publishes a newer
manual `val.fair_value` fact for that AS-OF slot with `value_numeric=NULL` and a
typed reason/revision reference in `value_json`. Readers select the newest
manual row **before** inspecting its value; this tombstone suppresses older
manual values instead of falling through to them. A Value Line target may still
appear separately as a system valuation reference, never as user intrinsic
value.

The canonical valuation result has two non-interchangeable branches:

- `user_intrinsic_value` -> may produce user margin of safety;
- `system_valuation_reference` -> may produce only
  discount/premium-to-reference with source/date/type.

Watchlist and Oracle's Lens must not calculate or label MOS from a Value Line
target. Phase 0 reconciles the conflicting Watchlist PRD fallback language and
Phase 2 migrates the UI/API through this result contract.

DCF remains an unsaved calculator draft. Only an explicit Save to research
copies labeled DCF inputs, method/version, and result into a new case revision;
only that saved revision may publish its selected base value through the
canonical valuation service. Merely visiting or changing DCF inputs never
changes Watchlist fair value.

### 7.3 Evidence references

Evidence references identify a supported source type and durable internal ID:

- Value Line document/fact;
- 13F filing/holding/change/signal;
- stock-price observation;
- user-authored note;
- external URL entered by the user.

An evidence reference is not treated as proof merely because an ID exists. The
API verifies that the object exists, is visible to the user, and matches the
case stock when the source is stock-specific. A fact whose source document is
owned by another user cannot expose that document, snippet, or derived private
content merely because the stock identity is shared. Historical revisions keep
a permitted minimal evidence snapshot (`source_type`, durable ID, source date,
label, and the specific recorded numeric/text claim) alongside the reference.
Proprietary excerpts are not copied into each revision; they remain behind the
original document/fact access controls. The UI renders the recorded claim by
default and links to the source only while access remains valid. Lost access is
an explicit `source_unavailable` state. An optional current comparison is
labeled as current and never replaces history.

User-entered external links accept only normalized `https` URLs in V1. They are
never fetched by the server, are rendered as untrusted external links with the
destination domain visible, and use safe new-window isolation. Removing one
from a current draft does not remove it from historical revisions.

Append-only history has one narrow, documented privacy exception for
accidentally saved secrets, sensitive personal content, or account erasure. An
audited redaction transaction overwrites only user-authored content with a
non-content hash/reason/actor/timestamp tombstone. It never alters sourced
financial facts, stock/source identity, state transitions, or decision metadata,
and never pretends the revision did not exist.

### 7.4 Research Inbox actions

`research_inbox_actions` is a user-owned current projection backed by immutable
action events. Each action has:

- a stable logical key, action family, subject, source version, and optional
  superseded-action link;
- a priority-policy version, matched rule, rank components, and plain-language
  reason;
- `open`, `snoozed`, `dismissed`, `completed`, or `superseded` state;
- `snoozed_until`, first/last observed timestamps, and target case/evidence
  links.

Regeneration upserts the current projection idempotently and appends an event
only on a material change. It never deletes prior evidence. Informational
discovery can be dismissed; monitoring obligations follow the bounded-snooze
rule and reappear after expiry. A corrected 13F source supersedes the prior
action rather than silently rewriting it.
Dismissal is scoped to the logical source version: a materially newer filing,
score version, or evidence change may create/reopen a new action while the prior
dismissal remains in history.

### 7.5 Coverage priority

Coverage priority is explainable and deterministic:

1. open `own` cases;
2. open `watch` decisions and overdue reviews;
3. `researching` cases;
4. queued cases;
5. Watchlist members;
6. top Oracle's Lens candidates selected by an explicit lens;
7. all remaining stocks are outside the targeted queue.

For ties, use oldest unmet requirement, then stock ID. No signal score alone may
outrank an owned case.

Coverage requirements are separate by kind:

- `eod_price`;
- `value_line_current_report`;
- `valuation_input`;
- `identity_review`;
- `cusip_review`.

Each item reports `ready`, `missing`, `stale`, `blocked`, `in_progress`, or
`failed`, with reason, observed timestamp, freshness policy, and permitted next
action. Proprietary report acquisition may only become `in_progress` through a
configured, authorized source or explicit user upload.

The priority algorithm has a persisted/exposed `priority_policy_version`, and
each item returns the matched rule and evidence. Recomputing under a new version
never rewrites the historical policy attached to completed work.

Value Line “current” means the latest permitted report is no older than the
configured product freshness threshold. V1 defaults the threshold to 120
calendar days, displays the report date and threshold, and treats the number as
a ValuePilot freshness policy rather than a claim about the vendor publication
schedule.
Coverage results persist the freshness-policy version and evaluation timestamp,
so a later threshold change does not rewrite what an earlier readiness result
meant.

### 7.6 Price freshness

- EOD price means the latest available market close, never real time.
- Trading-calendar awareness distinguishes a weekend/holiday from staleness.
- An active research or Watchlist stock is `fresh` when its latest price is for
  the most recent expected trading session under the configured market calendar.
- Missing exchange/calendar mapping produces `unknown_freshness`, not `fresh`.
- Reads choose one canonical observation deterministically by source priority,
  `price_date`, and `created_at`; the policy is shared by all consumers.
- Refresh is batched, idempotent, rate-limited, observable, and never triggered
  once per table row.
- `stock_prices` gains a nullable ISO 4217 currency field. Historical rows are
  left `NULL` unless a source-backed deterministic backfill exists; new provider
  writes require a validated currency. Unknown is never inferred from ticker
  text. Inactive stocks or stocks with unresolved listing identity are retained
  for research history but automatic refresh is disabled with a typed reason.

### 7.7 Oracle's Lens modes

The existing blended score remains available as evidence but is not presented
as the one investment truth.

- **Consensus lens:** independent-manager breadth, persistence, and meaningful
  shared ownership, with index-like/quant/shared-attribution exclusions.
- **Distinctive lens:** few-manager, high portfolio weight, concentration,
  persistence, and manager fit, with crowding displayed separately.

Both modes:

- expose component values and exclusions;
- show manager representativeness and incomplete-filing caveats;
- never infer current ownership or transaction price;
- use stable, versioned scoring definitions;
- can be reproduced from persisted inputs.

`thirteenf_representativeness` is reviewed manager metadata with values
`faithful`, `partial`, `unrepresentative`, or `unknown`. It affects display and
documented scoring weights only after human review; unknown never silently
means faithful.

Classification is versioned with reviewer, rationale, evidence, and effective
timestamp. Persisted score components and Inbox actions record the
classification version they used, so a later taxonomy correction can trigger a
new score/action without rewriting the historical explanation.

### 7.8 Manager follows

- `manager_follows` is unique by `(user_id, manager_id)` and user-owned.
- Following affects the user's inbox and subscriptions, never global ingestion
  or canonical manager ranking.
- Unfollow does not delete prior research evidence or delivered-event history.

### 7.9 Notifications

Events are produced from committed domain changes through an outbox-style
durable record; sending is not performed inside the business transaction.
Logical notifications, user subscriptions/destinations, in-app read state, and
per-channel delivery attempts are distinct records. The existing deployment
operations webhook is not a user research destination and must never receive
user research content implicitly.

A logical domain event has a stable event family and subject key plus an
explicit source version. For 13F changes the source version includes the active
filing accession and authority/parse result. If an amendment supersedes a
previously notified action, the system emits one linked `correction` event that
references the superseded logical event; it neither silently mutates the old
notification nor replays it as an unrelated duplicate. Delivery attempts have
their own idempotency key
`(logical_notification_id, destination_id, content_version)`.

Required event families:

- followed manager filed;
- followed manager new/add/reduce/exit affecting a Watchlist or open case;
- user intrinsic-value threshold crossed using fresh EOD price;
- research review due/overdue;
- data coverage completed or failed for an open case.
- filing-season summary scoped to followed managers, Watchlists, and open cases.

Intrinsic-value price alerts require two consecutive canonical, fresh EOD
observations and a direction-aware crossing from one side of the configured
boundary to the other. The first observation initializes state without
alerting. Hysteresis and cooldown prevent boundary oscillation; stale,
unknown-currency, currency-mismatched, or same-session duplicate observations
cannot trigger. Because V1 research intrinsic value is USD, only USD price
observations are eligible. State binds the observation to the exact user
intrinsic-value fact ID, monitoring research-revision ID, and threshold/
hysteresis values; a change to any of them reinitializes the boundary without
an alert, so a user edit or newly confirmed decision cannot masquerade as a
market-price crossing. Threshold,
hysteresis and logical cooldown are one user-level event policy synchronized
across destinations; channel frequency, timezone and quiet hours remain per
destination. Evaluation serializes the one user/stock alert projection before
its first insert or update so concurrent scheduler replicas cannot duplicate or
lose initialization.

Delivery requirements:

- in-app is always available and has durable `read_at` / dismissal state;
- a Slack destination is user-owned. Its webhook secret is encrypted at rest
  with a configured, versioned application key, returned only as a masked label,
  and can be rotated or revoked. V1 accepts only HTTPS Slack webhook URLs on the
  exact approved host/path family, disables redirects, resolves/fetches only at
  send time through the hardened adapter, and otherwise rejects the destination;
- a Slack test message is sent only by a separate, explicit user confirmation
  action. Automated background setup never sends one, and deterministic mocks
  are the acceptance mechanism unless a real send is separately authorized;
- an email destination remains `pending_verification` until a short-lived,
  single-use, hashed verification challenge is completed. No existing account
  email is assumed verified merely because login succeeds;
- when the encryption key or channel provider is unavailable, destination
  creation/activation fails closed and existing destinations become visibly
  `configuration_blocked`; no plaintext fallback is allowed;
- ciphertext records carry a key version. The service accepts a bounded
  current-plus-previous decrypt window during rotation, provides an audited
  re-encryption job, and marks an unreadable secret `configuration_blocked`
  without attempting delivery;
- V1 email transport is TLS-required SMTP with configured host, port, sender,
  credentials, connection/read timeouts, and redacted typed failure classes.
  Missing TLS/provider configuration keeps email disabled;
- per-event subscription, frequency, IANA timezone, quiet hours, cooldown, and
  enablement are user-controlled. In-app history is immediate; external
  `daily_digest`/`weekly_digest` delivery is a derived, catch-up, idempotent
  logical notification over a recorded source range;
- quiet-hour and digest calculations use a DST-aware timezone library and store
  each scheduled attempt as UTC;
- idempotency key prevents duplicate delivery across retries;
- each attempt stores status, provider response classification, attempt count,
  and next retry without storing credentials;
- the lease/attempt event commits before a provider call. Since V1 Slack/SMTP
  cannot accept an application idempotency key, an expired lease or unexpected
  adapter exception becomes visible `delivery_outcome_unknown` and is not
  blindly resent;
- permanent failures stop retrying and remain visible;
- notification copy links to the evidence/case and never says “buy signal”.

Migration preserves all existing `notification_events`. Safe legacy preferences
become immediate in-app history only, retaining the old frequency label solely
for reversible migration audit; no legacy `channel='email'` row
activates external email without destination verification. The existing filing
season digest remains readable and also emits one scoped, idempotent logical
notification when the user has relevant items.

### 7.10 Manual portfolio and journal

- portfolios and positions are user-owned;
- positions are explicitly labeled manual and may be stale;
- V1 positions are long-only: quantity is positive while open, shorts are
  rejected, and closing is a typed event rather than a negative quantity;
- quantities and optional user-entered **average unit cost** are fixed-precision
  decimals, explicitly currency-labeled, and never derived from 13F. It excludes
  fees, lots, realized gain, and tax meaning;
- a position can link to the research case/revision that supported the user's
  decision;
- closing or resizing a position appends a journal event with optional reason;
- each position is a mutable current projection with an expected version.
  Create/resize/close atomically validate the prior version, append an immutable
  event, update the projection, and reject stale writers with typed `409`;
- review views compare current evidence against the recorded thesis and
  valuation without rewriting history;
- no broker balance, execution, tax-lot, realized-P&L, or tax accuracy claim.
- V1 does not perform FX conversion. It displays per-position/per-currency
  values and never presents a cross-currency portfolio total or return as if the
  currencies were comparable.
- even a single-position value/return is calculated only when the canonical
  price currency is known and equals the position currency. Otherwise the UI
  shows `price_currency_unavailable` or `currency_mismatch` and performs no
  arithmetic.
- stock deactivation, delisting, or identity review never cascades a portfolio
  or case away. It stops automatic valuation refresh and displays the preserved
  manual state plus the typed identity/market-data limitation.

## 8. Delivery roadmap

Durations express sequencing and expected size, not a promise detached from
evidence. A phase exits only when its gate passes.

### Phase 0 — Product truth and trust gates (1–2 weeks)

Deliver:

- reconcile README, v0.1 plan, Watchlist status, Oracle plan, and Backlog against
  current code;
- incorporate Research Decision Loop contracts into the authoritative PRD;
- publish the Consensus vs Distinctive ranking thesis and scoring versions;
- complete human review of scoring-relevant manager taxonomy and
  representativeness;
- resolve or explicitly decide the active correctness gaps that could taint the
  workflow: Value Line industrial percentage normalization, annual-table
  alignment before historical expansion, `13F-NT/A` ingestion semantics,
  failed-parse retry eligibility, amendment rule-2 ordering, full real-body
  quarterly integration test, and product-query source guard;
- correct the existing Watchlist fair-value write path so it never globally
  demotes current `metric_facts` across AS-OF periods;
- add the canonical valuation source guard before migrating product consumers;
- create a coverage-source decision record covering license, retention,
  provenance, rate limits, and permitted automation.

Exit gate:

- documentation describes the current product rather than historical intent;
- no unresolved high-severity issue;
- every medium signal/data-truth issue above is fixed or has an explicit PO
  disposition and visible product caveat; user input is required only for new
  authority, licensing, or a contradiction with a locked decision;
- new domain contracts are approved in the authoritative PRD;
- existing canonical suites remain green.

### Phase 1 — Targeted coverage foundation (2–5 weeks)

Deliver:

- coverage-priority service and admin queue;
- canonical price read policy and batched EOD refresh for active research,
  Watchlist, and top candidate stocks;
- market-calendar-aware freshness states;
- Value Line coverage request/upload path with authorization and provenance;
- weekly forward archive only when the coverage-source decision authorizes it;
- coverage summary APIs and UI states.

Implementation exit gate:

- 100% of open cases have either a fresh EOD price or a typed reason explaining
  why not;
- 100% of the selected top 30 candidates have an evaluated fundamentals
  requirement, visible status, provenance/freshness result, and a permitted next
  action; `blocked` is visible and never counted as covered;
- all coverage work is deduplicated, observable, retryable, and source-legal;
- empty and failure states are browser verified.
- a deterministic supported-equity fixture and a configured-provider runtime
  probe prove the complete EOD path: fetch, validated currency, persistence,
  canonical read, and freshness classification. An implementation that labels
  every item blocked cannot pass.

Post-configuration efficacy target:

- the denominator is `min(30, eligible selected candidates)` and both the
  eligible count and evaluated count are reported;
- that selected set reaches at least 80% usable current fundamentals
  after an authorized source or user-provided corpus is available. This metric
  measures deployed data efficacy; lack of third-party authorization cannot be
  disguised as implementation success or used to trigger unlicensed access.

### Phase 2 — Research cases and Research Inbox (3–6 weeks)

Deliver:

- migrations/models/APIs for cases, immutable revisions, evidence, and events;
- Research Cases list with lifecycle, filters, overdue state, and coverage;
- home becomes Research Inbox while retaining ticker search;
- action priority: overdue owned/watch reviews, material case events, new filing
  actions affecting user scope, incomplete research, then new candidates;
- one-click create/open from Oracle's Lens, Watchlist, manager holding, screener,
  and stock summary;
- source context and lens mode survive the transition.

Exit gate:

- a user can identify the top three next actions in ten seconds in moderated or
  deterministic acceptance testing;
- duplicate clicks and concurrent requests create one active case;
- every user-owned API has cross-user authorization tests. Touched legacy
  Watchlist/stock-pool endpoints migrate to session-derived ownership or receive
  an explicit compatibility boundary that never trusts a query `user_id`;
- the Inbox explains why each action is ranked and supports dismiss/snooze
  without deleting evidence.
- permanent dismissal is limited to informational discovery actions. Case
  monitoring/review obligations may be snoozed for at most 30 days per action;
  snooze is audited and never deletes or permanently suppresses the obligation.

### Phase 3 — Unified company research workspace (6–10 weeks)

Deliver one stock-centric workspace with:

- business and data-freshness summary;
- Value Line facts with report date, original evidence, conflicts, and missing
  items;
- Piotroski and existing calculated quality measures;
- 13F holders, changes, streaks, manager/filing caveats, and both Lens modes;
- user intrinsic-value low/base/high, assumptions, and price-to-value display;
- thesis, variant view, risks, evidence, decision, and next review;
- revision comparison and audit history;
- DCF as an input tool, not an automatically accepted answer.

Exit gate:

- a user can take one candidate from discovery to a qualified decision without
  leaving the application;
- older revisions render exactly as recorded even when current facts change;
- system reference values and user intrinsic value are visually and
  semantically distinct;
- all unsupported/missing/provenance states are verified in browser acceptance.
- direct routes, refresh, back/forward navigation, and shareable non-sensitive
  filters preserve the expected case/stock context.

### Phase 4 — Habit loop and configurable delivery (10–13 weeks)

Deliver:

- user manager follows;
- notification preferences and subscriptions;
- durable event production, dedupe, cooldown, quiet hours, retry, and audit;
- in-app inbox;
- Slack and email adapters that activate only with valid configuration and
  consent;
- filing-season summaries scoped to followed managers, Watchlists, and open
  cases instead of the entire manager universe.

Exit gate:

- replaying the same source event produces one logical notification;
- failure/retry tests prove no silent loss or duplicate external sends;
- unconfigured and disabled channels make zero network attempts;
- every delivered item links to relevant evidence and can be muted;
- no secrets appear in logs, payload audit, API responses, or frontend state.

### Phase 5 — Manual portfolio and decision journal (13–16 weeks)

Deliver:

- manual portfolios and positions;
- link positions to the supporting research case/revision;
- review calendar and overdue thesis views;
- append-only position/journal events for open, resize, close, and review;
- post-mortem comparison of original decision, subsequent revisions, and current
  evidence.

Exit gate:

- the complete lifecycle from candidate to owned/pass decision to later review
  is auditable;
- historical decisions and position events survive edits and closures;
- permissions, decimal handling, currency labels, and stale manual data states
  are tested;
- no UI or API claims broker, execution, tax-lot, or tax correctness.

### Phase 6 — Quant research dependency only (parallel data obligation)

Allowed now:

- perform the pre-existing 1-R0 data-sufficiency/power audit;
- start authorized weekly Value Line forward archiving because missed vintages
  cannot be recovered;
- record the procurement decision for survivorship-free fundamentals/prices.

Not unlocked by this roadmap:

- PIT engine beyond the approved 1-R0 gate;
- factor/strategy claims without sufficient data;
- backtest UI, trading cockpit, IBKR integration, or automated execution.

## 9. Cross-phase engineering requirements

### 9.1 Database and migration safety

- PostgreSQL is the behavioral target; SQLite-only evidence is insufficient.
- `metric_facts` remains the only queryable financial-fact source of truth;
  `metric_extractions` remains immutable, and no global `is_current` deduplication
  is permitted.
- Parser fixes normalize `value_numeric` to canonical base units and preserve
  `document_id`, `page_number`, and `original_text_snippet` provenance for every
  parsed metric.
- New enum-like fields have database checks or reference tables where domain
  integrity matters.
- Database CHECK constraints enforce the case matrix: queued/researching have
  no decision; monitoring has `watch|own` plus review date; closed has `pass`
  and no review date; voided has no decision/review date and a non-empty reason.
  Services validate the same rules for typed errors, but are not the only guard.
- Uniqueness and partial indexes enforce one active case and delivery dedupe.
- Foreign-key delete behavior is explicit; immutable history is restricted or
  soft-retained, not cascaded away accidentally.
- Money uses fixed precision, never binary float, in new valuation/portfolio
  fields.
- Every migration includes downgrade logic unless a documented irreversible
  data transformation is separately approved.
- Upgrade/downgrade/upgrade is tested on representative data.

### 9.2 API and authorization

- Derive the current user from the authenticated session/token. New APIs do not
  accept `user_id` as authority.
- Ordinary admin endpoints do not grant access to private theses, valuations,
  evidence notes, notification destinations, or portfolios. Admin operations
  expose aggregate queue/health metadata only. Support impersonation/content
  access would require a separate explicit-consent, time-bounded audit design
  and is out of scope.
- Return typed 404/409/422 responses for ownership, concurrency, invalid state,
  and validation failures.
- Pagination, stable ordering, and bounded filters are required for lists.
- Idempotency is explicit for create, event generation, coverage work, and
  delivery.
- User-provided text is rendered as text, not trusted HTML.
- User filters/rules compile to bounded SQLAlchemy expressions; no raw SQL is
  constructed from user input. Formula or content evaluation never uses
  unrestricted `eval`/`exec`.
- External URLs are validated and never fetched server-side merely because a
  user attached them as evidence.
- Schemas enforce documented field sizes, list cardinalities, batch caps, and
  pagination limits. Expensive refresh, upload, destination verification, and
  delivery-test operations have per-user rate limits and abuse-path tests;
  oversized requests fail before allocating unbounded work.
- Normal UI actions close or hide records without erasing immutable financial
  history. Account-erasure processing immediately revokes destinations and
  tokens, purges or irreversibly tombstones user-authored thesis/portfolio data
  under a documented retention policy, and leaves only the minimum non-content
  integrity markers needed to keep shared financial lineage valid. Normal
  delete endpoints cannot bypass that workflow.

### 9.3 Frontend and accessibility

- Use shared shadcn/UI controls and Tailwind under the repository UI contract.
- URL state is used for shareable non-sensitive filters; private notes and
  secrets never appear in URLs.
- Keyboard navigation, focus restoration, semantic labels, contrast, loading,
  error, disabled, empty, stale, and narrow-layout behavior are acceptance
  requirements.
- Destructive actions require scoped confirmation and describe historical-data
  consequences.
- Optimistic UI never claims persistence before the server transaction succeeds.
- When a monitoring case returns to researching, the UI may show the prior
  published number only as “last user value — under review,” with its original
  date. Value-based alerts pause until a new monitoring decision is saved.
- `next_review_on` is presented as the user's calendar date. Due-action
  materialization uses the user's validated IANA timezone and stores the actual
  scheduling/execution timestamps in UTC, avoiding an ambiguous local instant.

### 9.4 Observability and operations

- Coverage and notification work use durable jobs/outbox rows with leases or
  equivalent recovery semantics.
- Admin surfaces show backlog, age, failures, retry status, last success, and
  configuration readiness without exposing credentials.
- Audit events retain source IDs and correlation IDs.
- Metrics distinguish expected no-op, source blocked, transient failure,
  permanent failure, and data-quality quarantine.

### 9.5 Testing and review

Every phase requires:

1. task document and acceptance contract;
2. failing tests before production code;
3. service/API/database tests on PostgreSQL;
4. frontend behavior/source-standard tests;
5. migration and permission tests where applicable;
6. adversarial review from each affected specialty;
7. remediation of every valid finding;
8. exact canonical closing commands.

“No bug found” is never proven by one happy-path test. Completion evidence must
map every requirement to a test, runtime observation, rendered state, or
documented external dependency.

## 10. Release and rollback strategy

- Each phase is independently releasable behind server-controlled capability
  readiness, not a frontend-only flag.
- Schema additions precede reads/writes; deploys tolerate the immediately prior
  application version during rollout where feasible.
- Background generation/delivery defaults disabled until migrations and
  readiness checks pass.
- Backfills are bounded, resumable, idempotent, and dry-run/report before
  mutation when scope is not obvious.
- Disabling a feature never deletes research history, evidence, events, or
  delivery audit.
- A rollback can stop jobs and hide entry points while preserving append-only
  data for later forward repair.

## 11. Explicit non-priorities

The following do not displace the roadmap unless new evidence changes the
product decision:

- adding more managers beyond the current verified universe;
- Dataroma-parity sector charts before a licensed canonical taxonomy exists;
- CSV export, visual polish, or more 13F table variants as standalone projects;
- generic AI-generated investment theses;
- full-market Value Line coverage before the targeted queue is working;
- real-time quotes or charting;
- broker/trading/tax integration;
- a quant cockpit before the research gate passes.

## 12. Program completion definition

The roadmap is complete only when:

- Phases 0–5 pass their exit gates;
- the allowed Phase 6 data obligation is either operating under an authorized
  source or explicitly blocked by a recorded user-owned licensing decision;
- all roadmap-defined features are present in current code and current migrated
  runtime behavior;
- every requirement is traced to authoritative evidence;
- repeated adversarial review produces no remaining valid correctness,
  security, financial-semantics, workflow, accessibility, operations, or test
  finding;
- all canonical commands pass after the last fix.

External provider credentials and production deployment are not silently
invented. Adapters can be complete and verified with deterministic test
providers while real delivery remains disabled until the user configures and
authorizes it.
