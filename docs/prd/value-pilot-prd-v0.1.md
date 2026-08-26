**Note**: This document is the consolidated **schema and execution PRD** for ValuePilot v0.1.  
> It focuses on parsing boundaries, data models, and execution semantics.  
> Higher-level product narrative (Background, Milestones) may live in a separate overview doc.

## A. Contract Sources & Precedence (V1)

This PRD intentionally separates “system behavior + storage contracts” from “metric semantics”.

If any inconsistencies exist, the following precedence order MUST be applied:
1) `docs/metric_facts_mapping_spec.yml` (metric semantics: `metric_key`, units, `period_type`, `period_end_date` derivations)
2) `docs/prd/value-pilot-prd-v0.1.md` (system behavior, schema, ingestion/API contracts)
3) Historical addendums / decision records (read-only reference; not normative)

This PRD MUST NOT be used to redefine metric semantics outside `docs/metric_facts_mapping_spec.yml`.
Any PRD text about metrics is descriptive and MUST defer to the mapping spec for canonical keys, units, and period rules.

## B.4 Parsing Boundary (Explicit Scope)

- V1 parsing is **template‑based**, not generic.
- **V1 supports Value Line equity report PDFs only** (each parsed page must match the single‑page standard layout).
- V1 supports both:
  - single-page PDFs (one company), and
  - multi-page “container PDFs” where each page is an independent Value Line report for a different company (see §B.4.2).
- Non‑Value Line pages can still be uploaded/stored; ingestion reports `unsupported_template` at the page level and the overall document status may be `failed` if 0 company pages parse successfully.

### B.4.1 Value Line Template Fields (V1)

The V1 parser MUST extract (at minimum) the following fields when present:

**Header / Ratings**
- company_name, ticker, exchange
- recent_price
- pe_ratio (recent / trailing), relative_pe_ratio
- dividend_yield
- timeliness, safety, technical, beta
- report_date (Value Line issue date)

**Target Price Ranges**
- 18_month_target_low, 18_month_target_high, 18_month_target_midpoint, midpoint_pct_to_mid
- long_term_projection_high_price, long_term_projection_low_price
- long_term_projection_high_total_return_pct, long_term_projection_low_total_return_pct
- long_term_projection_year_range (e.g. "2028-2030")

**Tables (time series)**
- quarterly_sales (by quarter + full year totals)
- earnings_per_share (by quarter + full year totals)
- quarterly_dividends (by quarter + full year totals)

**Financial snapshot blocks**
- capital_structure (debt, leases, pension assets/obligations, shares outstanding, market cap)
- current_position (current assets/liabilities breakdown)
- annual_rates_of_change (sales/cash flow/earnings/dividends/book value; 10yr/5yr/est.)

**Narrative**
- business_description (Value Line “BUSINESS” paragraph)
- analyst_name

### B.4.2 Multi-Page Value Line PDF Ingestion (V1)

The system MUST support PDFs with 1..N pages where each page is parsed independently.

Definitions:
- **Container PDF Document**: the uploaded PDF artifact (may contain multiple company pages).
- **Page Report**: the independent parsing unit corresponding to a single page within a Container PDF Document.
- **Company Page**: a page that passes the Value Line V1 template validation (page-level).

In Scope:
- Loop over pages (ascending `page_number`) and parse each page as a standalone Value Line report.
- Partial success: some pages may parse successfully while others fail or are skipped as non-company pages.

Out of Scope (v0.1):
- Non–Value Line templates.
- “One page contains multiple companies” layouts.
- Cross-page reconciliation (merging facts across pages).

Upload + ingestion flow:
1) Store the PDF as one `pdf_documents` row and extract per-page text into `document_pages`.
2) For each page `p`:
   - Validate Value Line V1 template (page-level).
   - Extract identity (ticker/exchange/company_name) from that page.
   - Resolve stock identity per §Stock Identity Resolution.
   - Parse metrics and persist immutable `metric_extractions` with:
     - `document_id = <container document id>`
     - `page_number = p`
     - `original_text_snippet` set for each extracted field
   - Map parsed page JSON to `metric_facts` using `docs/metric_facts_mapping_spec.yml`.

Single-page vs multi-page stock linkage (`pdf_documents.stock_id`):
- If the uploaded PDF is single-page and represents a single company, `pdf_documents.stock_id` MAY be set.
- If the uploaded PDF is multi-page and contains multiple companies, `pdf_documents.stock_id` MUST be NULL (multi-company container).

