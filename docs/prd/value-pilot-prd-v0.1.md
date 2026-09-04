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

## H. SEC Financial-Filing Lineage (FT-03)

### H.1 Boundary and authority

FT-03 creates the primary-source lineage needed for future financial truth. It
does not itself publish product financial facts. Permitted forms, acquisition,
retention, automation and visibility are owned by
`docs/architecture/coverage-source-policy.md`. Metric names, units and mapping
remain owned by `docs/metric_facts_mapping_spec.yml`; adding SEC publication is
FT-04 and requires that authority to change before implementation.

The only queryable product fundamentals source remains `metric_facts`. Raw SEC
filings, artifacts and XBRL facts MUST NOT be queried by screeners, formulas,
the research workspace, valuation, Watchlist, or other product consumers. They
are lineage/review inputs and future mapping inputs only. Market prices remain
under the separate canonical EOD contract.

### H.2 Effective-dated issuer identity

`sec_issuer_identities` is append-only reviewed master lineage:

- `id` BIGINT primary key;
- `stock_id` FK `stocks`, required and delete-restricted;
- zero-padded ten-digit `cik`, required;
- `status` one of `reviewed`, `needs_review`, `retired`;
- `confidence` fixed-precision nullable and `review_reason` required for a
  reviewed/retired decision;
- `effective_from` and nullable `effective_to` describe the real-world identity
  interval; `known_at` records when ValuePilot acquired the decision;
- reviewer identity and created timestamp are retained.

Only a `reviewed` row may drive acquisition. At most one identity whose
real-world interval contains a given instant may be active for a stock, and a
CIK cannot be concurrently reviewed for two economic issuers. The service and
database reject overlapping reviewed intervals. A ticker/name match or CIK
candidate never promotes itself. A correction appends a new decision; it does
not rewrite what the system knew earlier.

An as-of identity must satisfy both its effective interval and
`known_at <= cutoff`. Backdating `effective_from` never makes a later review
visible at an earlier knowledge cutoff.

### H.3 Financial filings

`sec_financial_filings` is append-only and shared public-source lineage:

- issuer-identity FK, accession number, form type and amendment flag;
- filing date, report date, SEC acceptance timestamp and ValuePilot `known_at`;
- primary document name/description and the constructed SEC index/source URLs;
- submissions source URL plus discovery payload hash;
- optional `amends_filing_id`; links are validated within the same issuer and
  compatible base form/report period;
- unique accession number.

Discovery reads the SEC submissions manifest, including referenced historical
submission files when necessary. Array fields are zipped only to their common
validated length; malformed entries are rejected or recorded as typed failures,
never shifted onto a neighboring accession. Approved base forms and amendments
are retained independently. Historical-submissions filenames are preserved for
service validation and must match the same reviewed CIK's SEC basename pattern;
path traversal, cross-CIK, malformed or otherwise unsafe references are not
requested and produce a bounded `unsafe_historical_submission_reference` typed
failure. Parser output retains the array index plus a fixed error code for
non-object entries and entries with a missing, non-string or empty `name`, so
service validation cannot silently turn them into “no filing found”. A later
amendment does not mutate or delete the original filing.

### H.4 Artifact manifest and immutable storage

`sec_submission_snapshots` records issuer-wide discovery payloads independently
from any one accession. Each immutable row records the reviewed issuer identity,
source URL, SHA-256, byte size, content-addressed storage key, fetch/knowledge
time and creation time. Unique issuer/source/content identity makes an identical
snapshot idempotent while allowing a changed submissions payload to append a new
auditable observation. These snapshots establish discovery lineage; they are
not members of a filing parse run's exact input manifest and their SHA or row ID
MUST NOT change an unchanged accession's artifact or parse identity.
Every successfully fetched main or historical submissions payload is retained,
including malformed payloads. Decode, parse, downstream historical-fetch or
accession-index acquisition failure appends a bounded typed acquisition-failure
audit tied to a snapshot explicitly linked to that operation and publishes no
unsupported filing parse lineage or `metric_facts`. A later operation may link
a byte-identical snapshot created earlier; ownership is the exact operation-to-
snapshot link plus reviewed identity, not the snapshot's creation operation.
Failure visibility is never cleared merely because another issuer operation
finalized. Each failure stores an immutable normalized resource role/key. A
later finalized operation resolves only the exact validated submissions source,
or an accession acquisition after that same accession reaches a terminal parse;
a terminal parse failure replaces the acquisition failure but remains visible
as failed-parse evidence. Different accessions, historical source URLs,
no-eligible-filing results, and unrelated operations do not resolve the failure.
PIT projection additionally requires the failure's reviewed identity to remain
the terminal effective identity at the requested cutoff.
If the initial canonical main-submissions request fails before returning bytes,
the system MUST commit a bounded `submissions_fetch` acquisition failure against
an explicit operation-owned no-bytes main-resource anchor. That anchor is not a
snapshot and MUST NOT support a `no_eligible_filings` terminal. The failure is
pending until a separate finalize commit, produces no filing/artifact/parse/raw
fact/`metric_facts` lineage, remains idempotent across the same typed outage,
and is resolved only when a later finalized operation validates the exact same
canonical main resource.
The backend application, PostgreSQL application/admin roles, Rate Guard,
deployment host/admins, and authorized developers are trusted infrastructure.
The product MUST fail closed for malformed or identity-conflicting SEC payloads,
limits/outages/partial fetches, stale cache, normal corrections and duplicates,
concurrency/crash/finalize behavior, small clock skew, coverage gaps, PIT and
supersession, and missing or corrupt retained files. Defending against arbitrary
trusted-database writes, arbitrary backend code execution, malicious admins,
internal key theft, or signature forgery is outside this product contract.
Transport receipts, backend signing authorities, keyrings, and cryptographic
replay gates therefore are not required.

