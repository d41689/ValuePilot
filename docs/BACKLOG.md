# Backlog — deferred work

Problems discovered but not yet fixed. The capture rule is in
`AGENTS.md` → Workflow → "Deferred work". Each entry stays until the work is
actually done — remove it in the same PR that resolves it.

Severity: **high** = data-loss / security / production risk; should not sit here
long — escalate to the user. **medium / low** = ordinary follow-up.

## Open

### Development hot reload repeatedly creates quarantined 13F reparses
- **Found:** 2026-08-31, PR #131 post-review closing-gate run
- **Severity:** medium (audit-table growth and misleading repeated work; current
  13F projections remained unchanged)
- **Problem:** the default development API starts the 13F worker while Uvicorn
  watches the mounted source tree. During one review/edit cycle, reloads and a
  default Compose restart repeatedly processed two pending reparses, appending
  11 quarantined non-current parse runs and 480 holdings to shared `valuepilot`.
- **Acceptance criteria:**
  - A pending controlled reparse is claimed and reaches one durable terminal
    disposition; reload, restart, and concurrent-worker tests cannot append a
    second candidate for the same pending work.
  - Development hot reload does not run mutation-capable background jobs unless
    explicitly enabled, while production retains its intended worker behavior.
  - Operator surfaces distinguish a terminal quarantine from retryable work and
    do not enqueue or claim it again.
- **Context:** `backend/app/main.py`;
  `backend/app/services/thirteenf_job_worker.py`;
  `backend/app/services/thirteenf_controlled_reparse.py`;
  `docs/tasks/2026-08-30_sec-gold-set-acceptance-run.md`
- **Issue:** —

### Financial Truth & Decision Loop Beta — product exit gate
- **Found:** 2026-08-27, PO user-value acceptance of the local product
- **Severity:** high (the current product discovers ideas but cannot yet be
  relied on for a complete, trustworthy long-term investment decision)
- **Problem:** verified financial history, business understanding, defensible
  valuation, monitoring, and postmortem do not yet form one coherent user loop.
- **Outcome:** a serious investor can turn an idea into a falsifiable,
  source-traceable human decision and later explain what changed.
- **PO disposition:** the high-severity FT items are acknowledged next-stage
  blockers, not accepted deferrals. Do not claim the beta ready or expand
  dependent conclusions until their gates pass.
- **Acceptance criteria:**
  - The locked FT-00 manifest remains unchanged for the evaluation cycle and
    FT-01 through FT-15 below are resolved with version-pinned evidence.
  - The stage is evaluated against the locked manifest and protocols in
    `docs/plans/financial_truth_decision_loop_beta_acceptance.md`; fixtures are
    fixed before results are known and failures are not removed to pass.
  - Product financial-statement/fundamental fact reads use only `metric_facts`;
    prices use the canonical EOD contract, while raw artifacts and raw XBRL
    remain lineage rather than a second queryable financial truth.
  - The stage evidence package contains zero privacy leak, look-ahead, silent
    source substitution, conflicting current price, or unsupported industry
    formula published as valid; any one is an automatic failure.
  - The moderated protocol passes and demonstrates business-quality analysis,
    disconfirmation, valuation range, kill criteria, and a human-authored
    decision without treating 13F, AI, or a system reference as advice.
- **Context:** `docs/plans/financial_truth_decision_loop_beta_acceptance.md`;
  `docs/tasks/2026-08-27_value-core-and-next-stage-backlog.md`;
  `docs/architecture/research-decision-support.md`
- **Issue:** —

### FT-02 — evidence retirement without unauthorized retention or lost lineage
- **Found:** 2026-08-27, PO acceptance of `/documents`; adversarial review VG-01
- **Severity:** high (physical deletion can destroy lineage, while unconditional
  retention can violate proprietary-source permission or account erasure)
- **Problem:** the ordinary delete path erases sourced facts and extraction
  history, but replacing it with unconditional permanent readability would
  create a retention right forbidden by the source-visibility contract.
- **Outcome:** retire evidence without losing permitted lineage and without
  retaining or exposing content after authority is lost.
- **Acceptance criteria:**
  - The PRD and source policy, not this backlog, own retention/redaction rules;
    implementation references those rules without creating a parallel variant.
  - Ordinary removal archives/tombstones the document. Artifacts and extraction
    lineage are immutable **while retained**, and archived content is readable
    only while the governing policy and current authorization permit it.
  - Permission loss returns `source_unavailable`; historical research preserves
    only the identity/claim fields the PRD and source policy allow and never
    bypasses access by copying a proprietary excerpt into a revision.
  - Account erasure uses the PRD's audited redaction/tombstone exception and does
    not rewrite shared financial lineage or pretend the event never existed.
  - Tests cover archive, current projection reconciliation, permission
    revocation, cross-user access, account erasure, and referenced history.
- **Context:** `docs/architecture/research-decision-support.md` §10.2;
  `docs/prd/value-pilot-prd-v0.1.md` §G.2–G.3;
  `docs/architecture/coverage-source-policy.md`
- **Issue:** —

### FT-03 — SEC issuer identity, authorized acquisition, raw lineage, and PIT replay
- **Found:** 2026-08-27, PO real-data review; adversarial review VG-02/VG-06
- **Severity:** high (without authorized, replayable primary filings later facts
  cannot prove identity, provenance, or what was knowable at a cutoff)
- **Problem:** 13F EDGAR infrastructure exists, but no general financial-filing
  identity/acquisition/lineage path exists; the current source policy authorizes
  SEC only for 13F ingestion.
- **Outcome:** establish the independently testable primary-source foundation;
  do not map or publish product metrics in this item.
- **Progress (2026-08-27):** the first locked AAPL vertical slice now covers a
  reviewed effective-dated identity, submissions discovery, complete accession
  manifest, immutable content-addressed artifacts, versioned inline-XBRL raw
  facts, exact parse-run inputs, and PIT replay. A live latest-10-Q probe retained
  the submissions/index plus approved filing inputs, recorded all 67
  current-policy artifact observations, and extracted 860 raw facts with zero
  `metric_facts` publication; an exact rerun created zero rows. FT-03 remains
  open for the complete locked form/history/issuer scope and evidence package.
- **Progress (2026-08-31):** the locked 24-case run finalized two idempotent
  passes with verified retained lineage and zero `metric_facts`. Twenty-two
  cases cover their expected annual denominator; JPM is 3/10 and GS 5/10.
  Contract review found that another bounded operation currently restarts at
  the first 20 historical-submissions references rather than advancing through
  a retained-manifest cursor. It also found that early annual filings frequently
  have standalone XBRL instance documents rather than inline XBRL; the current
  retention/parser path does not preserve/parse those instances, leaving many
  pre-inline years as typed `no_inline_xbrl_facts`. Publication-grade FT-03
  therefore still requires a validated resumable cursor plus immutable
  standalone-instance retention and a new append-only parser version. The
  existing typed failures and Step-D evidence must not be rewritten.
- **Progress (2026-08-31, Step 2):** bounded continuation and parser-v2 are now
  implemented. Random persisted continuation authorities bind the retained main
  snapshot, identity, cutoff, full target and ordered validated references;
  each advance is backed by an immutable operation consumption claim and cursor
  validation failures have a separate durable terminal audit;
  the database now proves every ordered consumption outcome from same-operation
  retained snapshots/failures and reciprocally guards continuation failures and
  terminal results rather than trusting caller JSON or timestamps;
  standalone instance XML is retained through
  the existing artifact policy and parsed with namespace/local-name and
  structured unit QName lineage. Typed dimensions retain a bounded canonical
  namespace-aware structure with a database-verified digest; inline parser-v2
  obtains that authority from retained XHTML XML events rather than tolerant
  HTML normalization and fails closed when XML/context correspondence is not
  provable. Exact URI/local structural selection and expanded taxonomy-QName
  fact signatures prevent tolerant HTML or fake-namespace nodes from entering
  parser v2. The safe streaming authority rejects DTD/entities and clears
  completed nodes; the same expanded-root preflight is mandatory for service
  dispatch and standalone parsing, whose dimension structures now require exact
  XBRLDI identity. Standalone candidates carry frozen verified bytes through
  parsing and are storage-reverified before run creation. Token-aware Expat
  declaration handlers reject real DTD/entities without rejecting lexical text
  in comments, CDATA or processing instructions. Preflight returns the exact
  downstream bytes: UTF-8/16 stays original, while UTF-32 normalization changes
  only the XML declaration token and rejects BOM/declaration conflicts. Global parser and database resource budgets bound the retained
  structure. Standalone parsing exposes no caller-controlled preflight bypass;
  every direct or service invocation revalidates its downstream bytes. A fresh isolated acceptance acquisition remains
  required before FT-03 can be closed.