Completion status (`pdf_documents.parse_status`, v0.1):
- `uploaded`: stored but not yet parsed
- `parsing`: ingestion in progress
- `parsed`: all company pages parsed successfully (non-company pages may be skipped)
- `parsed_partial`: at least 1 company page parsed and at least 1 company page failed (e.g., identity unresolved / parse error)
- `failed`: 0 company pages parsed successfully

Output contract (API):
- The upload response MUST include `page_reports[]` even for single-page PDFs (length = 1).
- Each entry MUST include `page_number`, `status`, and `parser_version`.
- `page_number` is 1-indexed (matches PDF page numbering).

Note:
- `pdf_documents.parse_status` is document-level.
- `page_reports[].status` is page-level and may include `unsupported_template` even when `pdf_documents.parse_status` is `parsed` or `parsed_partial`.

Example (schema shape, not exhaustive):

```json
{
  "document_id": 123,
  "page_count": 7,
  "status": "parsed_partial",
  "page_reports": [
    {
      "page_number": 1,
      "status": "parsed",
      "parser_version": "v1",
      "stock_id": 10,
      "ticker": "AOS",
      "exchange": "NYSE"
    },
    {
      "page_number": 2,
      "status": "unsupported_template",
      "parser_version": "v1",
      "error_code": "unsupported_template",
      "error_message": "Non-company page skipped."
    },
    {
      "page_number": 3,
      "status": "failed",
      "parser_version": "v1",
      "error_code": "identity_unresolved",
      "error_message": "Could not resolve ticker/exchange for page."
    }
  ]
}
```

Recommended `error_code` enum values (v0.1):
- `unsupported_template`
- `identity_unresolved`
- `parse_error`
- `normalization_error`

Non-normative reference: see multi-page behavior tests in `backend/tests/unit/test_multipage_value_line_upload.py`.

### Canonical Metric Key Rules (V1)

- All `metric_key` values MUST:
  - use dotted namespaces with `snake_case` segments (e.g., `mkt.price`, `val.pe`, `per_share.eps`)
  - NOT start with a number
- Metric keys MUST NOT encode units (no `_usd`, `_pct`, `_millions` in the key); units live in `metric_facts.unit` and are defined in `docs/metric_facts_mapping_spec.yml`.
- Only canonical keys are exposed to formulas and screeners.
See Appendix A.2 for the canonical regex form.

---

## C. Data Modeling & Storage (PostgreSQL)

### Core Tables (V1 Schema Draft)

> Principle: store both (1) **document artifacts** (file/pages/text), (2) **field-level extractions with lineage**, and (3) **metric facts** that power formulas/screeners.

#### users
- id
- email
- created_at

#### stocks
- id
- ticker
- exchange
- company_name
- is_active
- created_at

Note:
- Stocks are **global master data**, not user-owned.
- User-specific views (pools, alerts, metrics) reference `stock_id`.

### Stock Identity Resolution (V1)

- The Value Line parser MUST extract `ticker` and `exchange` when available.
- On PDF ingestion:
  - If (ticker, exchange) exists in `stocks`, reuse its `id`.
  - Otherwise, auto-create a new `stocks` record.
- After resolving by (ticker, exchange), the system MUST compare `company_name` from the PDF to `stocks.company_name`.
- If ticker/exchange matches but company name similarity is below a threshold, set `pdf_documents.identity_needs_review = true` and do NOT auto-link without user confirmation.
- `pdf_documents` and downstream metrics are linked to stocks via `stock_id`.

#### pdf_documents
- id
- user_id
- file_name
- source (e.g. Value Line)
- upload_time
- file_storage_key (store original PDF; text can be regenerated)
- parse_status (uploaded / parsing / parsed / parsed_partial / failed)
- parser_template_id (nullable)
- parser_version
- raw_text (optional cache)
- notes
- stock_id (nullable; resolved via Stock Identity Resolution)
- identity_needs_review (bool; default false)

#### parser_templates
- id
- name (e.g. "value_line_equity_report_v1")
- vendor (Value Line)
- version
- description
- is_active

#### document_pages
- id
- document_id
- page_number
- page_text
- page_image_key (optional, for calibration UI)
- text_extraction_method (native_text; `ocr` reserved for future)

Text Extraction Strategy (V1):
- v0.1 implementation uses native text-layer extraction.
- OCR fallback is reserved for a future revision; when introduced it MUST be expressed via `document_pages.text_extraction_method = ocr` (and must not break lineage contracts).

