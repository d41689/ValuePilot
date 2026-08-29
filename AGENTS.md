# ValuePilot — agent guide

ValuePilot is a financial-analysis engine that parses, stores, and analyzes
equity reports. This file is the **cross-agent contract** — every agent (Claude
Code, Cursor, Aider, Copilot) follows it. Deep, task-specific detail lives in
`docs/architecture/`; this file links to it where relevant. Read the linked doc
before working in that area.

## Product north star — the highest-priority principle

ValuePilot exists to help a serious long-term investor turn noisy, delayed, and
conflicting information into an **independent, falsifiable, source-traceable
capital-allocation decision**, then maintain the discipline to update or reject
that decision when the facts change.

The product does **not** optimize for stock tips, buy/sell signals, trading
activity, engagement, or the volume of data shown. When requirements compete,
prefer the behavior that best helps the user avoid permanent capital loss and
make a better-reasoned decision. Missing or conflicting evidence must remain
visible; false precision and silent assumptions are product failures.

Here, permanent capital loss means impairment of business earning power,
balance-sheet or refinancing capacity, accounting or management integrity, or
capital-allocation quality. It does not mean ordinary market-price volatility,
low beta, or a mechanical valuation threshold. A price move may prompt research;
it is not evidence of impairment or an investment conclusion by itself.

Every meaningful product capability should help the user do at least one of
these six jobs:

1. **Stay inside the circle of competence.** Decide whether the business is
   understandable enough for the user to evaluate and name what remains
   outside that understanding.
2. **Understand business quality.** Evaluate the business model, durable moat,
   management, capital allocation, return on invested capital, and the runway
   to reinvest at attractive incremental returns.
3. **Estimate normalized owner earnings.** Reconstruct trustworthy historical
   economics, distinguish reported facts from estimates and adjustments, and
   account explicitly for capital expenditure, working capital, stock-based
   compensation, acquisitions, and cyclicality when material.
4. **Value with a margin of safety.** Use explainable assumptions, scenarios,
   and ranges rather than treating a precise model output or another analyst's
   target as intrinsic truth.
5. **Disconfirm before deciding.** Steelman the opposing case, record evidence,
   decision rationale, risks, and falsifiable kill criteria, while preserving
   human authority over every investment conclusion.
6. **Monitor the thesis, not price noise.** Surface material thesis changes,
   preserve immutable decision history, and support review and postmortem so
   the user can improve the quality of future decisions.

An agent proposing or implementing a feature must be able to state which of
these jobs it advances and how success will be observed. A feature that cannot
make that connection is not a ValuePilot priority merely because it is
technically interesting or financially adjacent.

## Start here

- **Two tracks, one data layer.**
  - **v0.1 core** — parse **Value Line** equity-report PDFs (single-page
    standard layout) into normalized storage for screening and formulas.
    Non-Value-Line templates are out of scope: mark them `unsupported_template`.
  - **13F automation** — EDGAR ingestion + Oracle's Lens scoring + the
    Watchlist × 13F surface.
  - Both tracks write to and read from the same data layer (below).
- **Research Decision Support boundary.** Before changing research cases,
  AI-proposed research, valuation publication, point-in-time reconstruction,
  case origins, or option-underwriting analysis, read
  `docs/architecture/research-decision-support.md`.
- **Stack.** Python backend; TypeScript / React (Next.js) frontend; PostgreSQL;
  SQLAlchemy ORM (screening rules compile to SQLAlchemy expressions); shadcn/ui
  + Tailwind + lucide-react. JSON for semi-structured fields
  (`parsed_value_json`, `rule_json`).
- **Everything runs in Docker.** Never run Python or Node tooling on the host.
- **Definition of done.** Task logged where required, tests written first, every
  canonical CI command green in-container, no critical invariant violated.

## Canonical commands

Services: `api`, `web`, `db`. Run all tooling inside containers. The CI pipeline
(`.github/workflows/ci.yml`) runs exactly these commands, in this order:

| Step | Command |
|---|---|
| Start / rebuild | `docker compose up -d --build` |
| Migrations | `docker compose exec -T api alembic upgrade head` |
| Backend tests | `docker compose exec -T api pytest -q` |
| Frontend unit tests | `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` |
| Frontend lint | `docker compose exec -T web npm run lint` |
| Frontend build | `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` |

At any closing gate run these **verbatim** — full suites, not a narrower glob or
a single file. Details that matter: `-T` disables TTY allocation (required in
CI, harmless when run by hand); the frontend test glob `lib/*.test.js` discovers
source-scanner tests such as `lib/uiStandard.test.js`; the build sets
`NODE_ENV=production`. Targeted runs are fine for iteration
(`pytest -q tests/unit/test_x.py`, `node --test lib/x.test.js`) but never
substitute for the full command at a closing gate.