- **Acceptance criteria:**
  - Before acquisition expands, `coverage-source-policy.md` records permitted
    SEC financial forms, retention, automation, rate limits, and visibility.
  - Versioned issuer/listing-to-CIK identity has effective dates, share class,
    review state, and no low-confidence auto-link.
  - Incremental discovery and raw storage cover approved forms/amendments with
    accession, URL, accepted/fetched time, MIME, ETag when supplied, SHA-256,
    parser version, and complete artifact manifest.
  - Raw XBRL is immutable lineage only and no screener, formula, workspace, or
    other product consumer can query it as financial truth.
  - PIT selection and replay cannot observe filings, amendments, artifacts, or
    parse versions unavailable at the requested cutoff; idempotent replay and
    trap tests pass.
- **Context:** `backend/app/edgar/`; `backend/app/models/institutions.py`;
  `docs/architecture/coverage-source-policy.md`
- **Issue:** —

### FT-04 — canonical SEC mapping and `metric_facts` publication
- **Found:** 2026-08-27, adversarial review VG-02/VG-06
- **Severity:** high (a second SEC read store or undefined mapping would split
  canonical financial truth)
- **Problem:** raw filing facts require explicit, versioned conversion into the
  existing financial-fact contract before any product use.
- **Outcome:** publish permitted SEC actuals through `metric_facts` only.
- **Progress (2026-08-31):** the `sec-us-gaap-v1` metric contract, PRD
  publication boundary, and source-policy authorization are approved. They
  define strict namespace-URI/local-name authority, semantically distinct cash,
  equity and debt concepts, generic revenue, source-reported ISO currency
  without FX, form-first period classification, ordered exact parse-authority
  sets, compatible exact derived-quarter inputs, slot-level amendments, shared
  SEC ownership, exact NUMERIC publication, PIT, SEC-only per-period current
  slots, provenance and fail-closed consumer behavior before FT-06. No
  publication migration, service, API, gold-set fact, or production activation
  is implemented yet; this item remains open.
- **Acceptance criteria:**
  - Metric keys, units, normalization, period semantics, source roles, and
    mapping rules are approved in `metric_facts_mapping_spec.yml`; schema, APIs,
    publication lifecycle, and correction behavior are approved in the PRD;
    permission remains owned by source policy.
  - Screening, formulas, workspace, and every product fundamental-fact read
    query only `metric_facts`; raw SEC/XBRL tables remain lineage and review
    inputs. Market price continues through the separate canonical EOD contract.
  - Publication preserves raw-fact identity, accession, mapping version,
    knowledge time, fact nature, period/context, dimensions policy, unit, and
    currency without last-write-wins source precedence.
  - Period tests cover instant/duration, YTD/discrete quarter, subtraction-
    derived quarters, fiscal calendars, 52/53 weeks, amendments, dimensions,
    units, and unresolved custom concepts.
  - Replaying the same approved inputs is idempotent and produces the same
    per-period current slots without globally deduplicating history.
- **Context:** `docs/metric_facts_mapping_spec.yml`;
  `docs/architecture/metric-facts-is-current.md`;
  `docs/prd/value-pilot-prd-v0.1.md`
- **Issue:** —

### FT-05 — historical comparability and foreign-issuer gold-set coverage
- **Found:** 2026-08-27, adversarial review VG-03/VG-06
- **Severity:** high (a sourced ten-year series can still be economically false
  after splits, ADR changes, currency changes, or incompatible filing regimes)
- **Problem:** coverage and provenance alone do not prove that historical facts
  or per-share values are comparable.
- **Outcome:** complete the locked gold set with explicit comparability rather
  than concatenating incompatible observations.
- **Acceptance criteria:**
  - Approved mapping/PRD policy records as-filed versus adjusted basis,
    split/corporate-action version, share-class and ADR ratio, reporting currency,
    and any translation basis; this backlog does not invent those semantics.
  - Foreign-form coverage includes the forms required by the locked manifest,
    including 20-F/6-K cases, without presenting interim 6-K availability as a
    guaranteed 10-Q-equivalent contract.
  - Each manifest case covers every available year in its locked denominator up
    to ten completed fiscal years; every missing year has a typed, reviewed
    disposition and no estimate fills an actual-history gap.
  - A series that cannot be made comparable under approved policy returns typed
    `unsupported`/`unavailable` and blocks per-share trend, growth, and valuation
    consumers that depend on it.
  - Gold-set reports reproduce the cutoff, source/mapping versions, coverage
    denominator, conflicts, and comparability decisions.
- **Context:** `docs/plans/financial_truth_decision_loop_beta_acceptance.md`;
  `docs/metric_facts_mapping_spec.yml`; `docs/prd/value-pilot-prd-v0.1.md`
- **Issue:** —

### FT-06 — SEC, Value Line, and derived-fact reconciliation
- **Found:** 2026-08-27, PO source review; adversarial review VG-02
- **Severity:** high (definition differences can become a silent source override)
- **Problem:** SEC as-filed actuals, Value Line adjusted actuals/estimates, and
  ValuePilot calculations have different roles and require comparison, not a
  newly invented precedence service.
- **Outcome:** expose differences through the existing canonical fact and
  evidence boundary without creating another financial truth.
- **Acceptance criteria:**
  - Mapping spec owns metric/source semantics, PRD owns reconciliation storage
    and API behavior, and source policy owns permission; implementation links
    those authorities and defines no parallel precedence contract.
  - Reconciled fundamental metric values shown to product consumers come from
    `metric_facts`; any reconciliation record is comparison/audit state, not a
    second fact store. This rule does not relocate market prices or user-owned
    research/portfolio records into `metric_facts`.
  - Comparison aligns definition, fiscal period/duration, dimensions, unit,
    currency/scale, fact nature, and knowledge date before computing variance.
  - Reviewed statuses distinguish match, expected definition difference,
    restatement, mapping conflict, and unresolved without rewriting either source.
  - Tolerances prioritize review but never hide a material unresolved difference;
    the locked gold set has zero silent source substitution.
- **Context:** `docs/architecture/research-decision-support.md` §2 and §5;
  `docs/metric_facts_mapping_spec.yml`; `docs/prd/value-pilot-prd-v0.1.md`
- **Issue:** —

### FT-07 — industry applicability and permanent-impairment method gate
- **Found:** 2026-08-27, adversarial review VG-03 and omitted-risk finding
- **Severity:** high (generic industrial-company formulas can publish false
  Owner Earnings, ROIC, trends, or valuation for banks, insurers, and REITs)
- **Problem:** industry and business-model applicability is not implied by
  complete data. Unsupported economics must block conclusions.
- **Outcome:** each analytical output is governed by an approved, versioned,
  auditable applicability policy or is visibly unsupported.
- **Acceptance criteria:**
  - Mapping spec owns input semantics and the PRD owns calculation/publication
    behavior and classification/applicability lifecycle for every gold-set
    primary stratum; no formula or company classification is adopted from the
    non-normative Vision or issuer-name inference alone.
  - Banks, insurers, REITs, ordinary operating companies, high-SBC/acquisitive
    businesses, and cyclical/commodity businesses each have an approved method
    and required evidence, or return typed `unsupported` and block the affected
    Owner Earnings, ROIC, per-share trend, and valuation conclusion.
  - Every result records method/version, company classification at calculation
    time, inputs, adjustments, unsupported reasons, and source/knowledge cutoff.
  - Balance-sheet/refinancing risk, accounting credibility, management
    integrity, dilution, and capital allocation are evidence-backed or typed
    unknown; ordinary price volatility or low beta cannot satisfy this gate.
  - Golden and negative tests cover every manifest stratum, including attempts
    to apply an ordinary-company method to financials, insurers, and REITs.
- **Context:** `docs/Investment_Research_Vision.md` §9–§15 (non-normative);
  `docs/metric_facts_mapping_spec.yml`; `docs/prd/value-pilot-prd-v0.1.md`
- **Issue:** —

### FT-08 — decision-centered research workspace
- **Found:** 2026-08-27, PO acceptance of `/research/cases/2`; review VG-03/VG-05
- **Severity:** medium (the current workspace leaves users to synthesize a raw
  fact table and blank form unaided)