#### metric_extractions (field-level lineage)
- id
- user_id
- document_id
- page_number
- field_key (e.g. "recent_price", "timeliness", "quarterly_sales")
- raw_value_text
- original_text_snippet (explicit snippet used for traceability; may duplicate raw_value_text)
- parsed_value_json (typed value; supports number/string/percent + units)
- unit (nullable)
- currency (nullable)
- period (nullable; FY2024/TTM/2024-03-31/etc.)
- period_type (FY / Q / TTM)
- period_end_date (YYYY-MM-DD)
- as_of_date (nullable; YYYY-MM-DD)
- confidence_score (0–1)
- bbox_json (optional: {x0,y0,x1,y1} for highlighting in calibration UI)
- parser_template_id
- parser_version
- created_at
- corrected_by_user (bool)
- corrected_at (nullable)
- target_year_range (nullable; e.g. "2028-2030" for rolling projections)

Correction Semantics (V1):
- `parsed_value_json` stores the latest parsed value produced by the parser.
- When a user corrects a value:
  - The corrected value is written into `metric_facts` (source_type = manual).
  - The original extraction in `metric_extractions` is preserved for auditability.
- V1 does NOT overwrite historical parser output.

UI & Query Semantics (V1):
- UI MUST show both: Parsed Value (from metric_extractions) and Active Value (from metric_facts where is_current = true).
- Screeners and formulas MUST read only the Active Value.

#### metric_facts (queryable facts for formulas/screeners)
- id
- user_id
- stock_id
- metric_key (canonical name, e.g. `mkt.price`, `val.pe`, `val.dividend_yield`, `per_share.eps`)
- value_json (typed value; number/string/percent)
- value_numeric (nullable; numeric projection of value_json for indexing/filtering)
- unit (nullable)
- currency (nullable)
- period (nullable)
- period_type (FY / Q / TTM)
- period_end_date (YYYY-MM-DD)
- as_of_date (nullable)
- source_type (parsed / calculated / manual)
- source_ref_id (nullable; points to metric_extractions.id when parsed)
- is_current (bool; indicates the active value for a given (user_id, stock_id, metric_key, period_end_date))
- created_at
- updated_at

Note:
- `value_numeric` MUST be populated when the metric is inherently numeric.
- Screeners SHOULD rely on `value_numeric` for SQL filtering and indexes.

Normalization (V1):
- `value_numeric` MUST be stored in a normalized base unit for correct screening (e.g., USD, not “millions of USD”).
- The ingestion pipeline MUST include a normalization layer that converts Value Line display units/scales into the chosen base units before writing `metric_facts`.

#### formulas
- id
- user_id
- name
- expression
- dependencies_json (list of metric_keys referenced)
- compiled_ast_json (optional)
- created_at
- updated_at

Recalculation Triggers (V1):
- Formulas form a dependency DAG via `dependencies_json`.
- When `metric_facts` receives new/updated facts for a dependency key (parsed or manual), dependent formulas SHOULD be marked dirty and recalculated.

#### calculated_runs
- id
- user_id
- formula_id
- stock_id
- period (nullable)
- as_of_date (nullable)
- result_value_json
- is_dirty (bool)
- created_at
- updated_at

Note:
- `calculated_runs` represents execution history and recalculation state.
- The **authoritative, queryable output** of a formula MUST be written into `metric_facts` with:
  - source_type = calculated
  - metric_key = formula-defined output key
- Screeners MUST operate on `metric_facts`, not directly on `calculated_runs`.

#### stock_pools
- id
- user_id
- name
- description
- created_at

#### pool_memberships
- id
- user_id
- pool_id
- stock_id
- inclusion_type (manual / rule)
- rule_id (nullable)
- created_at

#### screening_rules
- id
- user_id
- name
- rule_json (validated rule AST; compiled to SQLAlchemy expressions, never raw SQL)
- created_at
- updated_at

#### stock_prices
- id
- stock_id
- price_date (YYYY-MM-DD)
- open
- high
- low
- close
- adj_close (nullable)
- volume (nullable)
- source
- currency (nullable ISO-4217; required for new provider writes)
- created_at

#### price_alerts
- id
- user_id
- pool_id (nullable)
- stock_id
- target_price
- tolerance_pct
- cooldown_hours
- last_notified_at (nullable)
- is_active
- created_at
- updated_at

#### notification_settings
- id
- user_id
- channel (email)
- frequency (daily_summary)
- send_time_local (HH:MM)
- timezone
- is_enabled
- created_at
- updated_at

#### notification_events (audit log)
- id
- user_id
- event_type (daily_summary / threshold_hit)
- payload_json
- created_at

---

### Data Traceability Requirements

For every parsed metric, the system MUST store:
- document_id
- page_number
- original_text_snippet
- parser_template_id
- parser_version
- confidence_score (0–1)

This ensures full field‑level auditability and explainability.  
In V1 (Value Line only), most traceability can be satisfied by (document_id, page_number, original_text_snippet) and optional bbox_json for UI highlighting.