Logs: `docker compose logs -f`.

### Local database — shared infra (not the `db` service)

Dev connects to the **shared Postgres** used by all local projects, defined in
`~/projects/infra` (its own repo; `~/projects/infra/README.md` is the source of
truth). The compose `db` service is a sleep-infinity **placeholder** — do not
start a project-local Postgres.

- Start it once: `cd ~/projects/infra && cp -n .env.example .env && docker compose up -d`
- The api reaches it over the external `projects-shared` network at host
  `postgres:5432`, database `valuepilot` (prod `valuepilot_prod`), role
  `valuepilot`. Isolation is per database + role, not per instance.
- No auto-migrate on boot — after first start run the Migrations step above
  (`docker compose exec -T api alembic upgrade head`).

## Critical invariants — never violate

Violating any of these causes real data loss or production breakage.

1. **`metric_facts` is the only queryable source of truth.** Screeners and
   formulas read `metric_facts`, filter `is_current = true`, and compare on
   `value_numeric` (never on JSON). `metric_extractions` is an immutable audit
   trail — never modify it (manual corrections insert a new `metric_facts` row),
   and never query it for screening.
2. **Never globally dedup `is_current`.** It is per-*period* currency, not one
   row per `(stock_id, metric_key)`. A "one is_current per metric" cleanup
   migration or script wipes ~99% of fiscal time series and breaks Piotroski,
   the screener, the formula engine, and Oracle's Lens.
   → `docs/architecture/metric-facts-is-current.md`
3. **A DB constraint violation is fixed with a migration, never a code
   workaround.** Never truncate or rename a value to slip under a limit.
   → `docs/architecture/data-layer.md`
4. **No raw SQL from user input.** `rule_json` compiles to SQLAlchemy
   expressions; formula evaluation uses a restricted AST engine — never
   `eval` / `exec`.
5. **Normalize before writing `value_numeric`** — base units only, scale tokens
   respected. If a value cannot be normalized, leave `value_numeric` NULL and
   keep `raw_value` in JSON with error metadata.
6. **Every parsed metric carries provenance:** `document_id`, `page_number`,
   `original_text_snippet`.
7. **Run the exact canonical CI commands before calling work done.**

None of these is fully enforced by automation. A few have partial guards —
`metric_extractions.document_id` and `page_number` are DB `NOT NULL`; formula
evaluation runs through a restricted AST engine — but the gaps are real
(`original_text_snippet` and `metric_facts.source_document_id` are nullable; the
screener and `is_current` rules have no general check). Treat every invariant as
the agent's own responsibility, not something CI will catch.

## Workflow

### Task logging

- **Substantive change** — touches a data contract, a migration, parsing, the
  schema, or spans multiple files / is otherwise risky: before coding, create
  `docs/tasks/YYYY-MM-DD_<short-name>.md` with Goal / Acceptance Criteria, Scope
  (in / out), PRD references (when applicable), Files to change, and a Test plan
  (Docker commands). Keep it updated with decisions, gotchas, and a sign-off
  trail.
- **Trivial change** — a typo, a copy tweak, or a single localized fix with no
  contract or migration impact: no task doc required; a clear commit/PR
  description is enough.
- When unsure which tier applies, treat it as substantive.

### Test-first

Write or update tests first (red) → minimal production code to pass (green) →
refactor while keeping tests green.

### Deferred work

A change often surfaces more problems than it should fix at once. Never let a
discovered problem vanish silently.

- **Fix what is in scope; capture the rest.** Before calling the work done,
  record every out-of-scope problem you found.
- **Severity decides the channel.** A finding that risks data loss, a security
  hole, or production breakage is *not* yours to defer — stop and tell the user
  so they can decide. Everything else goes to the backlog.
- **The backlog is `docs/BACKLOG.md`** — one entry per item: date found, where
  (PR / task / file), the problem, severity, and a link to fuller context. It
  is in-repo on purpose: the entry shows up in the PR diff so the reviewer signs
  off on the deferral, and the next agent finds it by reading the repo. A GitHub
  issue is invisible to an agent's default context, so it cannot be the primary
  record.
- **The PR names what it defers.** A PR that knowingly leaves problems behind
  lists them and links `docs/BACKLOG.md`.
- **Promote long-lived items to GitHub Issues** for human triage and
  assignment; record the issue number on the backlog entry. Issues complement
  the register — they do not replace it.
- **Clear an entry in the same PR that resolves it.**

### Verification (closing gates)

When declaring work "ready", "shipped", or green, run the **exact** canonical CI
commands above — full suites, in-container, not a more-targeted version. A glob
is not a list of files. Long-lived branches mask failures because CI only fires
on push: if a branch will accumulate >10 commits before pushing, run the
canonical commands at each closing gate.

### Git / PR conventions

