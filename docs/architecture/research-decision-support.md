# Research Decision Support architecture

Status: normative architecture boundary, subordinate to the authoritative PRD  
Owner: Product / Engineering  
Version: 1.0  
Last updated: 2026-08-20

## 1. Decision and scope

ValuePilot Research Decision Support is the integration boundary that turns
permitted discovery signals and canonical financial evidence into a private,
user-authored, point-in-time research record. It supports independent judgment;
it does not create a platform investment opinion or execute a trade.

This document defines exactly ten cross-cutting decisions:

1. authority and precedence;
2. research ownership;
3. AI proposal and human authority;
4. canonical financial truth;
5. canonical valuation truth;
6. point-in-time and supersession;
7. orthogonal states;
8. no trading rails;
9. authorization, privacy, and source visibility;
10. case origins and product integration.

It does not redefine database columns, metric keys, units, formula semantics,
API payloads, delivery behavior, or implementation sequencing. Those details
remain in their delegated authorities.

Normative terms `MUST`, `MUST NOT`, `SHALL`, and `SHALL NOT` apply only within
the ten decisions above. Descriptive diagrams do not create additional storage
or API contracts.

## 2. Authority and precedence

### 2.1 Authority map

When sources overlap, the following bounded authority applies:

| Concern | Authority |
| --- | --- |
| Metric keys, units, normalization, and period semantics | [`metric_facts_mapping_spec.yml`](../metric_facts_mapping_spec.yml) |
| System behavior, schema, API, and Research Decision Loop storage | [`value-pilot-prd-v0.1.md`](../prd/value-pilot-prd-v0.1.md), especially §G |
| `metric_facts`, extraction immutability, correction, and current-slot rules | [`data-layer.md`](data-layer.md) and [`metric-facts-is-current.md`](metric-facts-is-current.md) |
| Permitted source acquisition, retention, automation, and coverage | [`coverage-source-policy.md`](coverage-source-policy.md) |
| 13F discovery interpretation and Oracle's Lens policy | [`oracles_lens_signal_policy.md`](../13f/oracles_lens_signal_policy.md) |
| Product sequencing and acceptance | [`research_decision_loop_product_roadmap.md`](../plans/research_decision_loop_product_roadmap.md) |
| Investment philosophy and conceptual capabilities | [`Investment_Research_Vision.md`](../Investment_Research_Vision.md), non-normative |
| Worked examples | `docs/examples/`, illustrative only |

The mapping spec prevails for metric semantics. The PRD prevails for system,
storage, and API behavior. The locked data-layer decisions prevail within their
delegated integrity concerns. This document resolves only the cross-system
boundaries named in §1 and MUST be read consistently with those authorities.

### 2.2 Change rule

This document MUST NOT silently override an authority above. A proposed change
that affects metric semantics changes the mapping spec. A proposed change that
affects schema, API, lifecycle, or publication changes the PRD in the same work.
A sequencing or exit-gate change belongs in the roadmap.

Vision statements and examples never override normative contracts. If a Vision
example looks like a table, enum, score, formula, or workflow, it remains
illustrative until an authority above adopts it.

### 2.3 No duplicate truth

Implementations MUST reference the delegated contract rather than copying it
into a second implementation guide. A summary may identify the governing rule
and link; it MUST NOT restate a competing variant.

## 3. Research ownership

### 3.1 Shared identity is not a shared thesis

`stocks` and other approved master identities are shared system objects. A
company has no platform-owned canonical investment thesis, quality judgment,
intrinsic value, or investment decision.

The authoritative research unit is the user-owned `research_case` defined by
PRD §G.2. A case represents one user's research cycle for one stock. A later
cycle may reach a different conclusion without rewriting the earlier cycle.

Two users may hold contradictory hypotheses and valuations for the same stock.
Neither user's content changes the other's research projection, alerts,
Watchlist value, portfolio journal, or evidence visibility.

### 3.2 Ownership layers

The architecture separates three ownership classes:

| Class | Examples | Default visibility |
| --- | --- | --- |
| Shared identity and permitted shared observations | stock identity, public SEC/13F records, provider observations explicitly authorized for shared product use | only the audience authorized by the governing source policy |
| User-scoped source material | user-uploaded Value Line reports, proprietary excerpts, private source artifacts | owning user only |
| User-authored research | cases, revisions, notes, evidence interpretation, valuation, decisions, portfolio journal | owning user only |

“Public company” does not imply that every related document or fact is shared.
Visibility follows the source artifact, PRD, and governing source policy, not
merely the stock ID. Permission to acquire or retain a provider observation does
not automatically authorize cross-user display. A shared derived fact MUST NOT
reveal another user's private document, snippet, or proprietary input.

### 3.3 Historical ownership

Research revisions and events preserve the user judgment recorded at the time.
Normal editing appends; it does not mutate a prior decision. Privacy redaction
and account erasure use only the narrow audited exception defined by PRD §G.2
and MUST NOT rewrite shared financial lineage.

The phrase “ValuePilot investment memory” means functionality that helps a user
retain their own auditable memory. It does not transfer ownership of private
research to the platform or authorize cross-user model training or reuse.

## 4. AI proposal and human authority

### 4.1 Authority layers

Investment-research content has three authority layers:

```text
AI_PROPOSED
    -> explicit authenticated user action
USER_ACCEPTED_REVISION
    -> canonical publication transaction when applicable
CURRENT_PUBLISHED_PROJECTION
```

These names describe authority, not a new database enum.

- `AI_PROPOSED` is a draft suggestion, extraction review, comparison, challenge,
  or candidate change. It is never the user's current thesis or valuation.
- `USER_ACCEPTED_REVISION` is an immutable research revision created only by an
  explicit authenticated Save/Decide/Review action under PRD §G.2.
- `CURRENT_PUBLISHED_PROJECTION` is an operational projection derived through a
  canonical publication service, such as current user `val.fair_value`.

### 4.2 Promotion rules

AI output MUST NOT promote itself. Silence, page navigation, background jobs,
model confidence, or elapsed time are not user acceptance.

Every proposed change, including a numerically “small” change, remains proposed
until the user accepts it. A sequence of small AI updates MUST NOT accumulate
into an accepted thesis through a threshold loophole.

An acceptance action records the user, expected head revision, timestamp, and
resulting revision. It records proposal/input references only when the PRD has
authorized their storage. Stale writers follow the PRD's optimistic-concurrency
behavior; last-writer-wins is not valid for user judgment.

In V1, accepting a revision that contains a publishable base intrinsic value
invokes the PRD §G.4 atomic publication transaction. There is no independent
second valuation writer and no accepted-but-secret current fair value. Work that
must not publish remains a client-local or clearly labeled proposal/draft. A
future separate acceptance-versus-publication workflow requires a PRD change.

### 4.3 Permitted AI work

AI may extract, compare, cite, identify missing information, propose hypotheses,
generate a steelman or skeptical alternative, and explain deterministic model
outputs. AI may recommend human review.

AI MUST NOT:

- write or overwrite an accepted thesis without the explicit action above;
- publish or clear current intrinsic value through a new path;
- label a system reference as the user's value;
- convert an Oracle score, filing event, price move, or option premium into a
  buy/sell recommendation;
- treat its own prior answer as evidence;
- hide material assumptions, contradictory evidence, or unavailable sources in
  model context.

Deterministic calculations remain deterministic code. Any persisted AI proposal
records model/prompt or policy version and cited input identities when the PRD
authorizes such storage. Until that storage contract exists, proposals remain
non-authoritative and MUST NOT be queried as product truth.

An in-product flow that lets a user accept AI-authored research MUST NOT ship
until the PRD defines enough proposal provenance to distinguish AI-proposed,
user-edited, and user-authored content. This rule does not pretend the system can
identify text copied from an unrelated external tool.

## 5. Canonical financial truth

### 5.1 One fact system

All Research Decision Support consumers SHALL use the canonical fact contract:

- metric semantics from the mapping spec;
- queryable financial facts from `metric_facts`;
- immutable extraction lineage from `metric_extractions`;
- correction and per-period current-slot behavior from the locked data-layer
  documents.

This architecture creates no thesis-local financial fact store. A research
revision may snapshot the specific claim used in a decision, but that snapshot
is decision evidence, not a second queryable financial truth.

