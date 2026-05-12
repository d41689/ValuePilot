# 13F MVP4-11: Manager Type Taxonomy Reconciliation

## Status

**Decision-staging — not yet authorized to implement.** This task log
lays out the vocabulary mismatch and proposes D1–D5 resolutions. The
human owner (or delegated reviewer) must approve the decisions below
before any code changes land. MVP4-11 is a hard prerequisite for
MVP4-03 / MVP4-04; the signal-weighted-score `manager_signal_weight`
table is undefined until the canonical taxonomy is picked.

## Goal / Acceptance Criteria

Reconcile the three currently-inconsistent `manager_type`
vocabularies in the codebase to one canonical taxonomy and bring the
admin enum + behavior-derived profile + plan §7.2 weight keys onto a
single source of truth. Land the plan §7.2 example weight table
(MVP4-01 D5 deferred this to MVP4-11) keyed on the canonical names.

Acceptance criteria (final shape depends on D1–D5 approval):

- `app/models/institutions.MANAGER_TYPES` enum is the canonical
  vocabulary; `derive_manager_signal_profile()` outputs match;
  plan §7.2 weight table keys match.
- A single `resolve_manager_type(manager) -> ManagerTypeResolution`
  helper returns the canonical type AND a source label
  (`admin` / `behavior_fallback`) so scoring callers can attribute
  the classification.
- The plan §7.2 `manager_signal_weight` constants table lands in
  `app/services/oracles_lens/constants.py` (per MVP4-01 D5) keyed
  on the canonical names.
- Alembic migration handles any DB enum rename (see "Data Impact"
  below — currently zero affected rows).
- `app/services/thirteenf_user_api.py`'s `VALUE_MANAGER_TYPES` and
  `CONSENSUS_EXCLUDED_MANAGER_TYPES` are updated to the canonical
  spellings (these are the only MVP2 consumers using the old
  `fundamental_long` literal).
- All 669 existing tests stay green; new tests pin the taxonomy
  resolution semantics.

## Audit: Current Three-Vocabulary Mismatch

| Concept | `MANAGER_TYPES` admin enum | `derive_manager_signal_profile()` behavior | Plan §7.2 weight key |
|---|---|---|---|
| Long-term fundamental | `fundamental_long` | `long_term_fundamental` | `long_term_fundamental` |
| Value-concentrated | — | `value_concentrated` | `value_concentrated` |
| Activist | `activist` | — | `activist` |
| Multi-strategy | `multi_strategy` | — | — |
| Quant | `quant` | — | `quant` |
| Index-like | `index_like` | — | `index_like` |
| High turnover | — | `high_turnover` | `high_turnover` |
| Unknown | `unknown` (default) | `unknown` (default) | `unknown` |

Where the three disagree:

1. **`fundamental_long` (admin) vs `long_term_fundamental`
   (behavior+plan)** — naming variant of the same concept.
2. **`value_concentrated` and `high_turnover`** — behavior+plan
   have them, admin enum does not.
3. **`multi_strategy`** — admin enum has it, plan §7.2 weight
   table doesn't.

### Data Impact

`SELECT manager_type, COUNT(*) FROM institution_managers GROUP BY 1`
on the live DB returns:

```
('unknown', 80)
```

**Every manager is `unknown`.** No rows currently carry
`fundamental_long` / `activist` / `quant` / `multi_strategy` /
`index_like`. The renames below are enum-constraint changes only —
no row-level data migration is required.

### Production Code That References the Old Names

- `app/services/thirteenf_user_api.py:34` —
  `VALUE_MANAGER_TYPES = {"fundamental_long", "activist"}` used in
  the MVP2 consensus aggregation to identify value-investor
  managers.
- `app/services/thirteenf_user_api.py:35` —
  `CONSENSUS_EXCLUDED_MANAGER_TYPES = {"index_like", "quant"}` —
  these two strings stay the same under D1.
- `app/services/oracles_lens/manager_signal.py` —
  `derive_manager_signal_profile()` already emits
  `long_term_fundamental` / `value_concentrated` / `high_turnover` /
  `unknown`.

## PRD / Decision References

- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` D5 SME
  remediation: "MVP4-11 manager_type taxonomy reconciliation must
  complete before MVP4-03 starts. Picks one canonical taxonomy,
  defines admin-set vs behavior-derived precedence, and updates
  `derive_manager_signal_profile` + admin UI to a single
  vocabulary."
- `docs/tasks/2026-05-11_13f-mvp4-decision-gate.md` D5 SME
  re-confirm note: when MVP4-11 opens, include an admin-side
  sub-deliverable exposing which managers' `manager_type=unknown`
  status materially affects `score_confidence` on the latest
  usable quarter — so admins can prioritize type-classification.
- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` §7.2
  weight table (the source of all seven weight keys).
- `docs/tasks/2026-05-11_13f-mvp4-01-score-schema-orm.md`
  Pre-Start Resolutions: D5 deferred the plan §7.2 weight tables
  to MVP4-11 specifically to wait for this reconciliation.