`original_text_snippet` is the canonical traceability field; `raw_value_text` is treated as parser output and may differ after user correction.

Confidence Strategy (V1):
- `confidence_score` is heuristic in early versions.
- The system MAY use self-consistency (multiple extraction passes) and/or a verifier step that checks extracted values against `original_text_snippet` to adjust confidence and flag items for review.

---

### F.3 Price Semantics (V1)

- Alerts are triggered using `close` price (not adj_close) unless explicitly configured.

### F.4 Alert Trigger Logic (V1)

- This subsection describes the legacy `price_alerts` proximity behavior only.
  Research Decision Loop intrinsic-value crossing notifications use the stricter
  contract in §G.8 and MUST NOT reuse proximity behavior silently.
- An alert is triggered when:
  abs(close - target_price) <= target_price * tolerance_pct
- `cooldown_hours` suppresses repeated alerts for the same stock after a trigger.
- `daily_summary` emails include:
  - all stocks currently within alert range
  - regardless of whether a threshold alert was triggered that day

---

## G. Research Decision Loop (V1)

The approved sequencing and acceptance source is
`docs/plans/research_decision_loop_product_roadmap.md`. This section is the
authoritative system/storage contract for that roadmap. It does not redefine
metric semantics from `docs/metric_facts_mapping_spec.yml`.

### G.1 Product boundary

Research Decision Loop turns 13F discovery into an independent, user-authored
research decision. It is not a recommendation, real-time signal, broker record,
or tax system. Required copy distinctions:

- 13F data is a delayed reported snapshot, never current ownership or cost basis.
- `val.fair_value` is a user's USD intrinsic-value estimate.
- Value Line targets and system outputs are valuation references; they never
  produce a label of “user fair value” or “margin of safety.”
- `margin_of_safety` is computed only from a current user intrinsic value and a
  fresh same-currency price.
- a system reference may produce only `discount_to_reference` or
  `premium_to_reference`, with source type/date.

### G.2 Research cases

#### `research_cases`

- `id` BIGINT primary key
- `user_id` FK users, required
- `stock_id` FK stocks, required; stock deletion is restricted
- `state` one of `queued`, `researching`, `monitoring`, `closed`, `voided`
- `decision` nullable; when present one of `watch`, `own`, `pass`
- `next_review_on` DATE nullable
- `void_reason` TEXT nullable
- `head_revision_number` INTEGER required, default 0
- `version` INTEGER required, default 1
- `created_at`, `updated_at`, `closed_at`

Database constraints MUST enforce:

- queued/researching: decision NULL, review date NULL, void reason NULL;
- monitoring: decision in watch/own, review date non-null, void reason NULL;
- closed: decision pass, review date NULL, void reason NULL;
- voided: decision/review date NULL, non-blank void reason;
- one active case per `(user_id, stock_id)` using a partial unique index over
  queued/researching/monitoring.

Valid transitions:

- queued -> researching / closed / voided
- researching -> monitoring / closed / voided
- monitoring -> researching / closed / voided
- closed and voided are terminal; a later revisit creates a new cycle

Duplicate create is idempotent: it returns the existing active case with
`created=false`. The create transaction still records a new origin when the
source context is materially new.

#### `research_case_origins`

- append-only, many-to-one with a case;
- fields: case ID, `origin_type`, stable `origin_key`, source version,
  source-reference JSON, created timestamp;
- unique `(case_id, origin_type, origin_key, source_version)`;
- first origin is derived by `(created_at, id)`, avoiding a cyclic reverse FK;
- supported origins: manual, ticker search, Watchlist, screener, Oracle lens
  mode/score, manager holding/change.

Origin validation MUST verify visibility, stock identity, and source version.

#### `research_case_revisions`

- append-only except the privacy-redaction rule below;
- unique `(case_id, revision_number)`;
- records complete user decision content: thesis, variant view, decision reason,
  assumptions JSON, risks JSON, evidence JSON, valuation low/base/high,
  currency, valuation-unavailable reason, decision, review date;
- records ticker, company name, exchange/listing identity displayed at save time;
- fixed-precision monetary columns; API serializes them as decimal strings;
- `created_by_user_id`, created timestamp;
- each save supplies expected head revision; a stale writer receives typed 409.

Valuation rules:

- a draft may omit valuation;
- if either low/high is present, low/base/high and currency are all required;
- `low <= base <= high`;
- a qualifying decision has the full range or one typed unavailable reason;
- V1 research valuation currency is USD, matching canonical
  `val.fair_value`; other currencies require a mapping-contract change.

Editing is client-local until explicit Save/Decide. Server saves append one
revision and warn/reject stale heads rather than overwriting.