A `resource_validated` resolution MUST remain operation/snapshot scoped and may
be written only after ordinary deterministic validation rereads the retained
content-addressed bytes, verifies recorded SHA-256/size, parses successfully,
checks canonical main/historical role and URL plus reviewed CIK, and, for a
historical payload, verifies the exact reference in the retained main payload.
Selectors repeat the controlled-storage integrity and semantic checks before a
resolution can suppress earlier failure evidence.
Every accession resolution MUST reference an immutable attempt owned by that
operation. The attempt is database-stamped and records the reviewed filing and
accession, index resource and content hash, parse-input manifest, terminal
outcome, and exact retained artifact links. A current parse belongs to the same
operation; idempotent prior-run reuse is valid only when the attempt explicitly
verifies the same content/input lineage. Finalizing an empty operation around an
old run is not evidence. A resolution recorded before a later failure cannot
resolve it merely because its operation finalizes afterward. Filing-artifact
failure claims must identify the same unavailable/rejected observation and
matching typed reason; retained artifacts and mismatched source-less filename keys
fail closed.

`sec_filing_artifacts` records the complete artifact list returned by the SEC
accession index and the fetch state for each item:

- filing FK, stable item sequence/name, description, SEC-declared type/size and
  source URL;
- state `manifest_only`, `retained`, `unavailable`, or `rejected` with typed
  reason;
- content MIME when known, SHA-256, byte size, storage key, fetched time and
  `known_at`; HTTP ETag/Last-Modified are stored when supplied;
- observation identity includes filing, filename, manifest version and state, so
  an unavailable fetch can be followed by a retained observation without
  mutating history; identical retained bytes reuse the same content-addressed
  storage object and each observation retains its own lineage row.

The accession manifest is complete even when policy fetches only approved
artifact types. A manifest row is not evidence content until state is
`retained`. Storage keys are derived from the content hash and never from
untrusted path segments. Existing bytes are verified and reused; they are never
overwritten. A filename containing traversal, an off-SEC URL, an oversized
response, disallowed content, hash mismatch, or storage mismatch fails closed.
When the SEC manifest supplies a byte size, the downloaded response MUST match
it exactly. A mismatch appends a `rejected` artifact observation with typed
`declared_size_mismatch` evidence and the response MUST NOT become a parse
input. A previously retained observation is reusable only after its stored
bytes, recorded byte size and SHA-256 all verify and after the corresponding
upstream input is revalidated through Rate Guard. The actual revalidated SHA-256
and byte size participate in manifest identity. Changed retained bytes append a
new artifact group and parse run even when the accession index bytes and
declared size are unchanged; identical bytes remain idempotent.

Forced revalidation uses Rate Guard's normal fetch contract with
`max_cache_age_s=0`; it never bypasses Rate Guard's SEC allowlist, aggregate
limiter, retries, or global pause. ValuePilot hashes and sizes the actual
returned bytes and persists exact attempt/input ownership. Success/failure
replay, suppression, earliest replay boundaries, and operator replay reread all
controlled retained inputs and verify file existence, recorded byte size,
SEC-declared size when present, and SHA-256. Missing, truncated, or same-size
corrupted inputs fail closed, remain visible as
`retained_artifact_integrity_failure`, and cannot silently fall back to an older
run for that filing. Every non-NULL filing-artifact URL is also an exact
reconstruction from reviewed CIK integer form, dashless accession and strict
safe filename (with `index.json` for the synthetic index observation); host,
userinfo, port, query, fragment, case, encoding, and traversal variants are not
equivalent.