### 5.2 Fact, evidence, and interpretation

A canonical fact becomes evidence only through an explicit case reference. A
case may interpret the same fact differently from another case. Interpretation
does not change the fact.

Queryable derived financial outputs use deterministic, versioned calculations
and are published through the existing formula/fact contract when authorized by
the PRD. An LLM narrative or score is not written to `value_numeric` merely
because it contains a number.

Missing, stale, blocked, failed, conflicting, unsupported, or inaccessible data
remains a typed visible state under the governing contract. Research code MUST
NOT substitute a guess and then present it as a canonical fact.

### 5.3 Provenance and visibility

Parsed metrics retain the provenance required by the data contract. Evidence
links additionally enforce user visibility and stock/source matching under PRD
§G.3. A durable ID proves identity, not permission or truth.

## 6. Canonical valuation truth

### 6.1 Two non-interchangeable branches

The canonical valuation result defined by PRD §G.4 has two branches:

```text
user_intrinsic_value
system_valuation_reference
```

Only a current, user-published intrinsic value may produce user margin of safety
or intrinsic-value crossing alerts. Value Line targets and other system values
may produce only a dated discount/premium-to-reference display.

An AI proposal, DCF input edit, unsaved calculator result, Value Line target,
Oracle score, analyst target, or Vision example is not published user intrinsic
value.

### 6.2 Publication path

Every Watchlist, Oracle's Lens, stock summary, DCF, research workspace, alert,
and option-analysis consumer uses the one canonical valuation application
service specified by PRD §G.4.

Publication appends the accepted revision, reconciles only the authorized manual
fact slot, writes the new AS-OF manual fact, updates the projection, and appends
the event in one transaction. Consumers use the locked read tiebreak. They MUST
select the newest manual row before inspecting its value.

Clearing or declaring valuation unavailable publishes the typed newest null
fact required by the PRD. Consumers MUST NOT fall through to an older value.

Changing a monitoring valuation returns the case to research and pauses value
alerts until a new qualified monitoring decision, exactly as specified by the
PRD. The prior value may appear only as dated, under-review history.

### 6.3 Comparison eligibility

Margin of safety, opportunity zones, and downstream option comparisons require
the PRD's canonical current value and a fresh exact-currency price. Unknown,
stale, mismatched, or system-reference-only inputs produce a typed unavailable
state, not arithmetic.

Bear/base/bull ranges and sector valuation policies are research-method inputs.
Their future storage and publication require PRD and mapping decisions; this
architecture does not create additional metric keys or formulas for them.

## 7. Point-in-time and supersession

### 7.1 Time dimensions

Historical reconstruction distinguishes, where applicable:

| Time | Meaning |
| --- | --- |
| `period_end` | economic/reporting period represented |
| `filed_at` or `accepted_at` | regulator receipt/acceptance |
| `published_at` | source made the item available |
| `ingested_at` | ValuePilot received it |
| `effective_at` | version became authoritative for a governed projection |
| `superseded_at` | later authority replaced it |
| `decision_at` | user accepted the recorded judgment |

Physical field names and required/null rules remain a PRD/schema decision. If a
source does not provide a time, the system records typed unknown; it MUST NOT
copy another timestamp into the field and imply false precision.

### 7.2 Knowledge-as-of rule

An as-of reconstruction uses only source versions ingested and permitted by the
requested knowledge time, the policies/model versions effective then, and the
user revision accepted by then. Later corrections may be shown as a separately
labeled current comparison; they do not leak into the historical result.

Research revisions snapshot the recorded claim, source identity/date, listing
identity, valuation assumptions, decision, and applicable method/policy version
needed to explain the judgment. They do not duplicate proprietary excerpts
beyond the permitted minimal snapshot in PRD §G.3.

### 7.3 Supersession

A restatement, filing amendment, corrected parse, source retraction, identity
correction, or policy/model change preserves the old version and records the
new authority and supersession relationship under the applicable source
contract. Physical links or fields require their PRD/schema contract before
implementation. Supersession does not erase the fact that the prior version was
once known or used.

