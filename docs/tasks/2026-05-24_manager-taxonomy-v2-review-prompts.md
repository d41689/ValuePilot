# Manager taxonomy V2 + Dataroma decouple — Three-role review prompts

Three reviewer prompts for the manager-taxonomy-v2 PR. Each is
self-contained — drop the prompt into a fresh chat or hand it to a
human reviewer without needing this conversation's history.

**Branch**: `claude/manager-taxonomy-v2`
**Commits**:
- `2c10fd1` — Manager taxonomy V2: two-layer style + capital_structure
  + metadata
- `ef4c018` — Decouple bootstrap from Dataroma; add admin
  "Sync with Dataroma" diff UI

**Task docs**:
- `docs/tasks/2026-05-24_manager-taxonomy-v2.md` — taxonomy redesign
- `docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md` —
  bootstrap/sync split

**Project guide**: `AGENTS.md` (project-wide contract for every agent)

**Why this PR exists** (read this first): a PO acceptance review of
the V1 manager_type vocabulary found that five Tiger Cubs (Tiger
Global, Lone Pine, Viking, Maverick, Durable Capital) were classified
as `long_term_fundamental` in production, giving their stock-picks the
same Oracle's Lens signal weight (1.00) as Berkshire and Tweedy
Browne. That pollutes the "value consensus" signal with growth /
momentum holdings. The V1 taxonomy also lumps ~50% of the universe
into `long_term_fundamental`, which makes it unusable for filtering
"deep value vs quality compounder vs activist". The V2 redesign
introduces a two-layer label (`style_primary` + `capital_structure`)
plus metadata, with V1 `manager_type` kept and auto-derived from
`style_primary` so existing scoring works unchanged. The second
commit cleans up bootstrap so it no longer hits Dataroma on every
button press — the new "Sync with Dataroma" diff UI separates the
discovery workflow from the seeding workflow.

Roles (priority order):

1. **Value Investor PO (HIGH).** Validates the 82 individual
   classifications and the V2 taxonomy design itself. The other two
   reviews are technical; this one is *product*.
2. **Staff Engineer (MEDIUM).** Schema migration safety, contract
   design, backward compat, the offline-bootstrap-vs-on-demand-sync
   split.
3. **Backend Reviewer (MEDIUM).** Service code structure, test
   coverage adequacy, edge cases in the diff algorithm.

---

## 1. Value Investor PO Review Prompt

You are a senior value investor reviewing a manager-classification
change to ValuePilot's 13F automation track. ValuePilot tracks ~82
US-filing superinvestors and uses their 13F holdings to build
"Oracle's Lens" — a research candidate ranking signal. The
classification of each manager directly drives how much weight that
manager's holdings carry in the consensus signal.

**Read these files in order:**

1. `docs/tasks/2026-05-24_manager-taxonomy-v2.md` — the design
   document. Pay attention to the "Hero outcome" (Tiger Cubs) and the
   acceptance criteria.
2. `backend/app/services/seed_data/confirmed_managers.json` — all
   82 classifications. Every entry has `style_primary`,
   `capital_structure`, and a one-line `classification_rationale`.
3. `backend/app/services/oracles_lens/manager_style.py` — the 9-line
   `STYLE_PRIMARY_TO_LEGACY` map. This decides each style's Oracle's
   Lens weight. Lines 49–60.
4. `backend/app/services/oracles_lens/constants.py` lines 46–60 —
   the legacy weights table (`MANAGER_SIGNAL_WEIGHTS`) for reference.

**Eight key product questions you must answer.**

### Q1 — Is the eight-bucket `style_primary` vocabulary the right cut?

The buckets are: `value_deep`, `value_concentrated`,
`quality_compounder`, `activist`, `growth_long_short`,
`special_situations`, `multi_strategy_macro`, `endowment_passive`
(plus `unknown`).