The retained first vertical slice includes the primary inline-XBRL/HTML document
and SEC index-declared XBRL instance/schema/calculation/definition/label/
presentation artifacts when present. Archives, images and unrelated exhibits
remain manifest-only unless the source policy is expanded.

### H.5 Parse runs and raw XBRL facts

`sec_financial_parse_runs` is append-only. A row is written only after an
attempt reaches a terminal `succeeded` or `failed` state and records filing,
parser name/version, input-manifest hash, start/completion/knowledge timestamps,
fact count and typed error. Unique `(filing_id, parser_version,
input_manifest_hash)` makes exact replay idempotent. A newer parser appends a
run and never deletes an earlier run/fact.

`sec_financial_parse_run_artifacts` is the append-only exact input manifest:
each row links one parse run to one retained artifact, unique per pair. The
manifest hash is a checksum, not a substitute for these durable identities. A
filing's exact manifest includes its accession index and retained filing
artifacts, never an issuer submissions snapshot. A link records both `known_at`
and its database-created timestamp. The run, all input links and all raw facts
are committed atomically; an input relationship may not be appended in a later
transaction. A PIT read is eligible only when every linked artifact was retained
and both the artifact and relationship were known and created by the cutoff. The
database rejects cross-filing links, artifacts learned after the parse run and
relationships created after the run; raw facts have a composite foreign key to
one of these exact input links.
New lineage belongs to an immutable ingestion operation. Absence of a separate
`sec_financial_lineage_availabilities` row means the operation is pending and
all of its success or failure evidence is excluded from PIT selectors. After the
ingest transaction commits, an operator path inserts the availability marker in
a second transaction; PostgreSQL stamps `available_at` with wall-clock time.
Reads before that boundary fail closed. Finalization and crash recovery are
idempotent, and operator reruns first recover any committed pending operation.
Every new parse run requires an operation. NULL-operation runs are replayable
only when their IDs were captured in the immutable legacy allowlist during the
schema upgrade; arbitrary or newly inserted NULL rows are rejected or excluded.

For the atomic group, the database unconditionally stamps `created_at` and a
64-bit creation-transaction identity on every run, input link and raw fact;
caller-supplied values are overwritten. Each link and fact must carry the same
database transaction identity as its run, so backfilled timestamps cannot make
a later transaction appear contemporaneous.

A `succeeded` run has a positive `fact_count`; a `failed` run has zero. A
deferred database constraint verifies at transaction commit that the recorded
count equals the number of raw facts attached to a succeeded run (and that a
failed run has none). Raw facts cannot be appended in a later transaction.
Therefore a terminal run cannot claim success without the exact evidence rows
that make the claim true.

`sec_raw_xbrl_facts` is append-only and belongs to exactly one succeeded run and
one retained source artifact. It preserves:

- concept namespace URI and local name plus the source prefix as display-only
  metadata; context ID; and a structured unit definition whose ordered
  numerator/denominator measures each preserve namespace URI and local name
  plus display-only prefix (the raw unit ID is retained but is not authority);
  raw lexical value, inline-XBRL transformation format, language and
  continuation reference, decimals, scale, sign and nil state;
- instant or duration start/end, entity identifier and dimensions JSON;
- an evidence locator containing artifact ID plus a validated HTML element ID
  or deterministic DOM/XPath-like locator and nearby-text hash/snippet within
  approved limits;
- ordinal and created timestamp, unique within the parse run.

This source locator is the SEC inline-XBRL equivalent of PDF page/snippet
provenance. `page_number` is not fabricated. When FT-04 maps a raw fact, its
canonical provenance must retain this locator through the approved mapping
contract; it may not silently populate an unrelated PDF `document_id`.

The initial parser extracts inline-XBRL numeric and non-numeric facts plus
context/unit definitions. It does not infer canonical metric identity, choose
between duplicate contexts, derive quarters, normalize currency, or publish
`value_numeric`.

Neither concept nor unit identity may be reconstructed by trusting an XBRL
prefix string. A currency measure is eligible for FT-04 only when its structured
QName resolves to the exact ISO-4217 authority URI
`http://www.xbrl.org/2003/iso4217` and an approved code. The XBRL instance
authority URI is exactly `http://www.xbrl.org/2003/instance`. Compound units
retain ordered numerator and denominator QName lists; a prefix is never
authority.