- **Problem:** the workspace is organized around fields and metric keys rather
  than the questions required before allocating capital.
- **Outcome:** guide evidence-based judgment without authoring the decision.
- **Acceptance criteria:**
  - The workspace covers circle of competence; business model/value drivers;
    moat; management integrity and capital allocation; balance-sheet/refinancing
    risk; accounting credibility; applicable Owner Earnings/ROIC and reinvestment;
    valuation; disconfirmation; kill criteria; and decision rationale.
  - Trends show investor-readable labels, actual/estimate and comparability state,
    units, provenance, and material changes; raw keys are an optional evidence view.
  - System observations remain proposals/references with supporting and
    conflicting evidence and require explicit human acceptance before revision.
  - Traceability and usability pass the exact interaction, participant, task,
    and success protocol in the beta acceptance document.
  - Missing, inaccessible, conflicting, or method-unsupported coverage blocks
    affected conclusions and identifies the next evidence action.
- **Context:** `frontend/app/(dashboard)/research/cases/[id]/page.tsx`;
  `docs/plans/financial_truth_decision_loop_beta_acceptance.md`
- **Issue:** —

### FT-09 — owner-earnings valuation ranges without false precision
- **Found:** 2026-08-27, PO acceptance of `/stocks/ASML/dcf`; review VG-03
- **Severity:** high (a generic precise value can create unjustified confidence)
- **Problem:** the current DCF uses a simplified owner-earnings proxy, one growth
  path, and a 1,000-year terminal-stage approximation.
- **Outcome:** produce explainable human-controlled underwriting ranges only
  when the approved company-method and comparability gates pass.
- **Acceptance criteria:**
  - FT-01, FT-05, and FT-07 gates are enforced; unsupported industry method,
    incomparable history, or invalid price blocks the dependent output.
  - The applicable owner-economics bridge exposes all policy-required inputs and
    adjustments—including maintenance/growth investment, working capital, SBC,
    acquisitions, dilution, balance sheet, and currency basis when material—with
    provenance and typed unknown/not-applicable states.
  - Maintenance capex is an explicit user assumption or the output of an
    approved versioned method; the system never presents a mechanically inferred
    amount as an observed fact.
  - Bear/base/bull hypotheses and opportunity/discount-cost assumptions are
    user-authored or visibly proposed; no system/analyst reference self-publishes.
  - Growth is reconciled to reinvestment economics or labeled unsupported;
    terminal value uses a guarded explicit formulation, never a 1,000-year fiction.
  - Results emphasize ranges and sensitivity; golden/negative tests cover every
    supported manifest method plus cyclical, negative, and insufficient-data cases.
- **Context:** `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`;
  `frontend/lib/dcfMath.js`; `docs/prd/value-pilot-prd-v0.1.md` §G.4
- **Issue:** —

### FT-10 — automatically materialize research coverage with each case
- **Found:** 2026-08-27, PO acceptance of the ASML case and `/admin/coverage`
- **Severity:** medium (an open case can have no evaluated requirements)
- **Problem:** case creation and coverage evaluation are disconnected.
- **Outcome:** every case explains which evidence is ready, missing, blocked,
  stale, inaccessible, or unsupported and what the user should do next.
- **Acceptance criteria:**
  - Create/reopen idempotently materializes authoritative requirements without
    an admin button; case and inbox show source, freshness/as-of, reason, and next action.
  - Ownership follows authenticated user/workspace authority and admin aggregates
    reveal no user, case, document, holding, or requirement detail.
  - Current-date results agree across consumers; unsupported historical
    reconstruction fails closed with the canonical reason.
  - Tests cover repeat evaluation, transitions, supersession, permissions,
    missing data, blocked source, inaccessible evidence, and unsupported method.
- **Context:** `backend/app/services/research_coverage.py`;
  `backend/app/services/research_cases.py`
- **Issue:** —

### FT-11 — consistent and explainable Oracle's Lens consumer state
- **Found:** 2026-08-27, PO acceptance of `/home` and `/13f/oracles-lens`;
  adversarial review VG-05
- **Severity:** medium (inbox rankings can coexist with an empty, indefinitely
  loading source dashboard)
- **Problem:** readiness, clusters, ranking, and inbox do not present one
  coherent period/snapshot and bounded terminal state.
- **Outcome:** every Lens consumer explains the same versioned research signal.
- **Acceptance criteria:**
  - PRD/API contract owns snapshot identity, period and scope semantics;
    dashboard, clusters, inbox, watchlist, and case origin share them or expose
    an explicit documented scope difference.
  - Browser acceptance passes the exact 10-second settling and 15-second hard-
    stop SLO plus all fixtures defined in the beta protocol; no permanent spinner.
  - Counts and readiness come from one versioned snapshot or carry distinct
    scope/version labels that prevent comparison as if they were identical.
  - Candidate evidence retains signal/version/period and caveats; user surfaces
    hide operator policy codes/ranks, while authorized diagnostics remain separate.
  - Economic-entity/share-class dedup prevents duplicate attention slots unless
    the listing distinction is material and explicitly explained.
- **Context:** `docs/plans/financial_truth_decision_loop_beta_acceptance.md`;
  `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`
- **Issue:** —

### FT-12 — thesis monitoring and consented notification delivery
- **Found:** 2026-08-27, PO acceptance; adversarial review VG-06
- **Severity:** medium (the habit loop needs an independently releasable trigger
  and delivery boundary)
- **Problem:** monitoring and notifications were bundled with portfolio and
  postmortem despite separate authority, failure modes, and release value.
- **Outcome:** surface material thesis/review obligations without engagement-
  driven alerts or trading implications.
- **Acceptance criteria:**
  - Monitoring derives from explicit claims, evidence/supersession, review dates,
    and kill criteria; price movement alone can request review but cannot assert
    thesis impairment or a trade conclusion.
  - Notifications are consented, permission-scoped, deduplicated, explain why
    they matter, link to currently authorized evidence, and fail closed otherwise.
  - Replay, cooldown, quiet-hour, retry, revocation, inaccessible-source, and
    cross-user tests prove no duplicate send, silent loss, or content leak.
  - Unconfigured/disabled destinations make zero external network attempts and
    secrets never enter logs, audit payloads, APIs, or frontend state.
- **Context:** `docs/plans/research_decision_loop_product_roadmap.md` Phase 4;
  `docs/architecture/research-decision-support.md`
- **Issue:** —

### FT-13 — manual portfolio decision journal without trading rails
- **Found:** 2026-08-27, PO acceptance; adversarial review VG-06
- **Severity:** medium (portfolio context has distinct ownership, currency, and
  lifecycle risks and should be independently releasable)
- **Problem:** portfolio journaling was coupled to notification and calibration.
- **Outcome:** relate exposure and user actions to the supporting research while
  remaining explicitly non-broker, non-execution, and non-tax.
- **Acceptance criteria:**
  - Portfolio/position/journal ownership and server authorization follow PRD;
    each material action links the case/revision knowable at that time.
  - Manual or permitted imported observations retain provenance, knowledge time,
    currency, stale state, and decimal semantics without becoming financial facts.
  - Append-only open/resize/close/review events survive edits and closures;
    privacy redaction follows the PRD exception rather than silent deletion.
  - UI/API make no broker, execution, tax-lot, tax-correctness, recommendation,
    or automatic-allocation claim; lifecycle and cross-user tests pass.
- **Context:** `docs/plans/research_decision_loop_product_roadmap.md` Phase 5;
  `docs/prd/value-pilot-prd-v0.1.md` §G
- **Issue:** —

### FT-14 — decision postmortem and process calibration
- **Found:** 2026-08-27, PO acceptance; adversarial review VG-06
- **Severity:** medium (decision learning is independently valuable and should
  not be blocked on notification or portfolio delivery)
- **Problem:** postmortem and calibration lacked a separately closable outcome.
- **Outcome:** help users distinguish decision-process quality from later price
  outcome and improve future assumptions without rewarding activity.
- **Acceptance criteria:**
  - A postmortem compares the original immutable decision, later revisions,
    evidence knowable at each cutoff, valuation-assumption deltas, kill criteria,
    and outcome without back-projecting current facts.
  - Process assessment is separate from return/price performance and does not
    rank users by trading frequency, short-term returns, or hindsight correctness.
  - Users can inspect which assumptions, evidence judgments, and precommitted
    criteria failed or held, with typed unavailable evidence and source policy enforced.
  - No AI-generated calibration becomes the user's accepted conclusion without
    explicit action; PIT, closure, redaction, and usability protocol tests pass.