#### `research_case_events`

- append-only event log for create, origin added, revision saved, transition,
  snooze/dismiss links, redaction, and closure/void;
- contains case ID, event type, actor, correlation ID, payload JSON, timestamp;
- no normal API mutates or deletes an event.

Privacy exception: an explicit authenticated redaction/account-erasure flow may
overwrite only user-authored revision content with a tombstone hash/reason/
actor/timestamp in one audited transaction. It MUST NOT alter sourced financial
facts, source/stock identity, decision/state metadata, or pretend the revision
never existed.

Qualified-decision measurement is explicit rather than inferred from any
content-complete save. Revision requests carry `decision_action` with one of:

- `draft`: save history/current projection but do not count a decision;
- `decision`: record a qualifying initial or changed decision transition;
- `review`: explicitly reaffirm an existing monitoring decision.

`decision` and `review` require a fully qualified snapshot. A `decision` cannot
restate the unchanged current decision, while a `review` can only reaffirm the
same `watch`/`own` monitoring decision. Each accepted action appends one
`qualified_decision_recorded` case event containing the action type and revision
ID. `qualified_research_decisions_per_active_user_per_week` counts those events,
not every revision whose content happens to be complete.

### G.3 Evidence

Evidence supports Value Line document/fact, 13F filing/holding/change/signal,
stock price, user-authored note, and external HTTPS URL references.

- Every reference is validated for existence, user visibility, and matching
  stock where applicable.
- A shared stock/fact ID cannot reveal another user's private document/snippet.
- Revisions keep only the permitted minimal recorded claim and source metadata;
  proprietary excerpts stay behind original document access control.
- A lost permission/source renders `source_unavailable`; historical claims are
  not silently replaced by current data.
- External URLs accept normalized HTTPS only, are never server-fetched, render
  as untrusted external links with visible domain and safe new-window isolation.

### G.4 Canonical current intrinsic value

One service owns every product read/write of `metric_key='val.fair_value'`.

A saved revision with a base value atomically:

1. appends the revision;
2. demotes only the same `(user_id, stock_id, metric_key, period_type,
   period_end_date, source_type='manual')` slot;
3. inserts the current manual AS-OF fact with the revision ID in
   `source_ref_id`;
4. updates the case projection and appends an event.

For this metric and `source_type='manual'`, `source_ref_id` may identify a
research-case revision. This typed use MUST be documented in the ORM/service;
it is not interpreted as an extraction/formula run.

Multiple current manual facts across AS-OF dates are correct. Reads use:

```text
period_end_date DESC NULLS LAST, created_at DESC, id DESC
```

They select the newest row before reading its value. Explicit clear/unavailable
publishes a newest manual row with `value_numeric=NULL` and typed reason in
`value_json`; consumers MUST NOT fall through to an older manual value. A Value
Line reference remains separately displayable.

Watchlist inline edits and saved DCF values use this service. DCF is otherwise
an unsaved calculator and cannot mutate current value merely by changing inputs.
When either path changes the valuation of a `monitoring` case, the atomic save
transitions it to `researching`, clears the current decision and review date,
and preserves the superseded judgment only in the prior immutable revision.
The new value is under review and cannot trigger intrinsic-value alerts until a
new qualified monitoring decision is saved.

### G.5 Research Inbox

#### `research_inbox_actions`

User-owned current projection with:

- stable logical key, action family, subject and source version;
- optional superseded-action ID;
- priority/freshness policy versions, matched rule, rank components, reason;
- state in open/snoozed/dismissed/completed/superseded;
- snooze date, target case/evidence, first/last observed timestamps;
- unique user + logical key + source version.

#### `research_inbox_action_events`

Append-only event history for creation, material update, correction,
snooze/dismiss/complete/supersede.

Priority order:

1. owned cases and overdue monitoring;
2. watched cases and overdue monitoring;
3. researching cases;
4. queued cases;
5. Watchlist stocks;
6. selected top Oracle candidates;
7. all other stocks excluded.

Permanent dismissal is informational-discovery only and scoped to a source
version. Monitoring obligations may be snoozed at most 30 days and reappear.

### G.6 Coverage and price freshness

#### `research_coverage_requirements`

Durable, explainable current coverage projection:

- user/stock, kind, priority policy version/rule, freshness policy version;
- state: ready/missing/stale/blocked/in_progress/failed;
- reason, source/evidence, observed/evaluated times, permitted next action;
- unique current requirement by user/stock/kind/policy version;
- kinds: EOD price, current Value Line report, valuation input, identity review,
  CUSIP review.

Proprietary acquisition enters in-progress only from a configured authorized
source or explicit upload. Blocked is not covered.