Supersession of source evidence may create a correction/review action. It MUST
NOT silently rewrite an accepted research revision. 13F authority follows the
active filing/current successful parse and correction semantics already defined
by the 13F and PRD contracts.

## 8. Orthogonal states

### 8.1 State axes

Research lifecycle, decision, valuation, ownership, risk, and option analysis
are separate axes:

| Axis | Meaning | Authority |
| --- | --- | --- |
| Case lifecycle | progress of one research cycle | PRD §G.2 `research_cases.state` |
| User decision | watch, own, pass, or absent as allowed by lifecycle | PRD §G.2 decision matrix |
| Valuation zone | computed relationship of eligible published value and price | canonical valuation result/policy |
| Portfolio state | manual owned/closed position projection | PRD §G.9 |
| Risk/review state | evidence conflict, falsification, due review, or source correction | Inbox/action contracts |
| Option eligibility | current analytical eligibility of a contract or underlying | optional downstream analysis policy |

Exact enums and database checks remain in the PRD. This table MUST NOT be
implemented as one combined enum.

### 8.2 Independence rules

A price crossing changes a valuation-zone projection; it does not by itself
change case lifecycle, thesis, or user decision. A new option contract changes
option eligibility; it does not make a company researched or owned. A risk event
creates review work; it does not silently sell, close, or rewrite a case.

`PUT_CANDIDATE`, `MARGIN_OF_SAFETY`, `THESIS_CONFLICT`, and `OWNED` therefore
MUST NOT be successive values of one state machine.

Axes may share one validated projection row; orthogonality is semantic and does
not require one table per axis. The required automated cross-axis effect in
scope is the PRD rule that accepting a changed valuation for a monitoring case
returns it to researching and pauses alerts. The PRD's lifecycle/decision matrix
continues to apply. Other derived cross-axis effects require an explicit user
action or a PRD change.

### 8.3 Projection transparency

Every derived zone, risk flag, rank, or eligibility result exposes its matched
rule, source/policy version, evaluation time, and unavailable reason. Derived
projections are reproducible conveniences, not historical thesis truth.

## 9. No trading rails

### 9.1 Product boundary

ValuePilot may analyze an equity or option, calculate deterministic underwriting
inputs, rank research attention, record a human decision, and maintain a manual
decision journal.

ValuePilot Research Decision Support SHALL NOT:

- connect to a broker for order submission;
- route, stage, modify, cancel, or execute an order;
- manage margin, collateral, exercise, or assignment;
- claim broker position, cash, tax-lot, realized-P&L, or tax accuracy;
- auto-trade from an alert, score, thesis delta, or option rank.

Adding any trading rail requires a new explicitly authorized product program and
security/legal architecture. It is not an extension implied by this document.

### 9.2 Optional option branch

Option underwriting is an optional downstream branch:

```text
published research decision
       -> equity review
       -> optional option-underwriting analysis
       -> human decision record
```

It is not a mandatory stage between opportunity and human review. Companies
without options remain valid research and investment candidates.

Option output is labeled analysis or “recommended for review,” never a trade
instruction. It binds every calculated result to quote/source time, contract
identity, underlying research revision, current published valuation, price and
currency eligibility, and stated gross/net cost assumptions. `strike - premium`
alone is a gross per-share comparison, not complete net economic cost.

This architecture grants no permission to acquire option-chain data. Automated
option analysis remains configuration-blocked until the coverage/source
authority records a permitted provider, retention/provenance rules, freshness,
and automation limits for the deployment.

## 10. Authorization, privacy, and source visibility

### 10.1 User authority

User-owned resources derive authority from the authenticated session/token, not
a caller-supplied `user_id`. An object ID alone never grants access.

Every research case, revision, origin, evidence reference, valuation, alert
state, destination, portfolio, and journal operation validates ownership on the
server. Cross-user authorization tests are required by the roadmap/PRD for every
affected API.

Ordinary admin access exposes operational health and aggregate readiness only;
it does not imply access to private thesis, notes, proprietary documents,
valuation, destinations, or portfolios.

### 10.2 Source visibility

Evidence validation checks object existence, user visibility, stock identity,
source version, and current permission. A shared fact derived from a private
artifact may expose only the portion explicitly authorized by the governing
contract; it MUST NOT leak the artifact or snippet.