- One scoped feature or fix uses one dedicated branch and one PR. Never commit
  directly to `main`.
- A request to implement or fix something authorizes the agent to create the
  branch, make focused commits, push, and open or update a Draft PR unless the
  user says otherwise.
- Commit at meaningful, reviewable checkpoints; keep unrelated changes separate
  and run relevant tests before committing.
- Mark the PR ready only after the full closing gate and review pass. Merge,
  release, force-push, and destructive cleanup still require explicit user
  approval.
- After an approved merge, update `main` and clean up the merged branch or
  worktree safely.

### Per-PR checklist

- [ ] `docker compose up -d --build` succeeds.
- [ ] Migrations apply cleanly (if changed).
- [ ] Every canonical CI command green in-container.
- [ ] No critical invariant violated.

### When to stop and ask

Ask the user before: a change whose scope is ambiguous; anything irreversible or
outward-facing (deleting data, touching prod, force-pushing); or a decision that
contradicts a design marked "locked". Do not guess.

## Data layer

Three layers, strictly separated — raw artifact, extraction lineage, queryable
facts:

1. **`pdf_documents`** — the file and its metadata.
2. **`metric_extractions`** — the immutable **audit trail**: exactly what the
   parser found (raw text, snippets, page numbers). Never query it for
   screeners.
3. **`metric_facts`** — the **source of truth**: normalized, queryable data
   (`value_numeric`, canonical keys). Always use it for screeners, formulas, and
   UI display.

**Normalization** (applied before writing `value_numeric`): currency → absolute
amount (`1.2 bil` → `1200000000`); percentage → ratio 0–1 (`5.2%` → `0.052`);
price / per-share → absolute currency; scale tokens `k` / `m` / `b` / `t`
handled case-insensitively.

**Stock identity** — match by `ticker` + `exchange`, then compare `company_name`
similarity; on low similarity set `pdf_documents.identity_needs_review = true`
and never auto-link.

**Manual corrections** never mutate `metric_extractions`. Insert a new
`metric_facts` row (`source_type='manual'`, `is_current=true`) and demote the
prior row scoped to the same `(stock_id, metric_key, period_type,
period_end_date, source_type='manual')`.

Full detail — `is_current` semantics, the no-band-aid schema-change policy,
Alembic conventions, and upsert-vs-IntegrityError write-conflict handling:

- `docs/architecture/metric-facts-is-current.md`
- `docs/architecture/data-layer.md`

## Parsing

- **Scope** — Value Line templates only for v0.1; mark others
  `unsupported_template`.
- **Strategy** — native PDF text layer only. Pages whose text layer is too
  sparse to parse are reported as `requires_ocr`; actual OCR is **not yet
  implemented** (see `docs/BACKLOG.md`).
- **Mapping** — map template-specific field names (e.g. `18_month_target_low`)
  to canonical metric keys (e.g. `target_18m_low`). The authoritative mapping
  is `docs/metric_facts_mapping_spec.yml` (the earlier
  `value_line_v1_field_map.json` approach is deprecated and removed).

The required parser fixture-alignment workflow and the EDGAR / 13F parsing
gotchas are in `docs/architecture/parsing.md`.

## Coding standards

- **Metric keys** — `snake_case` only, no leading digit (`target_18m_low`, not
  `18m_target`).
- **Tables** — `snake_case` plural (`metric_facts`, `stock_pools`).
- **Error handling** — on a normalization failure keep `raw_value` in JSON,
  leave `value_numeric` NULL, and flag specific error metadata. Every parsed
  metric must include `document_id`, `page_number`, `original_text_snippet`.

## Frontend UI standard

*Enforced by `frontend/lib/uiStandard.test.js` (CI), which scans `app/`,
`components/`, and `features/`.*

- Use **shadcn/ui + Tailwind** for all product frontend. Shared controls live in
  `frontend/components/ui/` and follow the shadcn pattern: Radix primitives where
  appropriate, `class-variance-authority` for variants, `cn()` for class
  merging.
- Do **not** render raw HTML form/control primitives directly in app, feature,
  or shared business components. Use the shared components — `Button`, `Input`,
  `Textarea`, `Select`, `DropdownMenu`, `Checkbox`, `Table`, `Card`, `Badge`,
  `Toast`. If one does not exist yet, add it under `frontend/components/ui/`
  first, then use it.
- Use Tailwind only for layout and component-specific adjustments; keep focus
  rings, disabled states, and base sizing inside the shared components. Use
  lucide-react icons; avoid hand-rolled SVG controls.
- The scanner matches substrings **anywhere in a file, including comments**.
  When a comment needs to describe this rule, write "raw HTML button element"
  rather than spelling out the literal angle-bracket form.

---

Role-specific review prompts live in `docs/tasks/*-review-prompts.md` — follow
them case by case.