- Is the split between `value_deep` (Tweedy / Southeastern / Yacktman
  / Kahn / Fairfax / Olstein / First Pacific / Pzena) and
  `value_concentrated` (Baupost / Akre / Greenlight / Pabrai /
  Greenlea / Vulcan / CAS / Aquamarine) meaningful, or is it a
  distinction without a difference?
- Is `quality_compounder` properly distinct from
  `long_term_fundamental` (the V1 catch-all)? The PR puts Lindsell
  Train / Fundsmith / Polen / Cantillon / AKO / Brave Warrior / Akre
  family / Davis / Markel / Cantillon / Wedgewood here. Would you
  rather see compounders fold back into `value_concentrated`?
- Should there be a `garp` (growth at reasonable price) bucket
  between `quality_compounder` and `growth_long_short`? Right now
  GARP-style managers (Jensen, possibly Ariel) get placed in
  `quality_compounder` and `value_deep` respectively.

### Q2 — Are the Tiger Cubs correctly classified?

Tiger Global / Lone Pine / Viking / Maverick / Durable all map to
`style_primary=growth_long_short` → legacy `manager_type=high_turnover`
(weight 0.30). This drops their stock-pick influence in Oracle's
Lens from 1.00 to 0.30.

- Is `growth_long_short` the right *style* label, or should it be
  e.g. `tiger_cub` / `growth_long_only`? (Note: legacy weight is the
  same regardless of the label — this is a vocabulary question.)
- Is dropping them to `high_turnover` the right *weight* outcome, or
  do you actually want them at `multi_strategy` (weight 0.60)?
  Argument for 0.30: their portfolios genuinely turn over fast and
  their long-bias growth has nothing to do with what a value investor
  is looking for. Argument for 0.60: their stock picks (e.g. Viking's
  consumer names) sometimes are genuinely undervalued, just not in a
  Graham sense.
- Should we expose the Tiger Cub lineage as an `ideology_tags` entry
  (e.g. `tiger_cub`) for future filtering? Right now Tiger Global has
  `["tiger_cub", "growth", "tmt"]`.

### Q3 — Spot-check the most-likely-wrong classifications

For each of these, accept / reject / suggest alternative:

- **TCI Fund Management** → `activist`. (V1 had value_concentrated.)
  Chris Hohn runs concentrated activist positions on Visa, Charter,
  Moody's, ABInBev. Is `activist` right, or is he more of a
  "constructive long-term holder"?
- **Berkshire** → `value_concentrated`. (V1 had long_term_fundamental.)
  Top 10 ≈ 80% of the equity book. Capital structure correctly marked
  as `permanent_capital`. Right call?
- **Gates Foundation** → `style_primary=endowment_passive` → legacy
  `index_like` (weight 0.10). Premise: it holds Buffett-donated stock
  and "trades" are gifting timing, not investment views. Should
  Oracle's Lens basically ignore Gates Foundation's holdings? Or do
  you want non-zero weight because the underlying positions came from
  Buffett's selection?
- **Scion (Burry)** → `special_situations`. (V1 had high_turnover.)
  His turnover IS high, but he's also a genuinely contrarian
  macro-driven investor. Is `special_situations` right or should he
  stay at `high_turnover`?
- **Vulcan Value Partners** → `value_concentrated`. (V1 had
  long_term_fundamental.) Their self-description is "concentrated
  value with MoS". Right call?
- **Markel** → `quality_compounder`, `permanent_capital`. Should it
  be `value_concentrated` instead (Tom Gayner does run a more
  concentrated quality book than e.g. Polen)?
- **Pershing Square** → `activist`, `permanent_capital`. Ackman's
  recent style is more "concentrated quality + activist optionality"
  than pure activism. Right?