Value Line freshness defaults to a visible 120-calendar-day ValuePilot policy;
the policy version and evaluation timestamp are persisted. The threshold does
not claim a vendor publication cadence.

`stock_prices` adds nullable ISO-4217 `currency`. Existing unknown rows remain
NULL absent a source-backed backfill; new provider writes require currency.
Freshness is based on the most recent expected trading session under the mapped
market calendar. Unknown identity/calendar/currency remains typed unknown.

Canonical EOD reads use configured source priority, price date, created time and
ID. Refresh is batched, idempotent at job/request level, rate-limited, and never
performed per rendered row. Inactive or unresolved stocks retain history but do
not auto-refresh.

### G.7 Oracle lenses and manager follows

The normative lens thesis, calibration versions and reviewed manager
representativeness methodology are recorded in
`docs/13f/oracles_lens_signal_policy.md`.

Oracle's Lens exposes separate versioned `consensus` and `distinctive` modes.
Both show score components, manager/classification versions, exclusions,
representativeness, incomplete-filing caveats, and never infer current ownership
or transaction price.

Manager representativeness is versioned human-reviewed metadata:
`faithful`, `partial`, `unrepresentative`, or `unknown`, with reviewer,
rationale, evidence and effective time. Persisted score/action rows record the
classification version used. Unknown never silently means faithful.

`manager_follows` is user-owned and unique `(user_id, manager_id)`. Follow state
affects only that user's Inbox/subscriptions, never ingestion or canonical global
ranking. Unfollow preserves historical evidence/delivery audit.

### G.8 Notifications

Logical notifications, user subscriptions, encrypted destinations, in-app read
state, and delivery attempts are separate records. Domain transactions append a
durable outbox/logical event; network send is asynchronous.

Required event families:

- followed-manager filing;
- new/add/reduce/exit affecting a Watchlist/open case;
- intrinsic-value threshold crossing;
- research review due/overdue;
- open-case coverage completed/failed;
- correction/supersession of a prior 13F event.

13F logical source version includes active accession and authority/parse result.
An amendment emits a linked correction instead of mutating or duplicating the
old event. Delivery idempotency is `(logical_notification_id, destination_id,
content_version)`.

Intrinsic-value alerts require two consecutive canonical fresh closes, an exact
currency match (USD in V1), a direction-aware crossing, initialization without
alert, hysteresis and cooldown. Same-session/stale/unknown/mismatched data cannot
trigger. Alert state records the last canonical price ID, exact user intrinsic-
value fact ID, monitoring research-revision ID, and threshold/hysteresis values
used. Publishing a newer valuation, saving a new monitoring revision, or
changing either boundary parameter reinitializes the boundary without an alert;
only a later fresh price can create a true crossing. Returning a case to
researching pauses value alerts until a new monitoring decision, whose revision
initializes a new boundary.

The threshold ratio, hysteresis and logical-event cooldown form one user-level
policy for this event family because crossing state is one row per user/stock.
Saving the policy through any destination atomically synchronizes those three
fields across the user's intrinsic-value subscriptions. Channel frequency,
timezone, quiet hours and enablement remain destination-specific; the API/UI
must not pretend that conflicting per-destination boundaries can coexist.
Alert evaluation takes a transaction-scoped user/stock advisory lock before
reading or creating crossing state, including the initial no-row case.

Destinations:

- In-app: always available, durable read/dismiss state.
- Slack: user-owned webhook, exact approved HTTPS Slack host/path, redirects
  disabled, secret encrypted at rest with key version and masked in all reads.
  Current+previous keys support rotation; unreadable secrets fail closed. Test
  send requires an explicit user action.
- Email: TLS-required SMTP; destination remains pending until a short-lived,
  single-use hashed verification challenge is completed. Login email is not
  implicitly verified.

Subscriptions support event family, enabled state, frequency, IANA timezone,
quiet hours and cooldown. Scheduling materializes UTC timestamps with DST-aware
timezone behavior. Attempts store typed response/failure, count, next retry and
timestamps without credentials. Permanent failures stop and remain visible.

In-app history is always immediate. For an enabled external destination,
`immediate` queues one attempt per source event; `daily_digest` and
`weekly_digest` materialize a derived digest after 08:00 in the subscription's
local timezone. A digest records its source-count/range and is inserted with its
delivery attempt in one transaction. The next due digest catches up source
events since the last digest, so scheduler downtime does not silently discard
them. Replays are idempotent by subscription, closed local period and source
range. Quiet hours and cooldown still apply to the resulting attempt.

