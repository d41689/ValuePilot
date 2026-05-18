# 13F MVP4-11: Manager Type Taxonomy Reconciliation

## Status

**Approved — authorized to implement (2026-05-11).** D1–D5 all
accepted by Product Owner; refinements applied below. Subsequent
audit found no DB-level CHECK constraint on
`institution_managers.manager_type` — enforcement is purely the
SQLAlchemy `@validates` validator — so the scope is further reduced:
no alembic migration is required, only Python-level updates.

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

**Framing rule:** *Canonical `manager_type` vocabulary follows
Oracle's Lens scoring vocabulary, not legacy admin enum names.*
The admin enum was an early-MVP1 construct that predated the
Oracle's Lens scoring contract; the scoring contract is what users
see and what V1 is judged against, so the scoring vocabulary wins
the naming tie.

Rationale:
- The plan §7.2 weight table is the user-facing scoring contract;
  it is the documented vocabulary.
- `derive_manager_signal_profile()` already emits these names —
  zero changes there.
- Live DB has zero rows using the legacy `fundamental_long` string,
  so the enum rename is purely a constraint change. No row backfill
  needed.
- Subsequent audit confirmed no DB-level CHECK constraint on
  `institution_managers.manager_type`; enforcement is purely the
  SQLAlchemy `@validates` validator. No alembic migration required.
- `multi_strategy` is preserved because the admin team has the
  concept; D3 below handles its weight.

Alternative considered: keep `fundamental_long` and rename the
plan/behavior keys to match. Rejected because the plan is the
documented product surface and behavior code already uses
`long_term_fundamental`; renaming back would touch more files for
no semantic gain.

### D2. Admin-Set vs Behavior-Derived Precedence

**Proposal:** admin always wins. Behavior is the fallback when the
admin enum value is `unknown`. The three-way source label
(`admin` / `behavior` / `fallback_unknown`) captures the case where
both admin and behavior fail to determine a type.

Concretely:

```python
def resolve_manager_type(manager) -> ManagerTypeResolution:
    if manager.manager_type and manager.manager_type != "unknown":
        return ManagerTypeResolution(
            canonical_type=manager.manager_type,
            source="admin",
        )
    derived = derive_manager_signal_profile(manager)
    if derived is not None and derived.manager_type != "unknown":
        return ManagerTypeResolution(
            canonical_type=derived.manager_type,
            source="behavior",
        )
    return ManagerTypeResolution(
        canonical_type="unknown",
        source="fallback_unknown",
    )
```

Rationale:
- Admin override is intentional human judgement and should not be
  silently overridden by a heuristic.
- The admin default is `unknown`, which already creates a natural
  fallback trigger — no need to introduce a separate
  `admin_override_active` flag.
- Three source labels make the
  "is this score's confidence low because we have no admin label,
  or because behavior couldn't classify?" question unambiguous in
  the score_explanation payload.

Alternatives considered:
- Behavior always wins → loses admin agency.
- Admin "suggests" + admin confirms → adds a workflow step admin
  doesn't have today.
- Orthogonal storage of both types → adds complexity for no
  immediate consumer.

### D3. `multi_strategy` Weight (V1 Conservative Fallback)

**Proposal:** V1 ships `multi_strategy` with the same weight as
`unknown` (`Decimal("0.60")`). This is a **conservative V1 fallback,
not an independent calibration**. The label remains in the admin
enum for filtering / display; the weight is explicitly tagged as
re-tunable.

Rationale:
- Multi-strategy is not a single investment style; it can include
  fundamental long, event-driven, quant, credit, arbitrage, macro,
  and hedge overlays simultaneously. The label by itself does not
  imply a consistent 13F long-equity signal quality.