### H.6 Point-in-time and supersession

For cutoff `T`, a replay may use only:

- the filing's own issuer identity, which must be reviewed, effective at the
  filing period, and known by `T`;
- a filing with SEC `accepted_at <= T` and ValuePilot `known_at <= T`;
- artifact bytes with `known_at <= T`;
- parse-input relationships with both `known_at <= T` and the database-forced
  `created_at <= T`, backed by the run's matching creation-transaction identity;
- a succeeded parse run with a positive fact count, `completed_at <= T` and
  `known_at <= T`.

The query returns the newest eligible parse version only when the caller asks
for that policy; it always exposes the selected filing/accession, parser and
manifest identities. An amendment supersedes the original only at cutoffs where
the amendment is eligible and the requested policy says amendments are
authoritative. Historical replay before the amendment continues to return the
original evidence. Current projection and historical replay are separate
queries; a current row is never relabeled with an old cutoff.

Every participating table is protected against ordinary UPDATE/DELETE at the
database boundary. A narrowly defined migration/retention operation requires an
explicit audited administrative path; application services have no mutation or
delete method for this lineage.

### H.7 Operator surface and failure behavior

FT-03 exposes an operator CLI/service, not a user-facing raw-fact endpoint. The
operation accepts a reviewed stock identity, bounded filing count, and optional
as-of cutoff; discovery uses the form set approved by source policy. It returns
accession/artifact/parse-run counts and typed failures without dumping artifact
content.

Acquisition is idempotent, bounded, observable and uses the shared Rate Guard.
Rate Guard unavailable/blocked, SEC HTTP status when supplied, malformed
manifest, identity not reviewed, storage mismatch, unsupported form, and parse
failure remain distinct terminal outcomes. Partial work never becomes a
succeeded parse run.
Retries reuse retained verified artifacts and do not create duplicate raw facts.
An exact replay of a failed run reports that run's typed failure; it never
returns an empty-success result. Historical-submissions discovery reads at most
20 referenced manifest files per operation. If the filing target is still not
met and more history remains, the report includes
`history_scan_limit_exceeded`; operators must continue with another bounded
operation rather than turning one request into an unbounded crawl. Unsafe
historical-submissions references are never fetched and appear as bounded
`unsafe_historical_submission_reference` failures, making the CLI exit with
the same incomplete-result status as other typed failures.

### H.8 Gold-set acceptance isolation and reporting

The locked FT-00 gold set MUST run in a clean, disposable acceptance database
on the authorized shared PostgreSQL instance and in isolated run-derived
content storage. It MUST NOT migrate, stamp, read acceptance state from, or
clean the shared development `valuepilot` database. The environment starts from
an empty database, upgrades to the single Alembic head, uses the normal single
Rate Guard SEC path, and supports exact retry-safe teardown.
Before any migration, test, ingestion, finalization, report, or destructive
cleanup step, one shared preflight MUST derive the exact acceptance database URL
and storage path from the validated run ID. It MUST reject absent acceptance
mode, any run/database/URL/`current_database()` disagreement, missing/wrong/
escaped/symlink storage, and every Rate Guard fallback. Acceptance CLI options
in a normal API environment MUST fail before opening an application session or
writing a report.

`filing_selection_as_of` is the historical filing-eligibility cutoff and MUST
remain separate from evidence knowledge time. PostgreSQL stamps the operation
attempt at insert and the separately committed availability marker; neither may
be caller-backdated to the selection cutoff. Newly fetched evidence is absent
from PIT replay immediately before availability and eligible at/after it.

Each case produces stable JSON plus a human summary containing the selection
cutoff, operation attempted/finalized/available times, expected completed fiscal
years, selected forms/accessions, bounded typed gaps/failures, and lineage
counts. The report explicitly records the number of `metric_facts` rows; FT-03
acceptance requires that count to remain zero.

### H.9 Canonical SEC publication (FT-04)

FT-04 is the only boundary that may convert SEC raw financial lineage into
product-queryable fundamentals. Metric keys, units, currency and period
semantics come only from the approved `sec_xbrl` version in
`docs/metric_facts_mapping_spec.yml`. Source permission remains governed by the
coverage-source policy. This section owns publication storage, lifecycle, API,
and point-in-time behavior; it does not create a second metric-semantics source.

#### Publication storage

The implementation adds these append-only lineage records:

- `sec_metric_mapping_versions`: the mapping ID, approved/retired status,
  mapping-spec content hash, `known_at`, `effective_from`, optional retirement
  time, reviewer and reason. Runtime text or an unapplied YAML edit cannot
  authorize publication by itself.
- `sec_metric_mapping_version_namespaces`: one immutable row for every
  `(mapping_version, namespace_authority, exact_namespace_uri)`, carrying the
  parent mapping-spec digest. Runtime pattern matching is not publication
  authority; an unregistered URI requires a new mapping version.
- `sec_metric_mapping_version_currencies`: one immutable ordinal row for each
  approved currency code, plus the currency-list ID, canonical serialization
  and SHA-256 pinned by the parent mapping version. Runtime library contents do
  not add or remove eligible codes during replay.
- `sec_metric_publication_runs`: one database-stamped attempt for one stock,
  reviewed SEC identity, mapping version and knowledge cutoff. It records
  terminal status and exact published/unresolved/rejected counts. A succeeded
  run is complete for its ordered exact parse-authority set and mapping version.
- `sec_metric_publication_run_sources`: the ordered exact source set for a run.
  Each row links one source ordinal to a finalized, PIT-eligible,
  storage-verified succeeded parse run and records its filing/accession,
  parser/manifest identity and availability. The set is immutable and its hash
  is only a checksum of these durable source rows, not a replacement for them.
- `sec_metric_publications`: one append-only mapping decision with status
  `published`, `unresolved`, or `rejected`, a bounded typed reason, canonical
  projection fields when published, source role, fact nature, filing/accession,
  parser/mapping/context/period/unit/currency identity, knowledge time, locator,
  and nullable resulting `metric_fact_id`.
- `sec_metric_publication_inputs`: the ordered exact raw-fact inputs and their
  role. A direct publication has one input; a subtraction-derived quarter has
  every operand. A checksum is not a substitute for durable input FKs.

Every publication input belongs to one member of the publication run's exact
source set and its verified retained artifact. The database rejects input not
in that set and rejects filing/identity, stock, context, period,
mapping-version, operation, source-ordinal and knowledge-cutoff mismatches.
Ordinary
application roles cannot update, delete, or truncate mapping versions, runs,
run sources, publication decisions, or input links. A narrowly audited
migration/retention path remains the only administrative exception.

Published facts use the existing table with all of these required rules:

- `source_type='sec'`, `user_id=NULL`, because permitted SEC actuals are shared
  public-source observations rather than a user's property;
- `source_document_id=NULL`; SEC HTML/XML evidence is not a Value Line PDF and
  no fake PDF document or page number may be created;
- `source_ref_id` identifies the exact `sec_metric_publications` decision, not a
  raw-fact ID or a polymorphic guess;
- provenance retains the accession, source artifact and locator, raw or exact
  derived inputs, parser and mapping versions, source role, fact nature,
  accepted/known time, context, dimensions policy, period bounds, unit and
  source-reported currency;
- user-owned parsed/manual/calculated facts retain a non-null owner. SEC
  publication never changes their visibility or current slots.

FT-04 directly migrates `metric_facts.user_id` to nullable and
`metric_facts.value_numeric` to exact `NUMERIC(38,12)`. A database ownership
check requires `(source_type='sec' AND user_id IS NULL) OR
(source_type<>'sec' AND user_id IS NOT NULL)`; every existing user-owned
parsed/manual/calculated row therefore retains its owner.
Existing float values are converted once by the migration; all new SEC
publication and derived-quarter arithmetic reaches the column as Decimal,
never through binary float. Upgrade declares the existing binary-float values
at `NUMERIC(38,12)`
precision. Downgrade is guarded: it is allowed only when no SEC facts exist and
every remaining `value_numeric` survives an exact
Numeric→double→`NUMERIC(38,12)` round trip. Otherwise downgrade fails explicitly
instead of claiming an arbitrary Decimal is exactly representable as float.
Migration tests must prove that an empty upgrade/downgrade/upgrade and a safe
legacy value such as `42.5` round-trip, while the presence of any SEC fact or a
precision-sensitive value such as `9007199254740993.000000000001` refuses
downgrade without changing data. EUR-per-share and other SEC values must remain
exact on upgrade but, as SEC facts, block downgrade.

SEC fact unit storage is a closed grammar: monetary facts use `unit='currency'`,
per-share monetary facts use `unit='currency_per_share'`, share counts use
`unit='shares'`; `currency` is a separately validated uppercase ISO-4217 code
for the first two and NULL for shares. An SEC fact requires non-NULL
`source_ref_id`; database integrity proves that it names a published
`sec_metric_publications` row whose reciprocal `metric_fact_id`, stock, metric,
period, value, unit and currency match. A partial unique current-slot constraint
applies only where `source_type='sec' AND is_current=true`, on
`(stock_id, metric_key, period_type, period_end_date)`. It neither merges source
roles nor changes user-owned current slots.