- **Oaktree** → `multi_strategy_macro`. They're really distressed
  credit — equity sleeve is small. Should we lower their weight
  further (e.g. tag them as `unknown` so they're 0.60)?

### Q4 — `capital_structure` design

The seven buckets are: `permanent_capital` (Berkshire, Markel,
Fairfax, Daily Journal, Icahn, Pershing, Cooperman, Duan Yongping,
Tepper), `locked_lp`, `standard_lp`, `mutual_fund_etf`,
`endowment_foundation`, plus `unknown`.

- Is `permanent_capital` a useful filter for value investors? (My
  argument: yes — managers without LP redemption pressure tend to
  hold longer, signal-add events from them are higher conviction.)
- The seed currently doesn't use `standard_lp` for any of the 82
  managers — everything is `locked_lp` or `permanent_capital` or
  `mutual_fund_etf`. Is that an honest read of reality, or am I
  miscategorizing some?
- Should `capital_structure` also weight Oracle's Lens directly (i.e.
  permanent capital signals get a multiplier)? Right now it only
  affects `style_primary` indirectly via the per-manager classification.

### Q5 — `market_cap_focus` and small-cap value sleuths

Punch Card / Greenlea Lane / Oakcliff / Pabrai are tagged
`market_cap_focus=small` (some `micro`). These small-cap value
managers are arguably the most valuable signal source for a value
investor — large funds can't compete on these names.

- Should there be a separate `market_cap_focus=small` weighting boost
  in Oracle's Lens? (Not in this PR; future question.)
- Are there small-cap managers in the universe I'm missing from this
  bucket?

### Q6 — Does any classification feel "this is just wrong"?

Scan the full 82-row JSON. Flag any classification that, as a value
investor, you'd argue with. A few specific ones I'm uncertain about:

- **Egerton Capital** (Armitage) → `quality_compounder`. Could be
  argued as `growth_long_short` (long-bias UK fund, has had high
  turnover in some periods).
- **Greenlight** (Einhorn) → `value_concentrated`. He's also famously
  short-biased — 13F only surfaces longs, so the signal we get is
  necessarily incomplete. Worth flagging in `ideology_tags`?
- **Cooperman (Omega family office)** → `value_concentrated`,
  `permanent_capital`. He's converted Omega to family office; do you
  agree with permanent_capital here?
- **Ariel (John Rogers)** → `value_deep`, `small`. Ariel does
  small/mid-cap value but their flagship has drifted larger. Right
  bucket?
- **Patient Capital (McLemore)** → `value_concentrated`. Successor
  to Bill Miller's Opportunity Trust. Right or is `growth_long_short`
  more honest (she ran the very tech-heavy MOT)?

### Q7 — Is the "Hero outcome" actually right?

The PR claims the single most important outcome is that Tiger Cubs
drop from weight 1.00 → 0.30. Is that the right pri-one outcome, or
are you more worried about something else (e.g. the
`endowment_passive` → 0.10 demotion of Gates)?

### Q8 — Bootstrap decouple — does this match value-investor workflow?

The second commit splits "Bootstrap manager universe" (now offline,
JSON-driven, deterministic) from "Sync with Dataroma" (on-demand
diff UI on the Managers page; admin chooses which discovered names
to add as candidates).

- Is "admin clicks button, sees diff, decides which to add" the
  right UX gate for discovering new superinvestors?
- The diff shows three buckets: new (in Dataroma, not in us), known
  (in both, matched by dataroma_code), dropped (in us, not in
  Dataroma). The end-to-end smoke test surfaced 3 of our managers'
  dataroma_codes (BAUP / BRIDGEWATER / DAILY) as "dropped" because
  Dataroma changed their codes. Should the UI also detect renames
  (same name, different code) as a separate bucket? Not in this PR.
- Should the "Add as candidates" path also try to auto-classify with
  V2 fields (e.g. via LLM call), or is "candidate with unknown V2
  fields" the right initial state for human review?

**Deliverable.** Write a markdown review report to
`docs/tasks/2026-05-24_manager-taxonomy-v2-review-results.md` with
sections matching Q1–Q8. For each classification you'd change, give
ticker / CIK + current style + proposed style + one-line rationale.

---

## 2. Staff Engineer Review Prompt

You are a staff engineer reviewing a contract-level change to
ValuePilot's 13F automation track. The PR introduces a new
two-layer manager taxonomy (V2) on the `institution_managers` table
and refactors the bootstrap path to be offline + on-demand.