Research notification materialization and outbox delivery run on an independent
15-minute scheduler, not as a side effect of EDGAR ingestion. Provider calls
occur only after a committed lease and attempted event. Typed transient provider
failures retry with bounded backoff. Because Slack webhooks and SMTP provide no
application idempotency key, an expired lease or unexpected adapter exception is
classified `delivery_outcome_unknown`, stopped rather than blindly resent, and
shown in both the user's delivery audit and aggregate admin operations view.

Destination ciphertext records a key version. The configured window contains
the current key and at most one previous key. A bounded, advisory-locked
re-encryption job records a credential-free `job_runs` audit; unreadable secrets
become `configuration_blocked`. When no keyring is configured, the independent
scheduler reports a skipped rotation rather than creating repetitive failed
jobs. Admin visibility is aggregate/readiness-only and cannot expose notification
content, labels, destination hints, or credentials.

Existing notification events remain readable. Legacy preferences migrate to
immediate in-app history only; their former frequency label is retained solely
for reversible migration audit. No legacy `channel='email'` activates external delivery.
The deployment operations Slack webhook is never a user research destination.

### G.9 Manual portfolios and journal

#### `portfolios`

User-owned name/description/current projection; normal deletion archives rather
than erasing linked history.

#### `portfolio_positions`

- user/portfolio/stock, open/closed state, positive fixed-decimal quantity;
- optional fixed-decimal average unit cost and ISO-4217 currency;
- optional supporting research case/revision;
- expected version, timestamps;
- V1 is long-only; close is an event, never negative quantity.

#### `portfolio_position_events`

Append-only open/resize/close/review events with expected prior version,
quantity/unit-cost snapshot, optional reason, actor/correlation/timestamps.
Projection update and event append are atomic; stale writers receive 409.

V1 performs no FX. A value/return calculation requires a known canonical price
currency equal to the position currency. Otherwise it returns typed unknown or
mismatch and performs no arithmetic. No broker balance, execution, tax lot,
fees, realized gain, or tax correctness is claimed.

### G.10 Authorization, limits and operations

- New user-owned endpoints derive user identity from authentication; query/body
  `user_id` is never authority.
- Cross-user resources return non-disclosing 404 behavior and have regression
  tests.
- Ordinary admins see aggregate operational health, not private research,
  destinations or portfolios.
- Text/JSON/list/batch/page fields have schema limits; external/expensive
  operations have durable per-user rate limits. V1 limits are six coverage price
  refreshes/hour, twenty PDF uploads/hour, ten destination-verification attempts
  per ten minutes, and three explicit destination tests per ten minutes. PDFs
  are rejected above 10 MiB before ingestion.
- User rules compile to SQLAlchemy expressions; no raw SQL from input and no
  unrestricted eval/exec.
- Background coverage/notification work uses durable idempotency, leases or
  equivalent recovery, typed retry/permanent failure and readiness visibility.
- Normal UI actions preserve history. Account erasure revokes credentials and
  purges/tombstones user-authored content under the audited privacy exception.
  The transaction verifies the current password, revokes refresh tokens and
  destinations, disables subscriptions, stops pending delivery, redacts research
  prose/evidence and manual unavailable reasons, tombstones portfolio quantities,
  costs and journal notes, pseudonymizes the login, deactivates the user, and
  retains only non-content integrity metadata plus one hash/summary audit event.

### G.11 API surface

Routes are under `/api/v1` and session-authorized:

- `/research/cases`, `/research/cases/{id}`, revisions, origins and redaction;
- `/research/inbox` plus snooze/dismiss/complete;
- `/research/coverage` and admin aggregate coverage operations;
- stock-scoped canonical valuation read/write;
- manager follow/unfollow/list;
- notification destinations, verification, subscriptions, in-app events and
  delivery audit;
- portfolios, positions and position events.

Every list is paginated with stable ordering. Create, coverage work, source
event generation and delivery have explicit idempotency. Typed 409/422 responses
cover stale version, invalid transition, duplicate domain conflict and invalid
input.

---

## Appendix A: Metric Keys & Mapping Contracts (V1)

This appendix defines the authoritative contract for mapping parsed Value Line output into `metric_facts`.

### A.1 Authoritative Source

The authoritative mapping and metric semantics live in:

```
docs/metric_facts_mapping_spec.yml
```

This mapping spec MUST be treated as versioned contract code. If PRD text and the mapping spec diverge on metric semantics, the mapping spec wins (see §A).

### A.2 Metric Key Naming (Canonical)

- `metric_key` uses dotted namespaces with `snake_case` segments (e.g., `mkt.price`, `val.pe`, `per_share.eps`).
- Each segment MUST match `[a-z][a-z0-9_]*`.
- Full regex form: `^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$`.
- `metric_key` MUST NOT encode units (no `_usd`, `_pct`, `_millions`, etc.); units are expressed via `metric_facts.unit`.