## Decision Record (Proposals)

Each decision is a **proposal**; please confirm or revise before
the implementation tasks open.

### D1. Canonical Taxonomy Naming

**Proposal:** adopt the plan §7.2 / behavior-derived spelling.
Rename `fundamental_long` → `long_term_fundamental` in the admin
enum. Add `value_concentrated` and `high_turnover` to the admin
enum. Keep `multi_strategy`, `activist`, `quant`, `index_like`,
`unknown` unchanged.

Canonical set (8 values):

```
{
  long_term_fundamental,
  value_concentrated,
  activist,
  multi_strategy,
  quant,
  index_like,
  high_turnover,
  unknown,
}
```

Rationale:
- The plan §7.2 weight table is the user-facing scoring contract;
  it is the documented vocabulary.
- `derive_manager_signal_profile()` already emits these names —
  zero changes there.
- Live DB has zero rows using the legacy `fundamental_long` string,
  so the enum rename is purely a constraint change. No row backfill
  needed.
- `multi_strategy` is preserved because the admin team has the
  concept; D3 below handles its weight.

Alternative considered: keep `fundamental_long` and rename the
plan/behavior keys to match. Rejected because the plan is the
documented product surface and behavior code already uses
`long_term_fundamental`; renaming back would touch more files for
no semantic gain.

### D2. Admin-Set vs Behavior-Derived Precedence

**Proposal:** admin always wins. Behavior is the fallback when the
admin enum value is `unknown`.

Concretely:

```python
def resolve_manager_type(manager) -> ManagerTypeResolution:
    if manager.manager_type and manager.manager_type != "unknown":
        return ManagerTypeResolution(
            canonical_type=manager.manager_type,
            source="admin",
        )
    derived = derive_manager_signal_profile(manager)
    return ManagerTypeResolution(
        canonical_type=derived.manager_type,
        source="behavior_fallback",
    )
```

Rationale:
- Admin override is intentional human judgement and should not be
  silently overridden by a heuristic.
- The admin default is `unknown`, which already creates a natural
  fallback trigger — no need to introduce a separate
  `admin_override_active` flag.
- Source attribution (`admin` vs `behavior_fallback`) is captured
  for the score_explanation payload so the user sees how the
  manager weight was derived.

Alternatives considered:
- Behavior always wins → loses admin agency.
- Admin "suggests" + admin confirms → adds a workflow step admin
  doesn't have today.
- Orthogonal storage of both types → adds complexity for no
  immediate consumer.

### D3. `multi_strategy` Weight

**Proposal:** fall back to the `unknown` weight (currently 0.60 in
the plan §7.2 example). Do not define a separate weight for
`multi_strategy` in V1.

Rationale:
- Multi-strategy managers are heterogeneous by definition; a
  single weight would be a guess.
- Admins can still label managers as `multi_strategy` for
  filtering / display purposes; only the scoring weight falls back.
- A future tuning round can introduce a calibrated weight if
  evidence supports it; that fits MVP4 D5's "no pre-launch tuning"
  policy (PO clarification).

Alternative considered: assign a fixed weight (e.g. 0.50 between
`unknown` and `quant`). Rejected because it would commit V1 to a
calibration we have no evidence for.

### D4. Plan §7.2 Weight Table Location and Tunability

**Proposal:** ship the example weights from plan §7.2 in
`app/services/oracles_lens/constants.py` as a typed dict:

```python
MANAGER_SIGNAL_WEIGHTS: dict[str, Decimal] = {
    "long_term_fundamental": Decimal("1.00"),
    "value_concentrated":    Decimal("1.00"),
    "activist":              Decimal("0.80"),
    "unknown":               Decimal("0.60"),
    "quant":                 Decimal("0.40"),
    "high_turnover":         Decimal("0.30"),
    "index_like":            Decimal("0.10"),
    "multi_strategy":        None,  # falls back to "unknown" per D3
}
```

`MVP4-03 signal-weighted score` reads these at compute time. A
future tuning round bumps `SCORE_VERSION` (already defined here)
and ships new weights as a code change — matching MVP4 D5's
"config module, no DB table" decision.

Rationale:
- Co-locates with `SCORE_VERSION`, which is the same kind of
  scoring-calibration knob.
- Decimal type avoids float-precision drift in score components.
- `multi_strategy: None` makes the fallback intent explicit at
  the table level — `resolve_manager_type` / signal-weighted
  service substitutes `unknown`'s weight.

### D5. Admin UI Sub-Deliverable (SME Non-Blocking Note)

**Proposal:** scope MVP4-11 to the **backend** only. Land the
admin-UI "expose managers whose `unknown` status materially affects
`score_confidence`" surface as **MVP4-11b** (a follow-up frontend
task) when MVP4-03 has been merged and there is a real
`score_confidence` field to query.

Rationale:
- MVP4-03 is the consumer that emits the `score_confidence`
  values the admin surface would prioritize on. Building the admin
  UI before MVP4-03 ships would require mocking the data.