**Read these files in order:**

1. `AGENTS.md` — project-wide contract, especially "Critical
   invariants — never violate".
2. `docs/tasks/2026-05-24_manager-taxonomy-v2.md` and
   `docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md` — both
   task docs.
3. `backend/alembic/versions/20260524120000-manager_taxonomy_v2.py` —
   the migration.
4. `backend/app/models/institutions.py` lines 20–60 (the new V2 enum
   sets) and 104–134 (column definitions).
5. `backend/app/services/oracles_lens/manager_style.py` — the
   `STYLE_PRIMARY_TO_LEGACY` mapping and `derive_legacy_manager_type`.
6. `backend/app/services/edgar_ingestion.py` — both the V2 changes
   in `seed_confirmed_managers` (top) and the bootstrap-decouple
   refactor (`sync_dataroma_managers`, `add_dataroma_candidates`,
   `_fetch_dataroma_managers`, `DataromaSyncDiff`).
7. `backend/app/services/thirteenf_admin_dashboard.py` — job dispatch
   updates (search for `bootstrap_whitelist` and `dataroma_sync`).
8. `backend/app/api/v1/endpoints/thirteenf_admin.py` — the two new
   `/managers/dataroma-sync` endpoints.

**Six contract questions you must answer.**

### C1 — Schema migration

- Are the new columns sized appropriately? (`style_primary`,
  `capital_structure` are `String(40)`; `market_cap_focus` is
  `String(20)`; `historical_turnover` is `String(10)`;
  `position_concentration_top10_pct` is `Numeric(6, 2)`;
  `ideology_tags` is `JSONB`.)
- Are `server_default='unknown'` on the two NOT-NULL columns safe for
  backfilling existing rows? (`institution_managers` already has 80+
  rows on production from prior bootstrap.)
- The two new indexes (`ix_institution_managers_style_primary` and
  `ix_institution_managers_capital_structure`) — are they justified?
  Predicted usage: filter queries in a future Oracle's Lens universe
  selector.
- Downgrade path — does it restore the table to the prior shape
  cleanly?
- Should the migration also include a one-time data backfill that runs
  `seed_confirmed_managers()` to populate V2 fields on existing rows?
  (Currently the migration only adds columns with `server_default`;
  the seed has to be run separately via the admin bootstrap button.)

### C2 — Backward compat for `manager_type`

The V1 `manager_type` column is kept and auto-derived from
`style_primary` via `STYLE_PRIMARY_TO_LEGACY` at write time.

- Is auto-derivation at write time (in `seed_confirmed_managers`) the
  right place, or should it happen at the model layer via an
  `@event.listens_for` hook so anyone writing `style_primary` gets
  `manager_type` consistency for free?
- What happens when admin updates `style_primary` via a future
  endpoint without going through the seed? Right now `manager_type`
  could drift out of sync.
- Is `derive_legacy_manager_type` raising `ValueError` on unknown
  inputs the right contract, or should it return `unknown` as a
  defensive default?

### C3 — Bootstrap / sync separation

The legacy `bootstrap_whitelist` job_type is kept (FE button still
fires it) but its handler now calls `seed_confirmed_managers`. A new
`dataroma_sync` job_type runs the read-only diff.

- Is keeping the old job_type name with new behavior an honest
  contract, or should we have introduced a `seed_confirmed_managers`
  job_type and deprecated `bootstrap_whitelist` properly via the
  job_type vocabulary?
- The `/admin/13f/managers/dataroma-sync` and
  `/admin/13f/managers/dataroma-sync/add` endpoints are synchronous
  (not job-system). Justification in the task doc: 1-3s round trip,
  UX simpler than polling. Is that right, or should they be jobs for
  audit-trail uniformity?
- Concurrency: what if two admins click "Sync with Dataroma" at the
  same time? The synchronous endpoint doesn't have a lock. The job
  system would.