The raw structured unit shape is equally closed. Monetary means exactly one
ISO-4217 currency QName in the ordered numerator and no denominator.
Currency-per-share means exactly one ISO-4217 currency numerator followed by
exactly one XBRL-instance `shares` denominator. Shares means exactly one
XBRL-instance `shares` numerator and no denominator. An additional, missing,
reordered, wrong-namespace or wrong-local-name measure is `unresolved_unit`;
display prefixes cannot make it eligible.

`metric_facts` remains the only product-queryable fundamentals store. The SEC
raw, mapping-version, run, publication, and input tables are lineage, operator,
and evidence-resolution inputs; screeners, formulas, research, valuation,
Watchlist and other product consumers MUST NOT query them for values.

#### Mapping and typed outcomes

Mapping matches the raw fact's namespace URI plus local name. An XBRL prefix is
display metadata only. `sec-us-gaap-v1` accepts only the exact US-GAAP and DEI
URIs enumerated in its mapping contract and persisted registry rows; a URI that
merely has a plausible year/host/path shape is not eligible. A new taxonomy URI
requires a new reviewed mapping version and digest.

Normalization uses decimal arithmetic and the exact source
scale/sign/transformation. `sec-us-gaap-v1` pins the ordered currency list
`[DKK, EUR, TWD, USD]` observed in the locked FT-00 gold set, with canonical
serialization and SHA-256 in both spec and registry. It does not consult a
runtime ISO library for replay eligibility. An approved source-reported
currency is preserved in `currency` and the corresponding source unit; any
other valid, deprecated, unknown or malformed currency code is
`unresolved_currency` until a new mapping version explicitly adds it. FT-04
performs no FX conversion and never infers USD for a non-USD or unknown fact.

Only the approved consolidated/no-dimension policy publishes in V1. Custom or
unknown concepts, dimensions, conflicting candidates, unknown units/currency,
invalid periods, unsupported form semantics, and missing derived-quarter inputs
append typed unresolved/rejected decisions. They do not publish NULL/zero or a
best guess. Identical candidates use the mapping spec's deterministic identity
rule; different values never use last-write-wins.

Concept selection has one deterministic priority pipeline. Candidate groups
are evaluated by ascending concept priority. Within a group every candidate is
validated, in order, for namespace authority, unit shape, period, dimensions
and value. The next priority group is considered only when every candidate in
the current group is typed-invalid. Once a group has a valid candidate, lower
groups cannot participate in selection or conflict detection. Identical valid
candidates for the same slot select the lowest raw-fact ID; different valid
values in the same group yield `unresolved_conflicting_candidates` and never
fall through. Every raw candidate in lower groups still receives one bounded
`lower_priority_concept_not_selected` audit decision. Thus a higher valid
concept wins over a lower concept whether their values agree or differ.

Disposition slot authority is presentation-aware. Invalid unit, currency,
value or nil evidence may carry a canonical slot only when the applicable rule
and an exact retained statement occurrence independently prove that slot's
presentation period. Dimensioned, custom, lower-priority, duplicate and
unclassifiable-period evidence remains slotless audit evidence and cannot
demote a current SEC fact. This restriction adds no new disposition type.

Period classification is deterministic and form-first. A duration in a
`10-K`/`10-K/A` or `20-F`/`20-F/A` is FY only within 300–380 elapsed days. A
`10-Q`/`10-Q/A` duration is discrete Q only within 70–110 days, six-month YTD
only within 150–210 days, or nine-month YTD only within 240–300 days. Form is
evaluated before bounds, so the 300-day annual and nine-month boundaries are
not ambiguous. Every accepted duration end must align to the filing's explicit
statement period and fiscal cycle; unmatched gaps are typed unresolved.

An instant publishes only when the filing explicitly presents it at the filing
fiscal-cycle end or an allowed comparative cycle: annual/current or prior FY,
current or prior same fiscal quarter, or a prior FY balance-sheet comparative
in a quarterly filing. Comparison uses the same fiscal-cycle ordinal and
explicit statement presentation; date proximity is not evidence. The duration
bounds deliberately include valid 52/53-week years, while comparative alignment
must retain their disclosed fiscal cadence. A `6-K` remains typed unresolved
until a separate approved period rule exists.