Loss of source permission produces `source_unavailable`. Historical research
keeps the permitted recorded claim and identity but does not bypass access by
copying proprietary content into every revision.

Source acquisition and product visibility remain distinct decisions. A source
being publicly reachable, purchasable, configured, or technically fetchable is
not proof of permission. All automation follows the coverage-source policy.

### 10.3 AI and untrusted content

AI jobs inherit the requesting user's visibility and MUST NOT retrieve or reuse
another user's private content. Private research is not a platform training or
cross-user recommendation asset without a separate explicit consent contract.

Filings, transcripts, PDFs, URLs, notes, and model output are untrusted content,
not authority-bearing instructions. They cannot change system policy, tool
permissions, publication state, or user ownership. External URLs attached as
evidence follow PRD §G.3 and are not server-fetched merely because they appear
in content.

User filters and rules use the repository's bounded SQLAlchemy/restricted-AST
contracts; no user text becomes raw SQL or unrestricted `eval`/`exec`. Rendering
treats user/model text as untrusted text, not executable HTML.

## 11. Case origins and product integration

### 11.1 Parallel discovery, one research boundary

Discovery sources are parallel inputs, not a mandatory funnel:

```text
13F / Oracle's Lens ---------+
Value Line evidence / screener+
manager holding/change ------+--> Research Inbox or create/open case
Watchlist -------------------+
stock summary/search --------+
manual investor idea --------+
```

Oracle's Lens is 13F idea discovery and corroboration, not the universal gateway
for Value Line or manually discovered research. Watchlist membership is not a
prerequisite for a case. V1 Value Line documents/facts attach as evidence or
enter through an already supported origin such as screener, stock summary,
Watchlist, or manual research; adding a distinct Value Line origin type requires
a PRD change rather than an architecture-only enum.

### 11.2 Origin preservation

All entry surfaces use the PRD's one idempotent create/open service. Creating a
new active case or reopening it from a materially new source appends a validated
`research_case_origin`; it does not overwrite the first origin or discard later
context.

An origin records its type, stable source identity, source version, stock match,
and visible context. It is discovery provenance, not evidence that the source's
conclusion is correct.

Duplicate clicks return the existing active case. A closed or voided cycle stays
historical; a later revisit creates a new cycle and records the new origin.

### 11.3 Integration responsibilities

- **13F / Oracle's Lens:** supplies delayed, caveated discovery/corroboration and
  source versions; never current ownership, cost basis, or a buy signal.
- **Value Line:** supplies permitted user-scoped documents and canonical mapped
  facts plus separately labeled system valuation references; never user MOS.
- **Screener:** supplies explainable rule context from canonical facts; it does
  not create thesis truth.
- **Watchlist:** remains a daily interest surface and uses the canonical
  valuation service; it does not maintain a second fair-value writer.
- **Stock summary/search:** may create/open research directly and records manual
  or search origin.
- **Research Inbox:** prioritizes user obligations and source-versioned actions
  under the PRD/roadmap; it does not mutate accepted research automatically.

Coverage follows the targeted priority contract in the PRD/roadmap. A ranking
signal alone cannot outrank an owned or overdue monitored case, and blocked
licensed coverage never counts as ready.

## 12. Conformance boundary

An implementation conforms to this architecture only if all of the following
are true:

- no new metric, fact, valuation, thesis, state, or source truth bypasses its
  delegated authority;
- each accepted research judgment is user-owned, revisioned, and attributable
  to an explicit authenticated action;
- AI proposals remain visibly non-authoritative until accepted;
- every current intrinsic-value consumer uses the canonical publication path;
- historical reconstruction is source-version and knowledge-time aware;
- lifecycle, decision, valuation, portfolio, risk, and option states remain
  orthogonal;
- source visibility is enforced independently from stock identity;
- every discovery surface preserves validated case-origin context;
- option analysis remains optional, evidence-bound, and non-executing;
- no conflict is resolved by treating the Vision or an example as normative.

Implementation acceptance, tests, rollout, and rollback remain governed by the
authoritative PRD and roadmap. This document is complete when it states these
boundaries unambiguously; it is not an alternate delivery plan.