### C4 — The diff algorithm

`sync_dataroma_managers` matches by `dataroma_code` only. No fuzzy
name match.

- This means a manager we have (no dataroma_code) that Dataroma
  newly tracks (with a code) will show up as `new` even though it's
  a duplicate. Is the V1 acceptance of this the right tradeoff, or
  should we do a fallback fuzzy-name match before adding to `new`?
- The `dropped` bucket explicitly excludes managers without a
  `dataroma_code`. The reasoning is correct (Dataroma never knew
  about them) but worth confirming the UX implication: this means
  V2-seeded managers can never appear in `dropped`, only in `new` if
  Dataroma starts tracking them.

### C5 — Test coverage

- `test_13f_manager_taxonomy_v2.py` (23 cases) and
  `test_13f_dataroma_sync.py` (10 cases) are the new test files.
- Are the assertions adequate? In particular: the test
  `test_bootstrap_whitelist_job_type_uses_offline_seed_path` asserts
  that `_fetch_dataroma_managers` is not called by monkeypatching it
  to raise. Is that a strong enough contract test, or should we
  also explicitly check that the FE button still works end-to-end?
- Test isolation: the dev DB had pre-existing committed rows that
  broke an assertion in `test_sync_dataroma_dropped_excludes_rows_
  without_dataroma_code`; I rewrote the assertion to be "my row
  isn't dropped" rather than "no rows are dropped". Is that the
  right scoping?

### C6 — Pre-existing test isolation issue

`docs/BACKLOG.md` documents a pre-existing dev-DB test isolation
issue (`_clear_13f` helpers in `test_13f_user_api` and
`test_13f_admin_dashboard` raise FK violations against committed
rows). I confirmed this reproduces on `main` with all V2 changes
stashed. CI passes because CI starts from an empty volume.

- Is the backlog entry triaged correctly (medium severity, dev-only)?
- Should this PR include a fix (e.g. switch the test DB to a
  separate schema or add a session-scoped wipe fixture), or is the
  current behavior of "just record it for later" acceptable per the
  AGENTS.md "Deferred work" workflow?

**Deliverable.** Write a markdown review report to
`docs/tasks/2026-05-24_manager-taxonomy-v2-review-results.md` with
sections matching C1–C6. Identify any blocking issues, any deferrable
issues (with backlog entry suggestion), and approval status.

---

## 3. Backend Reviewer Prompt

You are a senior backend engineer doing a code-level review.
Focus on the Python implementation quality, test adequacy, and
edge cases.

**Read these files in order:**

1. `backend/app/services/edgar_ingestion.py` — the heart of both
   commits. Read the new docstrings (the file's module-level docstring
   is updated) plus the three new symbols: `DataromaSyncDiff`,
   `sync_dataroma_managers`, `add_dataroma_candidates`. Compare against
   the old `bootstrap_whitelist` that got refactored.
2. `backend/app/services/oracles_lens/manager_style.py` — the entire
   file (62 lines).
3. `backend/app/api/v1/endpoints/thirteenf_admin.py` lines 446–525 —
   the two new endpoints and the `DataromaSyncAddItem` /
   `DataromaSyncAddRequest` Pydantic models.
4. `backend/app/cli/edgar.py` — the modified `bootstrap-whitelist`
   command and the new `sync-dataroma` command.
5. `backend/tests/unit/test_13f_manager_taxonomy_v2.py` and
   `backend/tests/unit/test_13f_dataroma_sync.py` — both new test
   files.

**Seven code-quality questions you must answer.**

### B1 — Lazy import in `seed_confirmed_managers`

```python
from app.services.oracles_lens.manager_style import derive_legacy_manager_type
```

is imported *inside* the function. The comment cites avoiding an
import cycle. Is the cycle real (verify), or is this premature?

### B2 — `derive_legacy_manager_type` error semantics

The function raises `ValueError` on unknown input. Defensive vs
permissive — was the right call made? What happens if a future
admin endpoint passes an in-progress `style_primary` value not yet in
`STYLE_PRIMARY`?

