# Project Context
**ValuePilot v0.1** is a financial analysis engine designed to parse, store, and analyze equity reports.
The v0.1 scope is strictly limited to **Value Line equity report PDFs** (single-page standard layout).
The system focuses on precise data extraction, strict data lineage (audit trails), and normalized storage for screening and formulas.


# Tech Stack
- **Language**: Python 3.10+
- **Database**: PostgreSQL (Relational, strictly typed)
- **ORM**: SQLAlchemy (Screening rules are compiled to SQLAlchemy expressions)
- **Parsing**: Template-based extraction (PDF text layer first, OCR fallback)
- **Data Exchange**: JSON for semi-structured data (`parsed_value_json`, `rule_json`)

# Development & Execution Environment (Docker Compose)

ValuePilot is developed and run via **Docker Compose**. Agents MUST assume the local runtime is containerized.

## Canonical Commands

- Start services:
  - `docker compose up -d --build`
- View logs:
  - `docker compose logs -f`
- Run commands inside a service container:
  - `docker compose exec <service> <command>`
  - Example: `docker compose exec api pytest -q`

## Rules
- DO NOT run Python tooling directly on the host when a containerized alternative exists.
- Always prefer running tests, linters, migrations, and scripts via `docker compose exec`.

# Architecture & Data Modeling Principles

## 1. The "Three-Layer" Storage Pattern
We strictly separate raw artifacts, extraction lineage, and queryable facts.
1.  **`pdf_documents`**: Stores the file and metadata.
2.  **`metric_extractions`**: The **Audit Trail**. Stores exactly what the parser found (raw text, snippets, page numbers). **NEVER** query this table for screeners.
3.  **`metric_facts`**: The **Source of Truth**. Stores normalized, queryable data (numeric values, canonical keys). **ALWAYS** use this table for screeners, formulas, and UI display.

## 2. Stock Identity Resolution
- **Stocks are Global Master Data**.
- **Ingestion Logic**:
  1. Match by `ticker` + `exchange`.
  2. If matched, compare `company_name` similarity.
  3. If similarity is low, set `pdf_documents.identity_needs_review = true`. **DO NOT** auto-link without confirmation.

## 3. Metric Normalization (Critical)
All data written to `metric_facts.value_numeric` MUST be normalized to base units.
- **Currency**: Absolute amounts (e.g., "1.2 bil" -> `1,200,000,000`).
- **Percentages**: Ratios between 0 and 1 (e.g., "5.2%" -> `0.052`).
- **Prices/Per Share**: Absolute currency (e.g., EPS 3.25 -> `3.25`).
- **Scale Tokens**: Handle `k`, `m`/`mil`, `b`/`bil`, `t`/`tril` case-insensitively.

# Business Rules & Constraints

## Parsing Logic
- **Scope**: Only support "Value Line" templates for v0.1. Mark others as `unsupported_template`.
- **Strategy**: Try Native Text Layer -> If density low -> Fallback to OCR.
- **Mapping**: Map template-specific field names (e.g., `18_month_target_low`) to **Canonical Metric Keys** (e.g., `target_18m_low`).
  - Refer to `value_line_v1_field_map.json` for authoritative mappings.

## Data Integrity
- **Immutability**: parsed records in `metric_extractions` are **immutable**.
- **Corrections**: If a user corrects a value:
  1. DO NOT update `metric_extractions`.
  2. Insert a NEW row into `metric_facts` with `source_type = 'manual'` and `is_current = true`.
  3. Set previous fact's `is_current = false`.

## Formulas & Screeners
- **Dependency**: Formulas form a DAG (Directed Acyclic Graph).
- **Trigger**: When a `metric_fact` is updated/inserted, trigger recalculation for dependent formulas.
- **Filtering**: Screeners MUST use `value_numeric` fields, not JSON fields.

# Coding Standards

## Naming Conventions
- **Metric Keys**: `snake_case` ONLY. NO leading numbers. (e.g., `target_18m_low`, not `18m_target`).
- **Tables**: `snake_case` plural (e.g., `metric_facts`, `stock_pools`).

## Error Handling
- **Normalization Failures**: If a value cannot be normalized (e.g., unknown unit), store the `raw_value` in JSON but leave `value_numeric` as `NULL`. Flag specific error metadata.
- **Traceability**: Every parsed metric MUST include `document_id`, `page_number`, and `original_text_snippet`.

# Development Workflow (Agent Instructions)

## 1. Task Logging (Required)

Before making any code changes, create a task entry in `docs/tasks/`:
- File naming: `YYYY-MM-DD_<short-task-name>.md`
- Must include:
  - Goal / Acceptance Criteria
  - Scope (in / out)
  - Files to change
  - Test plan (what will be run in Docker)

Agents MUST keep the task file updated as work progresses (notes, decisions, gotchas).

## 2. Test-First Implementation (TDD)

For any feature or bugfix:
1. Write or update tests first (red).
2. Implement the minimal production code to pass (green).
3. Refactor safely while keeping tests green.

Definition of Done:
- All relevant tests pass in Docker
- No contract violations vs PRD (data lineage, normalization, safety)
- Clear change summary in the task log

## 3. Running Tests (Docker Only)

Agents MUST run verification commands inside containers, e.g.:
- `docker compose exec api pytest -q`
- `docker compose exec api pytest -q tests/test_value_line_parse_ao_smith.py`
- `docker compose exec api alembic upgrade head` (when migrations change)

If tests fail:
- Fix bugs and re-run until all tests are green.

## 4. Safety & Data Contract Checks (Always-On)