- **Context:** `docs/plans/research_decision_loop_product_roadmap.md` Phase 5;
  `docs/plans/financial_truth_decision_loop_beta_acceptance.md`
- **Issue:** —

### FT-15 — licensed EOD history, corporate actions, and optional live quotes
- **Found:** 2026-08-27, PO real-data acceptance and adversarial loop 2
- **Severity:** high (current-price consistency alone cannot support historical
  valuation, per-share comparability, or PIT-safe postmortem)
- **Problem:** the current provider path is primarily a single-target-date EOD
  refresh. It lacks an accepted 10–15-year history, provider/listing identity,
  adjustment policy, corporate-action lineage, and delisted-name coverage.
- **Outcome:** provide licensed, source-traceable daily market history for the
  user-directed research universe; treat intraday quotes as a separate optional
  convenience, not as canonical EOD truth.
- **Acceptance criteria:**
  - Before production fetch, source policy records the provider's permitted API
    use, storage/retention, display/redistribution, history depth, corporate-
    action/adjustment semantics, quota, and automation limits; development-only
    data cannot satisfy production coverage.
  - The PRD owns provider-symbol/MIC/listing identity, raw versus adjusted close,
    currency, observed/provider time, source batch/hash, correction/version,
    split/dividend/symbol-change/delisting, and PIT read behavior.
  - At the locked evaluation cutoff, the recorded scope snapshot covers the
    manifest, then-open cases, watchlist, and approved candidate set for every
    provider-entitled daily session up to 15 years; each expected session is a
    valid bar or typed market-calendar/provider/listing-life gap.
  - Corrections and corporate actions are append-only/versioned; a historical
    as-of read cannot use an observation, adjustment, or action version learned
    after its cutoff.
  - Cross-listing, share-class, ADR-ratio, currency, split, dividend, symbol-
    change, stale, missing, and delisted fixtures prove raw/adjusted series and
    prevent false per-share or return comparisons.
  - Optional live/intraday quotes use a separately authorized, visibly timed
    contract and bounded cache; they never overwrite canonical EOD or create a
    tick-history/trading claim. If unconfigured, the product remains fully usable
    with EOD data and makes zero live-provider calls.
  - This item makes no survivorship-free or quant-ready claim; those remain
    gated by the separate quant data-sufficiency contract.
- **Context:** `backend/app/services/market_data_service.py`;
  `backend/app/models/stocks.py`; `docs/architecture/coverage-source-policy.md`;
  `docs/plans/financial_truth_decision_loop_beta_acceptance.md`
- **Issue:** —

### Frontend Browserslist compatibility data is stale
- **Found:** 2026-07-19, zero-database rehearsal closing gate
- **Severity:** low (dependency-maintenance warning; build output and product
  behavior are unaffected)
- **Problem:** The canonical production build succeeds but reports that its
  bundled `caniuse-lite` data is seven months old. Updating it changes frontend
  dependency metadata and should be handled as a narrow dependency-maintenance
  change, not folded into the 13F correctness repair.
- **Fix sketch:** run the official Browserslist database updater in the web
  container, review the lockfile-only dependency diff, then rerun frontend
  tests, lint, and production build.
- **Context:** `docs/tasks/2026-07-19_13f-current-code-zero-db-rehearsal.md`
- **Issue:** —

### 13F sector allocation has no canonical queryable taxonomy
- **Found:** 2026-07-19, Dataroma manager-workbench implementation
- **Severity:** low (investor-analysis coverage gap; no data correctness regression)
- **Problem:** Dataroma's manager holdings page includes a sector-percentage
  analysis, but ValuePilot's `stocks` identity table has no canonical sector or
  industry field and the 13F source itself does not provide one. Inferring sector
  from issuer names would produce precise-looking but unauditable allocations.
- **Fix sketch:** choose a licensed/canonical classification source, persist its
  taxonomy and provenance by stock identity, define unmapped/changed-sector
  semantics, then add the allocation to manager holdings and history.
- **Context:** `docs/tasks/2026-07-19_13f-manager-research-workbench.md`
- **Issue:** —

### ~~OpenFIGI matcher silently drops mega-caps whose CUSIP has no US-composite listing~~ (RESOLVED — curated CUSIP overrides)
- **Found:** 2026-07-10, PR (13f-data-trust-guardrails) — surfaced by the new
  `HIGH_IMPACT_CUSIP_UNRESOLVED` guardrail
- **Severity:** **high** (real product-value loss — the two largest names in the
  affected set are invisible in Oracle's Lens; recurs every quarter on prod)
- **Problem:** `evaluate_openfigi_matches` only auto-confirms a CUSIP→ticker when
  a listing with `exchCode == "US"` (the composite) is present. For some
  mega-caps OpenFIGI returns **no US-composite row at all** — the US listings come
  back under venue codes. Live `mapCusips` on 2026-07-10: ExxonMobil `30231G102`
  → 14 listings, 6 agree on ticker `XOM` under codes `PE/CB/CX/UZ/OU/QU` (plus
  foreign `EXMOC/XOMCHF/XOM_KZ/1XOMM`), **zero `US`**; Honeywell `438516106` → 4
  listings, all foreign-currency variants, **zero `US`**. Both fall to
  `review_needed:low` and never link, so ExxonMobil (~10 managers, ~$1.2B) and
  Honeywell (~4 managers) are absent from Oracle's Lens. Re-running enrichment
  cannot fix it — the heuristic itself is the gap.
- **Resolved:** 2026-07-10, curated CUSIP overrides
  (`docs/tasks/2026-07-10_13f-curated-cusip-overrides.md`). Live evidence killed
  the "US-venue consensus heuristic" option: for HON the correct ticker `HON` is
  **absent from the response entirely** (only `HONGBP/EUR/…`), and Carnival
  `143658300` is the same (only `CCL1USD/EUR/…`), so a forward-lookup heuristic
  would either fail or **mis-link to a foreign-currency ticker** — worse than a
  known-unresolved CUSIP. Fix is a deterministic, human-verified override seed
  (`seed_data/curated_cusip_overrides.json`, XOM + HON) applied by
  `seed_curated_cusip_overrides()` at the start of every full enrichment pass
  (gated by `CUSIP_OVERRIDE_SEED_ENABLED`, prod on at the data gate). It rides
  the existing rank-4 `manual` precedence: beats any OpenFIGI row, never
  downgraded by a later run, auto-creates the `Stock` and links holdings via the
  existing bootstrap/backfill. `evaluate_openfigi_matches` is deliberately NOT
  changed. Tests: `test_13f_curated_cusip_overrides.py` (8, incl. no-US-listing
  override, rank-4 protection, idempotency, prior-manual conflict). Dev probe:
  loader is an idempotent no-op for the already-resolved XOM/HON (unchanged=2,
  0 applied, 0 regression). The `HIGH_IMPACT_CUSIP_UNRESOLVED` guardrail remains
  the detection half of the loop for the next mega-cap an operator must add.
- **Context:** `docs/tasks/2026-07-10_13f-data-trust-guardrails.md`,
  `docs/tasks/2026-07-10_13f-curated-cusip-overrides.md`
- **Issue:** —

### Managers page has no per-manager data-health column
- **Found:** 2026-07-10, PO review of `/admin/13f`
- **Severity:** medium (visibility gap, not data loss)
- **Problem:** The acute per-manager gap — a confirmed manager that never files —
  is now surfaced on the admin overview by the `CONFIRMED_MANAGERS_NOT_FILING`
  guardrail. But `/admin/13f/managers` still shows no per-manager health at a
  glance: last filing quarter, holdings count, linked-CUSIP ratio, or a
  never-filed / stale badge. An operator triaging the manager universe cannot see
  which specific managers are thin without drilling into each.
- **Fix sketch:** add a health column (last-filed quarter + a stale/never-filed
  badge + linked-ratio) to the managers list, sourced from the same queries the
  guardrails already use. Additive UI; own PR.
- **Context:** `docs/tasks/2026-07-10_13f-data-trust-guardrails.md`
- **Issue:** —

### ~~CLI `reparse-filing` / `reparse-all` write product-invisible legacy holdings~~ (F7 — RESOLVED T4 rework)
- **Found:** 2026-07-08, T4 external review (correctness finder)
- **Severity:** medium (product-visibility / footgun — no audit-trail loss)
- **Resolved:** 2026-07-08, T4 rework (second review escalated F7 to a merge
  blocker: the commands are advertised in `README.md` and destructive). Both
  `reparse_filing` and `reparse_all` (`backend/app/cli/edgar.py`) now delegate to
  the ParseRun-backed `reparse_accession` job via the locked runner
  (`run_locked_job`). `reparse_accession` swaps `is_current` and RETAINS the
  prior run's holdings — non-destructive. Verified on real dev data: reparsing
  `0001325447-26-000009` created a new current parse_run (602 rows) and retained
  the old run's 602, with 0 NULL-parse_run rows globally. (That accession is the
  *inactive* original — superseded by restatement `0001325447-26-000018` — so
  `active_hr_holdings_query` correctly returns 0 for it and 602 for the active
  restatement; ParseRun currency alone is not product visibility.) Regression:
  `test_13f_cli_ingest.py` — source guard + CliRunner wiring + a real
  `run_locked_job('reparse_accession')` integration test asserting
  `active_hr_holdings_query` visibility on an active filing (and 0 on an inactive
  one), plus a runtime `reparse-all` partial-failure non-zero-exit test. README
  copy updated.