A direct discrete quarter is preferred. When an approved subtraction rule
derives a quarter, every operand must have the same stock, canonical metric and
mapping semantics, fiscal-year start, unit, currency, consolidated context and
empty-dimension policy; every filing/amendment must be selected under the run's
one amendment policy and every input must be known by the run cutoff.

`current_ytd_minus_immediately_prior_ytd` applies only to Q2 or Q3. The left
fiscal-quarter ordinal is respectively 2 or 3, the right ordinal is exactly one
less, both share the same fiscal-year start, left end is later, and the
difference duration is 70–110 days. The output is Q at the left ordinal, starts
the day after the right end and ends at the left end. A skipped quarter is not a
quarter derivation.

For Q4, the left FY is 300–380 days and the right input is explicitly Q3/nine-
month YTD with the same fiscal-year start; left end is later and their difference
is 70–110 days. Output is Q4, from the day after the nine-month end through the
FY end. This rule may use one selected 10-K source and one selected 10-Q source
from the ordered run-source set. Cross-year, cross-currency, context, dimension,
semantic, skipped-period, wrong-duration, unselected-amendment or post-cutoff
inputs produce the mapping spec's specific typed incompatibility outcome; they
are never coerced. The result is `derived_actual`, uses Decimal arithmetic, and
records all exact operands.

#### Atomic lifecycle, current slots, and replay

Publication starts only from a reviewed identity and an ordered exact set of
finalized, PIT-eligible, storage-verified succeeded parse runs. Selection
records the full source set, one explicit amendment policy, mapping version and
knowledge cutoff. It never queries raw facts as a product shortcut.

One transaction appends the run's decisions and exact inputs, inserts each SEC
`metric_facts` row, reconciles only the same SEC per-period current slot, and
commits terminal counts. Deferred database checks prove that every published
decision has exactly one matching canonical fact and that a succeeded run's
counts equal its durable decisions. A crash commits none of that transaction.

Exact `(ordered parse-authority set, amendment policy, mapping version,
knowledge cutoff)` replay is idempotent and creates no new decisions or facts.
Publication takes a
transaction-scoped stock/publication lock; concurrent attempts cannot create
two current SEC facts for the same `(stock_id, metric_key, period_type,
period_end_date, source_type='sec')` slot. Mapping version is part of replay and
provenance identity, not current-slot identity: an accepted newer mapping
version supersedes the older SEC projection for that same period. This
uniqueness is SEC- and period-scoped and MUST NOT become global `is_current`
deduplication.

V1 amendment authority is slot-level. An eligible amendment affects an original
slot only when the amendment actually contains a candidate for that mapped slot
and that candidate is published or receives a typed unresolved/rejected
decision. A successfully parsed amendment with no applicable mapped financial
facts records `nonfinancial_amendment_no_slot_effect` and does not clear any
original slot; omission of some other metric from an otherwise financial
amendment also does not imply deletion. A published amended value supersedes
only its matching SEC period slot. A conflicting or otherwise unresolved
candidate makes only that slot typed unavailable—never silently stale—while
preserving the prior row as immutable non-current evidence.

If an eligible amendment parse fails before its affected slots can be proven,
canonical reads for that filing cycle fail closed with
`unresolved_amendment_parse_failure`; they must not silently return original
values as though no amendment existed. A later successful classification may
establish the narrower slot-level effect by appending lineage. No amendment,
including a nonfinancial one, affects current or historical projection before
its own acceptance, availability, mapping-effective and knowledge boundaries.
Original-to-amendment authority selection is recorded in the ordered run-source
set; a query never combines an original and superseding amendment for the same
slot by accident.

A later parser version or mapping version also appends lineage and may
supersede only the corresponding SEC period slot after its own effective and
knowledge boundaries. Prior facts remain immutable historical evidence. A
typed conflict never falls back to an older value without exposing the typed
unavailable state.

For knowledge cutoff `T`, a fact is eligible only when its identity, filing,
artifact, every member of the ordered parse-authority set, amendment selection,
mapping version, publication run, decision, inputs
and fact were all known/effective and available by `T`. Historical reads select
that eligible version and never relabel a current row with an old cutoff.

#### Product visibility and API boundary

Authenticated canonical-fact APIs may expose a shared SEC actual to any user
authorized by the source policy. Responses include the canonical value and the
bounded provenance above, or a typed unavailable/unresolved reason. They may
return an authorized evidence resolver or canonical SEC source URL; they MUST
NOT return a raw-table browsing endpoint, arbitrary raw fact content, internal
storage key/path, filesystem URL, or local artifact location.

