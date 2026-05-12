# Pre-MVP6-02: Admin 13F Information Architecture Split Plan

## Status

**Authorized to start.** Second of two Pre-MVP6 Stabilization
Gate tickets. Must complete before MVP6 feature work can open.

**Planning / decision-gate ticket — not coding.** Output is a
written split plan that becomes the MVP6 task sequence
backbone. Per PO direction:

> 这个任务先不要直接拆 7 个页面。先写一个 decision gate, 确定
> 怎么拆、先拆哪几个.

## Goal / Acceptance Criteria

Resolve the structural mismatch between PRD §11.1 (which asks
for 7 distinct admin pages) and the current implementation
(one 3300-line `/admin/13f/page.tsx` that embeds every section
as an anchor-linked block). Produce a written plan that
answers the seven questions the PO surfaced, and that lands
as the input to the MVP6 task sequence.

The output of this ticket is a **decision document** — no
production code changes. The decisions captured here drive
each subsequent MVP6 ticket's scope.

Acceptance criteria — the plan must answer all seven of the
following with a recorded decision, not just "TBD":

1. **Is `/admin/13f` retained as the Overview hub?** Yes / no
   + rationale. If yes, the existing route stays as a
   navigation + overview page; if no, propose the
   replacement.
2. **Final route naming for the 7 PRD §11.1 pages.** Concrete
   paths, not just labels. PO's working proposal (open to
   revision):
   ```
   /admin/13f                       — Overview hub
   /admin/13f/managers              — Managers list
   /admin/13f/managers/[id]         — Manager detail
   /admin/13f/sync                  — Daily Sync + no-index calendar
   /admin/13f/filings               — Filings list (+ amendments)
   /admin/13f/holdings              — Holdings Coverage + CUSIP workflow
   /admin/13f/jobs                  — Jobs / workers / EDGAR rate limit
   /admin/13f/readiness             — Readiness levels detail
   ```
3. **Reusable components extracted from the 3300-line
   single-page.** Enumerate which existing UI blocks become
   shared components (Card primitives, Table helpers,
   Dialog patterns, query hooks). Map: section in current
   page → new component name + new file path.
4. **First batch — which 2 pages ship first.** PO's working
   suggestion:
   - Overview hub (MVP6-01)
   - Managers + Manager Detail (MVP6-02)
   Confirm or revise based on engineering risk + admin
   usage patterns.
5. **Read-only vs destructive-action pages.** Tag each of
   the 7 pages: which only display data (Overview,
   Readiness), which expose admin actions (Managers, Sync,
   Filings, Holdings, Jobs). Destructive-action pages need
   the existing confirmation-dialog pattern; read-only ones
   don't.
6. **Empty / loading / error state convention.** Today the
   page mixes Loader2 spinners, "—" placeholders, and
   ad-hoc text. The new pages need ONE convention. Decide:
   - Loading: Loader2 (existing) vs Skeleton component vs
     simple text.
   - Empty: directional text (MVP5-04 pattern) vs an
     `<EmptyState>` shadcn component.
   - Error: toast vs inline error vs Alert component.
   Pick one of each and apply consistently.
7. **MVP6 task sequence + sequencing constraints.** Write
   the MVP6-01..N task list with each task's scope-in
   summary + dependency notes (e.g. MVP6-02 Managers depends
   on MVP6-01's shared layout component). The plan ships
   this sequence as MVP6's execution plan when MVP6 opens.

## Scope In

- A new decision-document task file as the deliverable.
  This file (Pre-MVP6-02) gets the answers filled in to the
  seven sections above.
- Code reading + design diagrams (mental or rendered) as
  needed to support the decisions. No production code
  changes.
- A draft MVP6 execution plan document path:
  `docs/tasks/YYYY-MM-DD_13f-mvp6-execution-plan.md`
  (filed but not opened — opens only after Pre-MVP6-01 also
  completes and PO authorizes MVP6 kickoff).

## Scope Out

- Any production code change (component extraction, route
  scaffolding, file moves). All actual work happens in
  individual MVP6 tickets that this plan defines.
- Backend changes. PRD §11.1 backend APIs are already
  shipped; this is a frontend IA decision.
- Decisions on MVP6 scope beyond the IA split itself —
  e.g. new admin features, manager bulk-import UI, CSV
  uploader. Those become MVP6 candidates only after the
  IA split is stable.
- Watchlist / Oracle's Lens M3 / Phase 4 retirement /
  Track C G1+G9 — all deferred per PO decision.

## PRD / Decision References

- `docs/prd/13f_automation_and_resilience_prd.md` §11
  (Admin Dashboard pages + Oracle's Lens admin metrics +
  Jobs page filter requirements).
- `docs/tasks/2026-05-12_post-mvp4-roadmap.md` Pre-MVP6
  Stabilization Gate.
- 2026-05-12 PO assessment surfacing the 3300-line
  single-page problem: "把 7 个页面塞一页的代价: 滚动深度大、
  信息密度高、空数据状态下整页看起来 'broken'."

## Files Expected To Change

- `docs/tasks/2026-05-12_pre-mvp6-02-admin-ia-split-plan.md`
  (this file — answer the seven questions inline below).
- `docs/tasks/YYYY-MM-DD_13f-mvp6-execution-plan.md` (new,
  drafted but not opened).

## Test Plan

This ticket has no executable tests — it's a planning gate.
Acceptance is: the seven questions have recorded decisions,
the engineer doing MVP6-01 can follow the plan without
re-asking, and the PO has signed off on the proposed sequence.

## Review Pattern

Two reviewer roles:

- **Staff Engineer** — confirm the proposed component
  extraction map is technically realistic; flag any section
  in the current page that doesn't decompose cleanly.
- **Product Owner** — sign off on the route naming, page
  ordering, and read-only vs destructive-action tagging.

## Progress Notes

- 2026-05-12: Task spec filed per PO Pre-MVP6 stabilization
  decision. Engineer is asked to fill in the seven
  decisions below; PO will sign off on the sequence before
  MVP6 opens.

## Decisions (engineer to fill in)

### D1. Is `/admin/13f` retained as the Overview hub?

> Engineer's recommendation + rationale here. PO confirms or
> revises.

### D2. Final route naming for the 7 PRD §11.1 pages

> Engineer's recommendation (probably matching the PO's
> working proposal above; deviations called out explicitly).

### D3. Reusable components extracted from the 3300-line page

> Concrete extraction map.

### D4. First batch — which 2 pages ship first

> Engineer's recommendation.

### D5. Read-only vs destructive-action page tagging

> Tag each of the 7 pages.

### D6. Empty / loading / error state convention

> One pick for each.

### D7. MVP6 task sequence

> MVP6-01..N with scope-in + dependencies.

## Verification Results

- Pending decision-fill-in.