### ~~Active-filing selection is scattered; accepted_at unpopulated; restatement ties + concurrency unhandled~~ (RESOLVED T1-FU)
- **Found:** 2026-07-08, T1 external review (`2026-07-08_13f-t1-restatement-activation-fix-review-results.md`)
- **Severity:** medium (correctness/robustness; no active data loss — T1 made the
  winner deterministic and crash-free)
- **Resolved:** 2026-07-08, T1-FU (`docs/tasks/2026-07-08_13f-t1fu-active-filing-authority.md`).
  One authority `apply_active_filing_policy` (thirteenf_filing_detail) now makes
  every activation decision — `apply_amendment_policy`,
  `reconcile_restatement_activation` (thin delegate), and the ingest job's
  per-group sweep (replacing the Phase-4c solo-HR heuristic + Phase-5 loop) all
  call it under a `pg_advisory_xact_lock` keyed on (manager_id,
  quarter_end_date). `accepted_at` is populated on the bulk path
  (`apply_primary_doc_metadata` + `backfill_period_routing`; 373/373 real
  filings backfilled, 0 NULL). Ties = equal AND non-NULL accepted_at
  (NULL→accession_no fallback preserves T1); restatement ties don't auto-switch
  (warning + amendments_pending). Also fixed in passing: rejected restatements
  can no longer be re-activated by a pipeline re-run; an NT can no longer beat
  an HR for the active slot; the tie-recovery dead code. Real-data sweep over
  355 groups: 0 flips, 0 dup-active. Tests: `test_13f_active_filing_authority.py`
  (15, incl. a two-session lock-serialization test).

### ownership_changes has no first-class "position" layer — per-lot rows fragment a stock held under multiple CUSIPs
- **Found:** 2026-07-08, T2 external review (design verdict)
- **Severity:** low (cleanliness / consumer ergonomics; no crash, no data loss —
  shares are all accounted for, just split across rows)