The publication write surface is an operator service/CLI with bounded stock,
mapping version and cutoff inputs. It is not a user endpoint and cannot accept
caller-defined metric keys, taxonomy rules, SQL, source precedence, or
timestamps.

Until FT-06 approves reconciliation, canonical reads preserve SEC, Value Line,
manual and calculated source roles separately. A dictionary overwrite, row ID,
query order, newest timestamp, or value satisfying a predicate cannot select
one source as truth. Mixed-source formulas, ratios, Piotroski inputs, screeners
and system valuations fail closed unless their governing contract explicitly
requires one eligible source role. User-authored valuation remains separate and
does not make a system financial source authoritative.

Industry applicability is also a separate gate. Raw SEC actuals may publish
regardless of economic class, but Owner Earnings, ROIC, per-share trend and
valuation outputs require a reviewed effective/knowledge-dated company
classification and approved method version, or return typed `unsupported`.
Foreign filing/currency regime is orthogonal to economic-method class. FT-04
does not approve a generic bank, insurer, REIT, high-SBC/acquisitive,
cyclical/commodity, or valuation formula, and ordinary price volatility or beta
cannot satisfy this gate.

### H.10 Exact source reconciliation (FT-06)

FT-06 is governed by `financial-source-reconciliation-v1` in the mapping spec.
It compares eligible canonical `metric_facts` from SEC, Value Line, manual, and
calculated roles. The result is a deterministic comparison/audit projection;
it is not a second fact store, does not change any per-period `is_current` slot,
and must not select a winning source.

The authenticated stock reconciliation read accepts a bounded optional metric
filter and a timezone-aware knowledge cutoff no later than the request time. It
returns the policy ID, mapping-spec digest, cutoff, exact ordered eligible fact
IDs, typed exclusions, comparison items, and a deterministic report digest.
Each comparison item includes only bounded canonical identity, source role,
fact IDs, outcome/reason, blocking state, and Decimal variance/tolerance when
variance is semantically eligible. It does not expose raw XBRL, proprietary
snippets, internal storage keys/paths, file URLs, or another user's facts.

Before variance, the service aligns the canonical definition and mapping
identity, fiscal period/duration, dimensions, normalized base unit/scale,
currency, fact nature, source identity and authorization, effective time, and
knowledge cutoff. A mismatch that makes values non-comparable is
`mapping_conflict` and has no numeric variance. A legacy owned parsed row whose
document/mapping identity was not retained may remain visible as single-source
data, but its identity is incomplete and it cannot establish a cross-source
match. Actual-versus-estimate,
as-filed-versus-adjusted, direct-versus-derived, and an explicit manual
correction are separate typed definition relationships; their values are never
treated as interchangeable merely because their metric key matches.

The approved outcomes are `match`, `expected_definition_difference`,
`restatement`, `mapping_conflict`, and `unresolved`. Tolerance uses Decimal
arithmetic only to identify a bounded match and prioritize review. It never
rewrites either fact, hides a material difference, or authorizes source
selection. Ambiguous current duplicates, missing derived/manual lineage,
material same-definition differences, or an otherwise unclassifiable
comparison are `unresolved`. Single-source coverage is a visible non-blocking
`unresolved` comparison state rather than evidence that a cross-source check
passed.

Eligibility is point-in-time and permission aware. A fact, source document,
canonical publication, mapping/policy version, derived input, and applicable
authorization must be known/effective and visible by the cutoff. Post-cutoff,
retired, unauthorized, cross-stock, cross-user, or unverifiable evidence is
excluded with a typed reason. Today's mutable non-SEC `is_current` projection
must not be relabeled as historical when its cutoff state cannot be proven. A
requested historical cutoff therefore returns the visible comparison as
`partial` with `historical_current_projection_unverifiable`, rather than a
false claim of complete PIT reconstruction.

Formula, ratio, Piotroski, screener, research, workspace, and other fundamental
consumers continue to read values only from `metric_facts`. A consumer may
request one source role when its own contract permits that role, but the
selection is explicit and cannot bypass a blocking `mapping_conflict` or
`unresolved` comparison for the same canonical slot. Without explicit source
selection, mixed source roles remain a typed `source_conflict`; even a `match`
does not invent a global source winner. Query order, dictionary overwrite,
highest row ID, newest row, or tolerance is never source authority.

Market-price authority, user intrinsic-value publication, valuation methods,
industry/economic applicability, new acquisition rights, and evidence
retirement/account erasure remain outside FT-06.

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