- The SME note is explicit that it's non-blocking; deferring
  preserves MVP4-03's start sequence.
- Naming it `MVP4-11b` (not a new MVP4-13) keeps the dependency
  obvious: it's the UI counterpart of the same reconciliation.

Alternative considered: do the UI now. Rejected because there is no
`score_confidence` field on managers yet to drive the UI off.

## Conditional Scope (Subject To D1–D5 Approval)

### Scope In

- Alembic migration renaming `fundamental_long` →
  `long_term_fundamental` in the `manager_type` enum constraint,
  plus adding `value_concentrated` and `high_turnover`. Zero rows
  to migrate (per audit above).
- Update `app/models/institutions.MANAGER_TYPES` to the new
  canonical set.
- Update `app/services/thirteenf_user_api.VALUE_MANAGER_TYPES` to
  `{"long_term_fundamental", "activist"}`.
- New module `app/services/oracles_lens/manager_taxonomy.py`:
  - `MANAGER_TYPES_CANONICAL` (re-export of the model's set for
    discoverability from the scoring side).
  - `ManagerTypeResolution` dataclass
    (`canonical_type`, `source`, `weight`).
  - `resolve_manager_type(manager)` function per D2.
- Update `app/services/oracles_lens/constants.py` with
  `MANAGER_SIGNAL_WEIGHTS` per D4.
- New `tests/unit/test_13f_mvp4_manager_taxonomy.py`.

### Scope Out

- Admin UI surfacing (D5 → MVP4-11b).
- Signal-weighted score computation (MVP4-03).
- Conviction score (MVP4-04).
- Schema column rename / new column (the existing
  `manager_type` column is reused; D1 is a constraint change).
- PRD edits.

### Files Expected To Change

- `backend/alembic/versions/YYYYMMDDHHMMSS-mvp4_11_manager_type_taxonomy.py`
  — new migration.
- `backend/app/models/institutions.py` — `MANAGER_TYPES` set.
- `backend/app/services/thirteenf_user_api.py` —
  `VALUE_MANAGER_TYPES` literal update.
- `backend/app/services/oracles_lens/manager_taxonomy.py` — new.
- `backend/app/services/oracles_lens/constants.py` — add
  `MANAGER_SIGNAL_WEIGHTS`.
- `backend/tests/unit/test_13f_mvp4_manager_taxonomy.py` — new.
- This task file (mark approved + record verification results).

### Test Plan (Provisional)

Tests to write first:
- Canonical set has exactly the 8 names from D1.
- `resolve_manager_type` returns `source='admin'` when the manager
  has an explicit non-unknown enum value.
- `resolve_manager_type` returns `source='behavior_fallback'` when
  the manager's enum is `unknown`.
- `MANAGER_SIGNAL_WEIGHTS` keys exactly match the canonical set
  (defensive — flags drift).
- `MANAGER_SIGNAL_WEIGHTS["multi_strategy"]` is `None` per D3;
  scoring callers (future MVP4-03) substitute `unknown`'s weight.
- Alembic migration applies cleanly from current head and rolls
  back cleanly; the `manager_type` column accepts each new
  canonical value after upgrade and rejects them after downgrade.
- MVP2 consumer continuity: a manager whose `manager_type` is now
  `long_term_fundamental` is included in `VALUE_MANAGER_TYPES`
  filters where the old code expected `fundamental_long`.

Docker verification commands:
- `docker compose exec api alembic upgrade head`
- `docker compose exec api alembic downgrade -1 && alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_manager_taxonomy.py`
- `docker compose exec api pytest -q`

## Approval Checklist

- [ ] D1 canonical taxonomy approved (8-value set; rename
      `fundamental_long`; add `value_concentrated` +
      `high_turnover`; keep `multi_strategy`).
- [ ] D2 admin-wins-with-behavior-fallback precedence approved.
- [ ] D3 `multi_strategy` falls back to `unknown` weight approved.
- [ ] D4 weight table location (`oracles_lens/constants.py`) and
      `Decimal` typing approved.
- [ ] D5 admin UI sub-deliverable filed as MVP4-11b (post-MVP4-03)
      approved.
- [ ] MVP4-11 implementation explicitly approved to start.

## Progress Notes

- 2026-05-11: Created after MVP4-10 conftest savepoint hardening
  landed. SME stamped this as a hard MVP4-03 prereq during the
  MVP4 decision-gate review; this log stages the five product /
  engineering decisions for owner approval before any code
  changes.
- 2026-05-11: Vocabulary audit — admin enum at
  `app/models/institutions.py:14`, behavior-derivation at
  `app/services/oracles_lens/manager_signal.py:34-40`, MVP2 user
  API references at
  `app/services/thirteenf_user_api.py:34-35`. Confirmed live DB
  has zero rows using `fundamental_long`; the rename is a
  constraint change only.

## Verification Results

- Documentation-only decision-staging task; Docker verification not
  required for this stage. Verification commands above will run
  after D1–D5 are approved and implementation lands.