- **Problem:** the normal `_compute_rows` path keys change rows per-CUSIP (via
  the PRD §7.4 fallback). A stock held under two CUSIPs that both persist across
  quarters yields two change rows for one stock_id (one keyed `stock:<id>`, one
  keyed `cusip:<other>`), and merged provenance fields (current_holding_id,
  current_cusip) reference one lot. T2 aggregates only the unavailable branch
  (where rows collide on the unique key); it deliberately does NOT aggregate the
  matched path (pre-aggregating breaks cross-quarter CUSIP-fallback — see the
  T2 review's [P1] #1). Fine for now, but consumers that treat one change row as
  "the position" see fragments.
- **Fix sketch:** a first-class positions read-model derived from raw holdings
  (sum shares/value per (stock, ssh_prnamt_type, position_type), honest lot
  provenance), consumed by the changes/holders APIs — instead of duck-typing
  `Holding13F` at compute time. Also covers put/call aggregation separation and
  representative-CUSIP semantics. Raw infotable rows stay the audit trail.
- **Context:** `docs/tasks/2026-07-08_13f-t2-ownership-changes-orchestration-review-results.md` (Design Verdict)

### Cross-filer double-count review guard for combination attribution (deferred)
- **Found:** 2026-07-08, T3 (combination attribution) — deferred from the PO ruling
- **Severity:** low (not currently triggerable)
- **Problem:** T3 attributes DFND/OTR holdings to the filer (`direct`). If a
  combination filer AND one of its included sub-managers were BOTH tracked as
  separate universe managers that each report the same position, consensus/
  holder counts could double-count. Not possible in the current 82-manager
  universe (sub-managers are not tracked separately), so no guard was built.
- **Fix sketch:** when adding managers, or in a periodic quality check, flag any
  two universe managers reporting the same (stock, quarter) via a combination
  linkage for human review rather than silently double-counting.
- **Context:** `docs/tasks/2026-07-08_13f-t3-combination-attribution.md` (Scope: Out)

### ~~CLI ingest commands write product-invisible legacy holdings (no ParseRun)~~ (F6 — RESOLVED T4)
- **Found:** 2026-07-08, during first real-data ingestion into dev
- **Severity:** medium
- **Resolved:** 2026-07-08, T4 (`docs/tasks/2026-07-08_13f-t4-cli-ingest-hygiene.md`).
  `backfill` / `ingest-holdings` in `backend/app/cli/edgar.py` no longer call the
  legacy `ingest_filing_holdings`; they delegate to the modern `ingest_holdings`
  job (`execute_job_payload` → `_execute_ingest_job` → `ingest_if_needed`), so CLI
  ingest is ParseRun-backed and product-visible, with the Phase-4 heal + solo-HR
  activation the legacy path lacked. Regression: `test_13f_cli_ingest.py`
  (`test_ingest_pending_holdings_delegates_to_job_per_quarter`).

### ~~CLI `backfill` skips the newest report quarter's holdings (period-proxy window miss)~~ (F5 — RESOLVED T4)
- **Found:** 2026-07-08, during first real-data ingestion into dev
- **Severity:** medium
- **Resolved:** 2026-07-08, T4. `backfill` Step 2 now selects pending filings via
  `pending_ingest_quarters` (grouping by each un-ingested filing's *proxy*
  `period_of_report` = `filed_at`, i.e. the filing quarter) and delegates each
  quarter to the ingest job — so the newest report quarter's filings, filed the
  following calendar quarter, land in the right job window instead of being
  silently skipped. Regression: `test_13f_cli_ingest.py`
  (`test_pending_ingest_quarters_covers_newest_report_quarter`).

### Rate Guard public path has no auth-failure / abuse observability
- **Found:** 2026-07-08, PR #103 staff review
- **Severity:** medium
- **Problem:** No metric or alert exists for 401s or for public traffic hitting
  `rate-guard.richmom.vip`. A leaked key or brute-force spray would first surface
  as our egress IP getting banned by SEC/OpenFIGI. `/v1/metrics` tracks upstream
  volume only; the auth middleware emits no 401 signal and no source-IP visibility.
- **Fix sketch:** (1) a counter on 401s in the auth middleware + alert on 401-rate
  spikes; (2) a Cloudflare WAF rate-limit rule on `rate-guard.richmom.vip` +
  source-IP via CF logs (CF sees the real client IP before the tunnel); (3) alert
  on anomalous `/v1/fetch` volume.
- **Context:** `docs/tasks/2026-07-07_rate-guard-public-auth-review-results.md` (#9);
  see also `docs/architecture/rate-guard-public-exposure.md` → Deferred hardening

### Rate Guard shared key — split dev/prod values; consider edge auth
- **Found:** 2026-07-08, PR #103 staff review
- **Severity:** low
- **Problem:** One static `RATE_GUARD_API_KEY` value is shared across dev, prod,
  and the remote dev box. The two-slot mechanism (`RATE_GUARD_API_KEY` +
  `RATE_GUARD_API_KEY_PREVIOUS`) now supports distinct/rotating keys, but distinct
  values are not yet provisioned. A leak grants full egress-proxy access under our
  IP/User-Agent, and the same key also gates dev.
- **Fix sketch:** (1) give the remote box its own key (second slot), revocable on
  its own; (2) as a future option, move auth to Cloudflare Access service tokens /
  mTLS for per-client identity + revocation, keeping the app bearer as
  defense-in-depth (Option B keeps the app bearer for now).
- **Context:** `docs/tasks/2026-07-07_rate-guard-public-auth-review-results.md` (#4)

### 13F CUSIP enrichment — monitor MUTUAL FUND / OPEN-END FUND / UNIT auto-confirms in production
- **Found:** 2026-05-22, PR #93 review (advisory #1)
- **Severity:** low
- **Problem:** The new `_EQUITY_LIKE_SECURITY_TYPES` allowlist in
  `backend/app/services/cusip_enrichment.py` includes `MUTUAL FUND`,
  `OPEN-END FUND`, `CLOSED-END FUND`, and `UNIT`. These are the most permissive
  entries on the list — a 13F filer's common-holding row (`put_call IS NULL`)
  legitimately resolves to a mutual-fund / closed-end-fund ticker in some
  cases, but a `UNIT` could also be a SPAC pre-business-combination unit
  bundling common + warrants. Once production accumulates a few quarters of
  data, scan `cusip_ticker_map.confidence='high'` rows where the matched
  securityType is one of these four, eyeball the auto-confirmed tickers
  against the issuer name, and tighten or split the allowlist if any tier
  shows mis-routes.
- **Context:** [docs/tasks/2026-05-22_13f-cusip-enrichment-adr-cins.md](docs/tasks/2026-05-22_13f-cusip-enrichment-adr-cins.md);
  [docs/tasks/2026-05-22_13f-cusip-enrichment-adr-cins-review-results.md](docs/tasks/2026-05-22_13f-cusip-enrichment-adr-cins-review-results.md)
- **Issue:** —

### 13F `_check_period_alignment` quality subcheck still uses filing-quarter
- **Found:** 2026-05-22, PR #90 review round 1 (P2)
- **Severity:** low
- **Problem:** Every other check in `run_quality_checks()` scopes by
  `period_of_report` (report quarter) via `_quarter_filter()`, but
  `_check_period_alignment()` (`backend/app/services/edgar_quality.py`) still
  interprets its `quarter` arg as a *filing* quarter — it filters
  `filed_at BETWEEN :f_start AND :f_end` and expects `period_of_report` in
  `quarter-1`. After the F1/F2 report-quarter fix, `quality_check` receives a
  report quarter, so this subcheck inspects the wrong filing set (the filings
  *filed in* that quarter, which report on the prior quarter) and can miss
  period anomalies for the requested report quarter. Non-blocking — it only
  emits info/warning lines. Fix needs a rethink of what the check should assert
  under the report-quarter model (likely: verify each filing's `report_quarter`
  matches its actual `period_of_report`).
- **Context:** `docs/tasks/2026-05-21_13f-web-validation.md` (Review round 1, R-P2)
- **Issue:** —

### Rate Guard rollout is in-place, with no staged probe or rollback
- **Found:** 2026-05-20, PR #79 (Rate Guard deploy integration) review
- **Severity:** low
- **Problem:** `scripts/deploy_prod_from_main.sh` brings Rate Guard up with
  `docker compose up -d --build` — an in-place stop→start with no blue-green
  swap and no automatic rollback. If a deploy ships a broken `rate-guard/`
  change, the previously-healthy shared instance is already replaced before
  `/healthz` fails. PR #79 itself is safe (nothing depends on Rate Guard yet,
  and a failed healthcheck aborts before the prod stack), and in-place rebuild
  is the existing model for all services. But once PR 2/4 routes live EDGAR
  traffic through Rate Guard, a safer rollout (staged probe of the new image
  before swap, or keep-old-on-failure) is worth doing.
- **Context:** `docs/tasks/2026-05-20_rate-guard-deploy-integration-review-result2.md`
  (follow-up 2); address as part of Rate Guard PR 2/4.
- **Issue:** —

### Admin metrics panel is EDGAR-only — no OpenFIGI / Dataroma view
- **Found:** 2026-05-21, Rate Guard PR 4/4 (admin panel reads `/v1/metrics`)
- **Severity:** low
- **Problem:** Rate Guard now tracks per-upstream metrics for all three
  upstreams (EDGAR, OpenFIGI, Dataroma) at `GET /v1/metrics`, but the admin
  panel still shows only EDGAR (`build_edgar_rate_limit_status()` calls
  `metrics("edgar")`). OpenFIGI / Dataroma rate-limit budget, 403/429 counts,
  cache hit rate, and global-pause state are collected but not surfaced. A
  multi-upstream admin view (or three panels) would make the whole egress layer
  observable. Out of PR 4's scope, which the design scoped to the EDGAR panel.
- **Context:** `docs/tasks/2026-05-21_rate-guard-pr4-admin-metrics.md`
- **Issue:** —

### Expired `refresh_tokens` rows are never purged
- **Found:** 2026-05-21, refresh-token revocation work
- **Severity:** low
- **Problem:** The `refresh_tokens` store gains one row per `/auth/refresh`
  (plus one per login). Nothing deletes rows whose `expires_at` has passed, so
  the table grows unbounded. Safe to defer — a row past `expires_at` is already
  rejected by the JWT `exp` check regardless, and the v0.1 user base is small —
  but a periodic purge (`DELETE FROM refresh_tokens WHERE expires_at < now()`,
  with a supporting index on `expires_at`) should land before broader rollout.
- **Context:** `docs/tasks/2026-05-21_refresh-token-revocation.md` (Scope → Out)
- **Issue:** —

### `refresh_tokens` FOR UPDATE concurrency path has no test
- **Found:** 2026-05-21, PR #86 review (both reviewers, advisory E14)
- **Severity:** low
- **Problem:** `rotate_refresh_token` (`backend/app/core/refresh_tokens.py`)
  serializes two concurrent refreshes of the same token with
  `SELECT ... FOR UPDATE`, so a self-race is caught as reuse instead of
  double-minting a successor. The branch is correct by inspection but has no
  automated test — a reliable one needs two real DB connections racing the same
  `jti` on separate threads, which the shared-session unit harness
  (`backend/tests/conftest.py`) cannot express. Add a multi-connection
  integration test before broader / multi-user rollout.
- **Context:** `docs/tasks/2026-05-21_refresh-token-revocation-review-result.md`
  and `..._review-results.md`, both item E14.
- **Issue:** —

### Interceptor-level tests for `frontend/lib/api/client.ts`
- **Found:** 2026-05-20, PR #64 (refresh-token flow)
- **Severity:** low
- **Problem:** The response interceptor's single-flight / retry / recursion
  behaviour has no unit test; only the pure helpers in `authSession.js` are
  covered.
- **Context:** `docs/tasks/2026-05-20_auth-hardening-followups.md` (item 2)
- **Issue:** —

### 13F CUSIP mappings flagged `needs_review` — human triage queue
- **Found:** 2026-05-21, after the OpenFIGI enrichment run (the original
  "link rate stuck at ~12%" item, PR #84, is resolved — see below)
- **Severity:** low
- **Problem:** The 2026-05-21 `enrich_cusip` run lifted the holdings link rate
  from 12.5% to 77.8% (12,443 / 15,995 linked). Of the residual: **2,160
  holdings are `needs_review`** — OpenFIGI returned an ambiguous result
  (multiple US-common-stock listings with conflicting tickers, or no
  US-common-stock listing), so `evaluate_openfigi_matches` flagged the mapping
  `review_needed:*` instead of auto-confirming. They need human triage via the
  existing admin CUSIP-mappings review surface
  (`GET /admin/13f/cusip-mappings/unresolved`). A further ~1,390 holdings are
  `unresolved` — OpenFIGI has no usable match (non-US, bonds, delisted, …), a
  genuinely hard tail. This is ongoing curation, not a code defect; the
  enrichment pipeline itself works and is re-runnable for future quarters.
- **Context:** `docs/tasks/2026-05-21_cusip-link-rate-diagnosis.md`
- **Issue:** —

### Extended historical backfill
- **Found:** 2026-05-20, /admin/13f operational audit (item #11)
- **Severity:** low
- **Problem:** The Overview surfaces an "Extended backfill recommended" P3
  task — run a historical backfill to deepen quarter coverage. Optional
  maintenance; skipped during the audit. Run via Manual Controls → Backfill
  when the EDGAR rate-limit budget allows.
- **Context:** `docs/tasks/2026-05-20_admin-13f-ops-audit.md` (item #11)
- **Issue:** —

### CSP `script-src` still allows `'unsafe-inline'`
- **Found:** 2026-05-21, CSP work (the original "no `Content-Security-Policy`
  header" item is resolved — a static CSP now ships, see below)
- **Severity:** low
- **Problem:** The CSP added in `frontend/lib/csp.js` is a *static* policy, so
  `script-src` keeps `'unsafe-inline'` — it does not block an injected inline
  script. Every other directive is locked down (`object-src 'none'`, `base-uri`,
  `form-action`, `frame-ancestors`, source-restricted
  `default`/`connect`/`img`/`font`/`style`), so this is the one remaining CSP
  gap. A genuinely strict `script-src` needs either a per-request nonce (Next.js
  then forces every page into dynamic rendering — see the task doc trade-off) or
  the experimental `experimental.sri` hash-based CSP once it is stable. Revisit
  before broader / multi-user rollout.
- **Context:** `docs/tasks/2026-05-21_content-security-policy.md`
- **Issue:** —

### Value Line parser: full OCR integration for scanned archives
- **Found:** 2026-07-02, Value Line parser historical-readiness review (for
  quant Phase 1 / 1-R0 archive ingestion)
- **Severity:** high — historical Value Line archives are largely scans; until
  OCR lands they cannot be ingested at all. Pages are now honestly reported as
  `requires_ocr` (F7) instead of silently skipped, but nothing OCRs them.
- **Problem:** `PdfExtractor` is native-text-only. The `requires_ocr` /
  `text_extraction_method="ocr"` enums existed unused; F7 wired the detection
  but real OCR (tesseract in the api image + an OCR extraction path) is not
  implemented.
- **Fix sketch:** add tesseract to the api Docker image; OCR pages flagged
  `requires_ocr`; set `text_extraction_method="ocr"`; validate against real
  scanned samples per decade acquired in 1-R0. Do not build before samples
  exist.
- **Context:** `docs/tasks/2026-07-02_value-line-parser-historical-readiness.md`
- **Issue:** —

### Value Line parser: x0-coordinate column alignment for annual tables
- **Found:** 2026-07-02, parser historical-readiness review (P1-5)
- **Severity:** high — count-based year↔value alignment (`_align_years` +
  drop-leading-outlier heuristics) can silently assign values to wrong years;
  for backtests this is the most toxic error class (no error, plausible value,
  wrong year).
- **Problem:** `_parse_time_series_tables` aligns rows to the year header by
  token count, not by word x0 coordinates, although `page_words` layout data
  is already extracted. The ADS/insurance "drop leading outlier" patches are
  symptoms of this design.
- **Fix sketch:** rewrite table row extraction to bucket value tokens by the
  year-header column x-ranges. Requires per-era historical fixtures (1-R0) as
  the safety net before refactoring — current heuristics pass all 55 modern
  fixtures.
- **Context:** `docs/tasks/2026-07-02_value-line-parser-historical-readiness.md`
- **Issue:** —
- **PO disposition (2026-07-20):** do not expand the historical corpus or make
  backtest claims until representative era fixtures exist and this alignment is
  implemented. Modern supported-template use remains enabled. See
  `docs/architecture/coverage-source-policy.md`.

### Value Line parser: verify fiscal column-year labeling convention
- **Found:** 2026-07-02, parser historical-readiness review (P1-8)
- **Severity:** medium
- **Problem:** the parser assumes the annual-table column year equals the
  calendar year the fiscal year ends in (`date(year, fye_month, last_day)`).
  For companies whose FY ends early in the calendar year (e.g. January FYE),
  Value Line's column-labeling convention may be off by one vs this
  assumption. Also `fiscal_year_end_month` is inferred solely from the
  quarterly table month order and silently falls back to December.
- **Fix sketch:** verify against real non-calendar-FYE samples (ADBE Nov,
  AAPL Sep, Jan-FYE retailers) across eras; add fixtures pinning the
  convention.
- **Context:** `docs/tasks/2026-07-02_value-line-parser-historical-readiness.md`
- **Issue:** —
- **PO disposition (2026-07-20):** same historical-expansion block as the x0
  item above; no inferred convention is accepted without real non-calendar-FYE
  evidence.

### Value Line page JSON: era-hardcoded key names
- **Found:** 2026-07-02, parser historical-readiness review (P2-13)
- **Severity:** low
- **Problem:** page JSON keys are hardcoded to the 2026-era layout
  (`annual_financials_and_ratios_2015_2026_with_projection_2028_2030`,
  `projection_2028_2030`) and will be semantically wrong (though functional)
  for historical reports. `docs/metric_facts_mapping_spec.yml` depends on the
  literals.
- **Fix sketch:** era-neutral key names behind a schema-version bump; blast
  radius = mapping spec + all 55 fixture expected JSONs, so do it as its own
  ticket.
- **Context:** `docs/tasks/2026-07-02_value-line-parser-historical-readiness.md`
- **Issue:** —

### 13F: follow-manager affordance
- **Found:** 2026-07-03, PO value-investor review of the 13F surface
  (`docs/tasks/2026-07-03_13f-po-review-value-investor.md` §3)
- **Severity:** medium
- **Problem:** There is no way for a user to follow specific managers; the
  filing-season digest (investor-workflow ticket 03) is featured-managers-only
  in V1, and the manager pages (ticket 01) have no personalization. The 13F
  habit loop ("my managers reported") needs per-user follows eventually.
- **Fix sketch:** small `manager_follows(user_id, manager_id)` table + star
  toggle on the manager list/detail pages; digest targeting switches from
  is_featured to followed-or-featured.
- **Context:** `docs/tasks/2026-07-03_13f-investor-workflow-03-filing-season-digest.md`
- **Issue:** —

### 13F: holding-streak saturation recalibration after historical backfill
- **Found:** 2026-07-03, PO value-investor review (§3)
- **Severity:** low (becomes medium once backfill lands)
- **Problem:** Conviction/persistence saturate at a 4-quarter streak — an
  artifact of the 2023+ data window, not an investment judgment. A value
  investor cares about 5+ year holders; once historical backfill extends the
  window, 4-quarter saturation materially understates long-tenure conviction.
- **Fix sketch:** revisit `_PERSISTENCE_STREAK_FULL` (conviction_score.py) and
  the streak bonus threshold together with a `SCORE_VERSION` bump, gated on
  backfilled data depth (readiness `historical depth` metric).
- **Context:** `docs/tasks/2026-07-03_13f-po-review-value-investor.md`
- **Issue:** —

### 13F: watchlist quarter-over-quarter trend + export
- **Found:** 2026-07-03, PO value-investor review (§4/§5)
- **Severity:** low
- **Problem:** Watchlist 13F columns show only the latest period (no QoQ
  conviction/Δ-holders trend sparkline), and no surface offers CSV export of
  candidates/holdings for offline research.
- **Fix sketch:** trend mini-viz on the watchlist 13F drawer once ≥3 quarters
  of persisted score history exist; simple CSV export endpoints for the
  Oracle's Lens candidates table and manager holdings.
- **Context:** `docs/tasks/2026-07-03_13f-po-review-value-investor.md`
- **Issue:** —

### 13F: `enrich_metadata` reports `new_stocks: 0` while creating thousands of stocks
- **Found:** 2026-07-10, prod-zero rehearsal (`claude/13f-prod-zero-rehearsal`)
- **Severity:** low (observability, not correctness)
- **Problem:** `enrich_all_unmapped_holdings` calls `bootstrap_stocks_from_cusip_map`
  once *after* its loop, but the per-batch path has already created the Stock
  rows, so the post-loop call returns 0. The sandbox created 1896 stocks and
  every `enrich_metadata` summary reported `new_stocks: 0`. An operator reading
  the job summary would conclude no stocks were created.
- **Fix sketch:** count created stocks inside the batch loop, or drop the
  post-loop bootstrap's return value from the summary and report the delta in
  `stocks` instead.
- **Context:** `docs/tasks/2026-07-09_13f-prod-zero-rehearsal.md`
- **Issue:** —

### 13F: a Rate Guard HTML error page is stored verbatim in `job_runs.summary_json`
- **Found:** 2026-07-10, prod-zero rehearsal
- **Severity:** low (observability)
- **Problem:** When the Rate Guard tunnel returns a Cloudflare 502, the whole
  HTML body (with IE conditional comments) is embedded in the daily-sync
  `last_error` and persisted into `JobRun.summary_json`. The actual signal — the
  HTTP status — has to be recovered by reading HTML out of JSONB. `edgar_fetch`
  errors should carry a status code and a truncated body.
- **Fix sketch:** in the Rate Guard client, raise with `status_code` and the
  first ~200 chars of the body; store both as structured fields.
- **Context:** `docs/tasks/2026-07-09_13f-prod-zero-rehearsal.md`
- **Issue:** —

### 13F: M5 (turn on the prod switches) must not ship before the pipeline fixes land
- **Found:** 2026-07-10, prod-zero rehearsal
- **Severity:** high (blocking dependency, no action needed until M5 opens)
- **Problem:** Turning on `EDGAR_SCHEDULER_ENABLED` / `THIRTEENF_JOB_WORKER_ENABLED`
  / `THIRTEENF_START_QUARTER` in prod *before* the `_ingest_candidate_filings`
  and `enrich_metadata` fixes would ingest holdings that never get scored, and
  would leave the newest report quarter permanently `pending` — while every job
  reported green. M5 depends on `claude/13f-prod-zero-rehearsal`.
- **Fix sketch:** land the rehearsal branch first; the cross-stage
  `pipeline_warning` guard then makes a regression visible in the admin job list.
- **Context:** `docs/tasks/2026-07-09_13f-prod-zero-rehearsal.md`
- **Issue:** —

### 13F: M5 needs startup-path tests the current suite does not have
- **Found:** 2026-07-10, external review of PR #115 (Missing Tests §7)
- **Severity:** medium (blocks M5, not this PR)
- **Problem:** `MANAGER_SEED_ON_STARTUP` is fail-loud by design, but no test covers
  what the API does when the database is unavailable at boot, when the seed's
  `pg_advisory_xact_lock` waits behind another container, or when real prod data
  puts managers in the `ambiguous_name_match` / `awaiting_confirmation` buckets.
  Fail-loud, hang, and degraded-start are three different outcomes and only one is
  acceptable.
- **Fix sketch:** boot-path tests with a refused connection, a held advisory lock
  in a second session, and a seeded ambiguous row; assert the process exits rather
  than hangs, and that the exit is distinguishable in the container logs.
- **Context:** `docs/tasks/2026-07-09_13f-prod-zero-rehearsal.md` (external review round)
- **Issue:** —

### 13F: 11 curated managers have a CIK that never files a 13F
- **Found:** 2026-07-10, verifying the from-zero rehearsal's claim that the pipeline "parses 13F data correctly"
- **Severity:** high — silent, product-visible, changes Oracle's Lens consensus
- **Problem:** `institution_managers` holds 82 confirmed managers; only 71 have ever
  produced a filing. The other 11 carry a CIK that is not the entity filing the 13F
  (Chou and Trian are off by one digit). `ingest_quarter_index` whitelists by CIK, so
  a wrong CIK matches nothing, forever, silently. `min_holders = 3` means Oracle's
  Lens consensus has been computed over 71 managers, missing Icahn, Einhorn, Tepper,
  Dalio, Peltz, ValueAct, Bridgewater, FPA, Third Avenue, Chou and Fundsmith.
  Verified against 45 319 13F records across 5 stored `form.idx` quarters: none of
  the 11 seeded CIKs appears as a filer in any of them. The other 71 are name-consistent
  with their EDGAR filer — no manager ingests the wrong filer's holdings.
  `match_cik_candidates()` cannot catch it: it only scans `cik IS NULL AND
  match_status IN ('seeded','candidate')`.
- **Fix sketch:** see the ticket. Correct the 11 CIKs; add a read-only
  `audit_seed_ciks` job that checks each confirmed CIK against EDGAR; add a readiness
  check for "confirmed manager, zero filings in the last N quarters"; then recompute
  ownership_changes + Lens for every quarter, because fixing this IS a universe change.
- **Context:** `docs/tasks/2026-07-10_13f-seed-cik-audit.md`
- **Issue:** —

### 13F: fixing the seed CIKs cannot repair an existing database — RESOLVED 2026-07-10 (PR #116)
- **Found:** 2026-07-10, while correcting `confirmed_managers.json`
- **Resolved:** `previous_ciks` + an audited `seed_cik_repoint` event make re-seed idempotent on an existing DB (`created=0`, one row per manager). The downstream recompute remains in the ticket.
- **Severity:** high (blocks applying the CIK fix to dev/prod)
- **Problem:** `seed_confirmed_managers` looks a manager up by `cik`, then by
  `dataroma_code`. A **changed** CIK is found by neither for 10 of the 11 corrected
  managers (only Bridgewater carries a dataroma_code). The seed therefore takes the
  CREATE path: where the normalized name still collides it refuses
  (`ambiguous_name_match`, loud and safe), and where the legal_name also changed —
  Icahn (`ICAHN CAPITAL MANAGEMENT LP` → `ICAHN CARL C`) and Greenlight
  (`GREENLIGHT CAPITAL INC` → `DME Capital Management, LP`) — it would mint a
  DUPLICATE confirmed manager row. An empty database is unaffected; dev and prod are not.
- **Fix sketch:** teach the seed a `previous_ciks` field (or an explicit re-point
  admin action that writes an `InstitutionManagerCikReviewEvent`), so a CIK change is
  an audited identity edit rather than a create. Then re-seed, backfill the 11
  managers' filings, and re-run `compute_ownership_changes` +
  `oracles_lens_score_backfill` for every quarter — adding 11 managers IS a universe
  change and `min_holders = 3` makes it a scoring change.
- **Context:** `docs/tasks/2026-07-10_13f-seed-cik-audit.md`
- **Issue:** —

### 13F: six managers report values in thousands under a dollars schema — RESOLVED 2026-07-18
- **Found:** 2026-07-10, from-zero rehearsal with the corrected seed
- **Severity:** medium (absolute values wrong by 1000x; weights and Lens unaffected)
- **Problem:** Every holding is tagged `value_unit_raw='dollars'`,
  `value_parse_rule='schema_dollars'`. Six managers file in **thousands** anyway, so
  their `value_usd` is 1000x too small. Detected by median implied share price
  (`value_usd / shares`), which should be $1–$1,000,000 for a US equity:
  Olstein $0.08, **Baupost / Klarman $0.12**, Vulcan $0.15, Triple Frond $0.22–0.25,
  AKO $0.28–0.29, Aquamarine $0.48–0.50. Compliant filers land where you'd expect:
  Berkshire $92–97, Bridgewater $77–80, Greenlight $25–30.
  The reconciliation check cannot catch this — the filer's own `tableValueTotal` is
  in the same wrong unit, so computed and reported agree exactly. Oracle's Lens is
  unaffected (portfolio weight is a within-manager ratio, hence scale-invariant), but
  every absolute dollar figure the product shows for those six is 1000x low.
- **Fix sketch:** an implied-price sanity check at ingest (median `value/shares`
  outside $0.50–$1e6 → flag), feeding the existing `effective_value_unit_override`
  mechanism instead of `infer`. Add it to `edgar_quality` as a warning first.
- **Context:** `docs/tasks/2026-07-10_13f-seed-cik-audit.md`
- **Issue:** —

**Resolution:** The holdings parser now cross-checks post-2023
`schema_dollars` filings against a conservative filing-level median implied
price (common positions only, minimum three observations). It switches to
`implied_price_thousands` only when the raw median is below $0.50 and the 1000x
corrected median is plausible. Parser/fingerprint v2 makes ordinary quarterly
re-runs converge existing rows. A live empty-DB 2026-Q1 replay corrected 167
current holdings across the five currently non-compliant filers; the lowest
remaining common-stock median is $1.00 and compliant filings were unchanged.
### Quant H3 historical filing/amendment PIT selector

- **Found:** 2026-07-21, `T-2026-07-21-quant-trading-1-r0a`
- **Where:** `docs/architecture/quant-trading-pit-read-contract.md` §7;
  future `backend/app/services/quant_trading/pit_reader.py`
- **Problem:** product-facing 13F reads correctly use today's active filing and
  current successful parse, but historical H3 research must instead select the
  filing/amendment version observable at T. The audit found 49 manager-quarters
  with multiple successful versions; back-projecting today's active version
  would create look-ahead. No H3 factor or holdout run may start until the
  version-aware PIT selector and trap tests exist.
- **Severity:** high — future research-integrity / false-alpha risk; currently
  contained because 1-R0A is NO_GO and 1-R1…1-R4 are closed.
- **Context:**
  `docs/tasks/2026-07-21_quant-trading-1-r0-data-sufficiency-adversarial-review.md`