- Assigning a precise number like `0.50` would suggest a product
  judgement ("multi-strategy is more credible than quant but less
  than unknown") we have no data basis for.
- A V2 tuning round can revisit using holding-duration,
  concentration, turnover, and top-10 position persistence
  evidence — not the label.

The weight table comment must make this V1-only intent explicit so
a future engineer doesn't mistake the value for a calibrated
constant.

Alternative considered: define a fixed weight (e.g. 0.50). Rejected
because it would commit V1 to a calibration we have no evidence for
and would mislead future tuners about how the value was chosen.

### D4. Plan §7.2 Weight Table Location and Tunability

**Proposal:** ship the example weights from plan §7.2 in
`app/services/oracles_lens/constants.py` as a typed dict.
`multi_strategy` carries `Decimal("0.60")` **explicitly** (not
`None`) per D3, with a comment marking it as a V1 fallback rather
than an independent calibration:

```python
MANAGER_SIGNAL_WEIGHTS: dict[str, Decimal] = {
    "long_term_fundamental": Decimal("1.00"),
    "value_concentrated":    Decimal("1.00"),
    "activist":              Decimal("0.80"),
    "unknown":               Decimal("0.60"),
    # V1 conservative fallback: multi_strategy does not imply a
    # consistent long-equity signal quality. Re-tune in V2 from
    # behavior evidence (holding duration / concentration /
    # turnover), not from the label.
    "multi_strategy":        Decimal("0.60"),
    "quant":                 Decimal("0.40"),
    "high_turnover":         Decimal("0.30"),
    "index_like":            Decimal("0.10"),
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
- Explicit `Decimal("0.60")` for `multi_strategy` (vs `None` with
  runtime substitution) keeps the scoring service simple: it just
  looks up the key. The V1-fallback intent lives in the comment +
  tests; if a future engineer changes the value they must update
  both.

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

## Product Owner Decisions (2026-05-11)

### D1 Canonical Taxonomy

Approved. Use Oracle's Lens plan / behavior-derived spelling as the
canonical `manager_type` vocabulary:

- `long_term_fundamental`
- `value_concentrated`
- `activist`
- `quant`
- `high_turnover`
- `index_like`
- `multi_strategy`
- `unknown`

Legacy `fundamental_long` is replaced by `long_term_fundamental`.
Live DB audit shows all 80 managers are currently `unknown`, so this
is a constraint / vocabulary migration only with no row migration
required. Post-approval audit further confirmed no DB CHECK
constraint on `manager_type` — no alembic migration needed at all.

### D2 Admin vs Behavior Precedence

Approved. Admin-set `manager_type` wins when it is not `unknown`. If
the admin value is `unknown`, fall back to the behavior-derived
profile. If neither yields a non-`unknown` type, return `unknown`
with `source='fallback_unknown'`.

The effective type's source must be explainable as
`admin`, `behavior`, or `fallback_unknown` and must be carried in
the `ManagerTypeResolution` payload so future
`score_explanation` consumers can attribute the weighting.

### D3 Multi-Strategy Weight (V1 Conservative Fallback)

Approved with explicit V1-only caveat. In V1, `multi_strategy`
receives the same weight as `unknown` (`Decimal("0.60")`). This is
a **conservative fallback, not an independent calibration**.
Multi-strategy does not imply a consistent 13F long-equity signal
quality.

The weight value is re-tunable in V2 using holding-duration,
portfolio concentration, turnover proxy, and top-10 position
persistence evidence — not the label itself.

### D4 Weight Constants Location

Approved. Store the manager signal weights in
`app/services/oracles_lens/constants.py` as typed Python constants
using `Decimal`. Co-locate with `SCORE_VERSION`. The
`multi_strategy` entry is written explicitly (not `None`) with a
comment tagging it as a V1 fallback, and tests cover all 8
canonical manager types so a future engineer adding a 9th type
must update both places.

### D5 Admin UI Sub-Deliverable

Approved. Defer the admin-UI prioritization surface (expose which
`manager_type=unknown` managers materially affect `score_confidence`
on the latest usable quarter) to **MVP4-11b**, post-MVP4-03.

MVP4-11b trigger conditions:

- MVP4-03 signal-weighted-score service has landed.
- Latest usable quarter has score outputs.
- `score_confidence` / `unknown_manager_type_count` /
  `unknown_manager_type_heavy` are available.

MVP4-11 scope is backend taxonomy reconciliation only.

## Conditional Scope (Subject To D1–D5 Approval)

### Scope In

- Update `app/models/institutions.MANAGER_TYPES` to the canonical
  8-value set (D1).
- Update `app/services/thirteenf_user_api.VALUE_MANAGER_TYPES` to
  `{"long_term_fundamental", "activist"}` (the only file still
  carrying the legacy `fundamental_long` literal).
- New module `app/services/oracles_lens/manager_taxonomy.py`:
  - `ManagerTypeResolution` dataclass
    (`canonical_type`, `source`, `weight`).
  - `resolve_manager_type(manager)` function implementing D2's
    three-way precedence.
- Update `app/services/oracles_lens/constants.py` with
  `MANAGER_SIGNAL_WEIGHTS` per D4 (8 keys, all `Decimal`).
- New `tests/unit/test_13f_mvp4_manager_taxonomy.py`.

**No alembic migration.** Post-approval audit confirmed
`institution_managers.manager_type` has no DB-level CHECK
constraint; enforcement is purely the SQLAlchemy `@validates`
validator on the Python set. Changing the set is sufficient.

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

Docker verification commands (no migration; alembic round-trip
removed from the list):
- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_manager_taxonomy.py`
- `docker compose exec api pytest -q`

## Approval Checklist

- [x] D1 canonical taxonomy approved (8-value set; rename
      `fundamental_long`; add `value_concentrated` +
      `high_turnover`; keep `multi_strategy`).
- [x] D2 admin-wins precedence with three-way source
      (`admin` / `behavior` / `fallback_unknown`) approved.
- [x] D3 `multi_strategy` weight is a V1 conservative fallback to
      `unknown=0.60`, not an independent calibration. Re-tunable
      in V2 from behavior evidence.
- [x] D4 weight table location (`oracles_lens/constants.py`) and
      `Decimal` typing approved; `multi_strategy` written
      explicitly with V1-fallback comment.
- [x] D5 admin UI sub-deliverable filed as MVP4-11b (post-MVP4-03)
      approved.
- [x] MVP4-11 implementation explicitly approved to start.

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
- 2026-05-11: Product Owner approved D1–D5 with refinements:
  framing rule added to D1 (canonical follows Oracle's Lens
  vocabulary, not legacy admin); D2 expanded to three source
  labels (`admin` / `behavior` / `fallback_unknown`) for
  unambiguous score-explanation attribution; D3 reworded as
  V1 conservative fallback (not an independent calibration); D4
  weight table writes `multi_strategy: Decimal("0.60")`
  explicitly with V1-fallback comment instead of `None`; D5
  defers admin-UI surface to MVP4-11b post-MVP4-03. Implementation
  authorized.
- 2026-05-11: Post-approval audit — no DB-level CHECK constraint
  on `institution_managers.manager_type`. Scope reduced: no
  alembic migration needed, only Python-side updates +
  `@validates` set update.
- 2026-05-11: Implemented per PO decisions:
  - `MANAGER_TYPES` updated to the 8-value canonical set; legacy
    `fundamental_long` removed.
  - `VALUE_MANAGER_TYPES` updated to use `long_term_fundamental`.
  - New `app/services/oracles_lens/manager_taxonomy.py` with
    `ManagerTypeResolution` dataclass (carrying `canonical_type`,
    `source`, `weight`) and `resolve_manager_type(manager, *,
    derived_profile=None)`. Three source labels exposed as
    module-level constants (`SOURCE_ADMIN`, `SOURCE_BEHAVIOR`,
    `SOURCE_FALLBACK_UNKNOWN`) so callers import canonical strings.
  - `manager_taxonomy.resolve_manager_type` accepts a precomputed
    `DerivedManagerSignalProfile` rather than computing one itself
    — separates concerns and lets the caller cache the profile
    across multiple resolve calls in one scoring batch.
  - `MANAGER_SIGNAL_WEIGHTS` added to
    `app/services/oracles_lens/constants.py` per D4 (Decimal
    type, all 8 canonical keys present, `multi_strategy` written
    explicitly at 0.60 with V1-fallback comment).
- 2026-05-11: Found two legacy test files still carrying
  `fundamental_long` literals
  (`tests/unit/test_13f_user_api.py`,
  `tests/unit/test_13f_manager_admin_backend.py`). Renamed via
  global sed; verified no behavior change beyond the literal.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_13f_mvp4_manager_taxonomy.py` -> 12 passed.
- `docker compose exec api pytest -q` -> **681 passed** (was 669 pre-MVP4-11; +12), **0 warnings** (carryover from MVP4-10).