### A.3 What the Mapping Spec Defines

`docs/metric_facts_mapping_spec.yml` defines (non-exhaustive):
- which parsed page JSON paths map to which canonical `metric_key`
- `period_type` and `period_end_date` sourcing/derivation rules
- unit/value normalization rules (as specified in the mapping spec)
- which value form is preferred (`value_numeric` vs `value_text` vs `value_json`)

### A.4 Template Field Keys vs Canonical Metric Keys

- The parser emits template-facing keys into `metric_extractions.field_key`.
- Ingestion builds a stable page JSON payload and maps it to `metric_facts.metric_key` via `docs/metric_facts_mapping_spec.yml`.

Legacy note:
- Earlier drafts referenced a `value_line_v1_field_map.json` approach. This is deprecated for v0.1; do not introduce new metric semantics outside the mapping spec.
---

## Appendix B: Normalization Layer Specification (V1)

This appendix defines how Value Line extracted values are normalized before being written into `metric_facts.value_numeric`.
The goal is to ensure screeners and formulas compare **like with like**, regardless of display scale (e.g., “millions”) or formatting.

### B.1 Core Rule

- `metric_facts.value_numeric` MUST be stored in a **normalized base unit** suitable for correct SQL filtering and indexing.
- Original display context is preserved via:
  - `metric_extractions.raw_value_text` / `original_text_snippet`
  - `metric_extractions.parsed_value_json` (typed, may include display scale)
  - `metric_facts.value_json` (typed, may include display metadata)

### B.2 Base Units (V1 Defaults)

**Money amounts (USD)**
- Base unit for `value_numeric`: **USD (absolute dollars)**.
- Examples:
  - “$1.2 bil.” → 1,200,000,000
  - “350 mil.” → 350,000,000

**Per-share money (USD/share)**
- Base unit for `value_numeric`: **USD per share**.
- Examples:
  - EPS “3.25” → 3.25
  - Dividend/share “0.28” → 0.28

**Shares**
- Base unit for `value_numeric`: **shares (absolute count)**.

**Market cap**
- Base unit for `value_numeric`: **USD (absolute dollars)**.

**Percentages**
- Base unit for `value_numeric`: **ratio in [0, 1]** (not 0–100).
- Example:
  - “5.2%” → 0.052

**Ratios / Multiples**
- Base unit for `value_numeric`: raw ratio number.
- Example:
  - PE “18.5” → 18.5

### B.3 Scale Detection (Display → Base)

The normalization layer MUST detect display scales from either:
- explicit unit tokens near the number (preferred), or
- known Value Line section/table conventions when tokens are absent.

Supported scale tokens (case-insensitive):
- `k`, `thousand` → × 1,000
- `m`, `mil`, `million` → × 1,000,000
- `b`, `bil`, `billion` → × 1,000,000,000
- `t`, `tril`, `trillion` → × 1,000,000,000,000

Currency tokens:
- `$` → currency = USD
- If currency is not explicitly present in the source, default to USD for Value Line (V1 assumption) and store this as metadata in `value_json`.

### B.4 Typed Value JSON Contract

The parser SHOULD emit a consistent `parsed_value_json` and `value_json` format, for example:

```json
{
  "display_value": "1.2",
  "display_unit": "bil",
  "normalized_value": 1200000000,
  "base_unit": "USD",
  "currency": "USD"
}
```

Notes:
- `metric_facts.value_numeric` MUST equal `normalized_value` for numeric metrics.
- `metric_facts.unit` SHOULD store `base_unit` (e.g., "USD", "USD/share", "ratio").
- If a metric is non-numeric (e.g., analyst name), `value_numeric` MUST be NULL.

### B.5 Screening / Query Guidance (V1)

- Screeners MUST filter on `metric_facts.value_numeric`.
- For percentage metrics, comparisons are done using the ratio base:
  - Example: val.dividend_yield > 0.03 (for > 3%)

### B.6 Validation & Guardrails

The ingestion pipeline MUST enforce guardrails:
- If a numeric metric has missing scale and cannot be inferred, mark:
  - `metric_extractions.confidence_score` lower, and/or
  - `pdf_documents.identity_needs_review = true` (if widespread ambiguity is detected)
- Store a normalization error reason in `value_json` if normalization fails.

### B.7 Future Extensions (Out of Scope for V1)

- Multi-currency normalization and FX conversion
- GAAP vs Adjusted metric reconciliation
- Unit-aware formula evaluation (dimensional analysis)