### B3 — `DataromaSyncDiff.to_summary_dict` sample size

```python
def to_summary_dict(self, sample_size: int = 25) -> dict:
```

- Is 25 the right cap? Dataroma's universe is ~80–100 entries; in
  practice all entries fit. But the comment says it's to keep
  JobRun.summary_json size sane. Should it be smaller (e.g. 10) or
  configurable per call-site?
- The endpoint at `/admin/13f/managers/dataroma-sync` calls
  `to_summary_dict()` without arguments. So the FE sees at most 25
  new entries even if there are 50. Is that a UX bug?

### B4 — `add_dataroma_candidates` idempotency window

```python
if existing is not None:
    existing.dataroma_synced_at = now
    existing.last_seen_at = now
    skipped += 1
    continue
```

When an entry is already in our DB, we touch the timestamps but skip
the insert. Is that the right side-effect for the "idempotent" path,
or should idempotent strictly mean "no writes at all"?

### B5 — Error handling in the API endpoint

```python
except RateGuardFetchError as exc:
    raise HTTPException(status_code=503, ...) from exc
```

- Are there other exception types from the Dataroma chain that should
  also be caught and translated to 503? (e.g.
  `httpx.RequestError`, `xml.etree.ElementTree.ParseError`.)
- The `add` endpoint doesn't have any error handling. What if the DB
  write fails halfway? Should we wrap it in a transaction?

### B6 — Test fixtures

`_make_existing` in `test_13f_dataroma_sync.py` uses
`InstitutionManager(... status="active")`. But
`_status_from_legacy_match_status` in the model normally derives this
from `match_status="confirmed"`. Is the explicit `status="active"`
needed, or is it redundant noise?

### B7 — The monkeypatch seam

```python
def _fetch_dataroma_managers() -> list:
    with DataromaClient() as dc:
        html = dc.get_managers()
    return parse_managers(html)
```

This module-level function exists solely so tests can monkeypatch
one symbol instead of the whole chain.

- Is this the cleanest way to inject? Alternative: dependency-inject
  the DataromaClient via a default parameter. Compare ergonomics.
- The function's return type is `list` (not `list[DataromaManager]`).
  Why? Should it be typed?

**Deliverable.** Write a markdown review report to
`docs/tasks/2026-05-24_manager-taxonomy-v2-review-results.md` with
sections matching B1–B7. For each issue, give file + line + severity
(blocker / nit) + suggested fix.

---

## Notes for all three reviewers

- The dev DB has pre-existing committed data that breaks some
  unrelated test files (`test_13f_user_api`, `test_13f_admin_dashboard`)
  via FK violations in `_clear_13f` helpers. This is documented in
  `docs/BACKLOG.md` under "`_clear_13f` test helper raises FK
  violation…". It is **not** caused by this PR (verified by stashing
  all changes and re-running — failures persist). CI is unaffected
  because CI runs against a fresh DB.
- All three reviewers can write to the same file
  (`2026-05-24_manager-taxonomy-v2-review-results.md`) using H2
  section headers like `## Value Investor PO Review`,
  `## Staff Engineer Review`, `## Backend Reviewer Review`. If you
  run reviewers in parallel, each can write to its own
  `*-review-results-{role}.md` file and the PR author can merge.
- The reviewer should run, at minimum:
  `docker compose exec -T api pytest -q tests/unit/test_13f_manager_taxonomy_v2.py tests/unit/test_13f_dataroma_sync.py`
  to confirm the new tests pass on their environment.
- Full canonical CI (per `AGENTS.md`):
  ```
  docker compose up -d --build
  docker compose exec -T api alembic upgrade head
  docker compose exec -T api pytest -q
  docker compose exec -T web sh -lc 'node --test lib/*.test.js'
  docker compose exec -T web npm run lint
  docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
  ```
  Note: `npm run build` clobbers the dev web server. Run
  `docker compose restart web` after to restore the live dev site.