- Screeners MUST query `metric_facts` and filter on `is_current = true`.
- Screeners MUST filter on `value_numeric` for numeric comparisons (not JSON).
- Rule evaluation MUST compile `rule_json` to SQLAlchemy expressions (never raw SQL).
- Formula evaluation MUST use a restricted AST engine (never eval/exec).
- Parsing MUST respect scale tokens (mil/bil/%) and normalization before writing `value_numeric`.
- Every parsed metric MUST include `document_id`, `page_number`, and `original_text_snippet`.

## 5. Minimal Verification Checklist (Per PR)

- [ ] `docker compose up -d --build` succeeds
- [ ] Migrations apply cleanly (if changed)
- [ ] `pytest` is green inside container
- [ ] No raw SQL generation from user input
- [ ] `metric_facts` remains the only queryable source of truth (Active Value uses `is_current = true`)
# End-to-End Agent-Driven Development Flow (Authoritative)

This section defines the **canonical development lifecycle** for ValuePilot.
All human contributors and Agents MUST follow this flow once the PRD is established.

---

## Phase 0: PRD Baseline (Human Only)

**Role**: Tech Lead / Human Owner  
**Input**: `docs/prd/value-pilot-prd-v0.1.md`  
**Output**: Approved, frozen PRD

Rules:
- The PRD is the highest-level contract.
- No Agent may modify PRD content unless explicitly instructed.
- All downstream work MUST reference PRD sections explicitly.

---

## Phase 1: Task Creation (Human → Orchestrator Agent)

**Role**: Human (author), Orchestrator Agent (assistant)  
**Input**: PRD section(s), user intent  
**Output**: Task file in `docs/tasks/`

### Step 1.1 Create Task File (Human)

Create:
`docs/tasks/YYYY-MM-DD_<short-task-name>.md`

Minimum required content:
- Goal / Acceptance Criteria
- Scope (In / Out)
- PRD References (exact sections)
- Test Plan (Docker commands)

### Step 1.2 Task Decomposition (Orchestrator Agent)

The Orchestrator MAY:
- Propose subtasks
- Identify risks and contracts touched
- Suggest verification steps

The Orchestrator MUST NOT:
- Change scope
- Invent requirements
- Modify schema or PRD

---

## Phase 2: Planning (Orchestrator Agent → Human Approval)

**Role**: Orchestrator Agent  
**Input**: Task file  
**Output**: Execution Plan (written into task file)

Plan MUST include:
- Files to be changed
- Order of execution
- Contract checks (schema, normalization, safety)
- Rollback strategy

Human MUST approve the plan before implementation begins.

---

## Phase 3: Test-First Implementation (Agent Execution)

**Role**: Implementation Agent (Parser / Rules / Schema / UI)

### Step 3.1 Write Tests First (Red)

Agent MUST:
- Write failing tests that encode acceptance criteria
- Commit test intent clearly (no placeholders)

### Step 3.2 Minimal Implementation (Green)

Agent MUST:
- Implement only what is required to satisfy tests
- Avoid opportunistic refactors

### Step 3.3 Refactor Safely (Green)

Agent MAY:
- Improve structure or readability
- ONLY if all tests remain green

---

## Phase 4: Verification (Agent + Docker)

**Role**: Implementation Agent  
**Runtime**: Docker Compose ONLY

Required commands (as applicable):
- `docker compose exec api pytest -q`
- `docker compose exec api pytest -q <specific-test>`
- `docker compose exec api alembic upgrade head`

Agent MUST:
- Fix all failures
- Re-run tests until green
- Record verification results in task file

---

## Phase 5: Contract Gate (Self-Check)

**Role**: Implementation Agent  
**Output**: Contract checklist in task file

Agent MUST explicitly confirm:
- `metric_facts` is the only source queried by screeners
- `value_numeric` is normalized and used for comparisons
- No raw SQL from user input
- No eval/exec for formulas
- Lineage fields are present
- `is_current` semantics preserved

---

## Phase 6: Human Review & Merge

**Role**: Tech Lead / Human Owner

Human reviews ONLY:
- Contract adherence
- Test coverage of critical paths
- Absence of unnecessary complexity

If approved:
- Merge changes
- Mark task as DONE

---

## Phase 7: Post-Merge Recording

**Role**: Human or Agent (if instructed)

Required:
- Update task file with final notes
- Update PRD / AGENTS.md if semantics changed

---

# Canonical Prompts by Role (Reference)

## Orchestrator Agent Prompt

"You are the Orchestrator Agent for the ValuePilot project.
Your job is to decompose approved tasks into executable steps.
You MUST:
- Respect the PRD as immutable
- Propose clear subtasks and verification steps
You MUST NOT:
- Modify schema or requirements
- Invent new functionality
Output only structured plans."

---

## Implementation Agent Prompt

"You are an Implementation Agent for ValuePilot.
You MUST:
- Follow the approved execution plan
- Use Test-Driven Development
- Run all verification via Docker Compose
- Respect all data contracts and safety rules
You MUST NOT:
- Modify PRD or schema without approval
- Use eval, exec, or raw SQL for user input
- Skip tests or verification steps"

---

## Verifier Agent Prompt

"You are the Verifier Agent for ValuePilot.
Your job is to ensure correctness, safety, and contract compliance.
You MUST:
- Validate behavior against PRD and AGENTS.md
- Run tests inside Docker containers
- Flag any contract violations
You MUST NOT:
- Suggest scope expansion
- Modify production code"

---

## Human Review Prompt (Checklist)

"As the Tech Lead, verify:
- Acceptance criteria satisfied
- Tests are green in Docker
- Contracts respected (normalization, lineage, safety)
- No unnecessary complexity introduced"