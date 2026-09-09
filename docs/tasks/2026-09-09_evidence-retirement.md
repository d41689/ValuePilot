# Issue 137 — minimal evidence retirement

## Goal

Replace ordinary Value Line document deletion with archival that
preserves retained bytes, pages, immutable extractions, facts, and research
lineage. Archived documents leave current report/fact-derived projections but
remain readable to their owning user while source authorization remains
available. If authorization is lost, document/evidence reads return the typed
`source_unavailable` state without copying proprietary content into research
history.

This advances ValuePilot's disconfirm-before-deciding and thesis-monitoring jobs:
decision history keeps durable source identity while current analysis cannot
silently use retired or unauthorized evidence. Success is observable when archive,
current reconciliation, authorized history, unavailable-source, and tenant tests
pass.

## Acceptance criteria

- `DELETE /api/v1/documents/{id}` performs ordinary archive, preserving the
  document row, stored file key/bytes, pages, extractions, facts, and research
  evidence references.
- Archive demotes only current parsed facts sourced by that document, then uses
  the existing calculated-fact refresh path; it never promotes an older fact.
- Current document lists, active Value Line reports, and derived projections do
  not treat archived documents as current.
- The owning user can read/download an archived document and its retained
  extraction history while current source authorization permits it.
- A retained document marked unavailable makes document/evidence/history reads
  report typed `source_unavailable`; research revisions retain their minimal
  recorded claim/source metadata and do not copy proprietary excerpts.
- A minimal authenticated owner mutation can mark retained source content
  unavailable. It is one-way in this scope; no permission-management or restore
  workflow is introduced.
- Existing non-disclosing ownership checks remain intact.
- No retained storage is deleted.

## Scope

### In

- Minimal document lifecycle fields and one fresh forward migration, if required.
- Document archive service/API response, current-source visibility, document
  cursor/list membership, direct historical document reads, research evidence
  availability, and canonical calculated projection reconciliation.
- Narrow PRD/source-policy wording needed to make ordinary archive versus source
  unavailability explicit.

### Out

- Account deletion/erasure implementation and the R26 remaining-writer inventory.
- File purge, retention-policy administration, permission-management UI or actor
  framework, archive/source restoration, new provider integrations, and SEC
  lifecycle changes.
- Any migration or code copied/cherry-picked from frozen PR #128.

## Explicit deferral

On 2026-09-09 the user narrowed issue #137 for this personal application:
account deletion/erasure and the broad R26 writer inventory remain future privacy
work and are **not completed by this delivery**. Existing privacy-erasure guards
and endpoints remain in place and are not weakened or removed.

## Authorities

- GitHub issue #137, narrowed by the user's 2026-09-09 instruction.
- `docs/architecture/research-decision-support.md` §§5, 7, 10.2.
- `docs/architecture/coverage-source-policy.md`.
- `docs/prd/value-pilot-prd-v0.1.md` §§G.2–G.4 and H.10.
- `docs/architecture/data-layer.md` and
  `docs/architecture/metric-facts-is-current.md`.

## Files expected to change

- `backend/app/models/artifacts.py`
- one fresh `backend/alembic/versions/*-evidence-retirement.py`
- `backend/app/services/document_dedupe_service.py`
- `backend/app/services/value_line_source_visibility.py`
- `backend/app/services/active_report_resolver.py` only if the shared predicate
  does not fully cover current-report exclusion
- `backend/app/services/document_cursor.py`
- `backend/app/services/research_cases.py`
- `backend/app/api/v1/endpoints/documents.py`
- focused backend tests for the services/endpoints above
- `docs/BACKLOG.md`, this task record, and narrowly affected authority docs

The list may shrink after red tests identify the smallest shared boundary. Any
expansion requires recording the reason here first.

## Test plan

Test first with focused in-container pytest targets, then run the exact closing
gate commands:

1. `docker compose up -d --build`
2. `docker compose exec -T api alembic upgrade head`
3. `docker compose exec -T api pytest -q`
4. `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
5. `docker compose exec -T web npm run lint`
6. `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`

## Decisions and sign-off trail

- 2026-09-09: account erasure and the broad writer inventory explicitly deferred;
  preserve existing guards and do not claim that privacy work complete.
- 2026-09-09: choose two orthogonal document fields: retirement controls current
  projection membership, while source availability controls whether retained
  historical content may be read. This avoids treating ordinary archive as loss
  of permission.
- 2026-09-09: no physical deletion or retained-file movement in this delivery.
- 2026-09-09: archive preserves history but adds no restoration promise or API;
  source-unavailable marking is an explicit authenticated owner operation rather
  than a test-only database state.
- 2026-09-09: red checkpoint produced three expected failures (missing lifecycle
  fields, delete still physically removed the document, and archived history was
  unreadable). The first focused green checkpoint passed 102 document, cursor,
  research-case, dedupe, and reparse tests.
- 2026-09-09: adversarial review of `f69e6664` found four direct lifecycle
  consumers. Extraction reads/corrections, coverage readiness, actual-conflict
  selection, and the archive toast now share the retirement contract; four
  focused regressions pass.
- 2026-09-09: follow-up review found direct revision-history serialization and
  source reconciliation did not apply current source withdrawal. Both now use
  typed access/exclusion overlays without changing the stored historical claim.
- 2026-09-09: the first complete backend run exposed an isolated-migration HEAD
  fixture that predated the new document columns and a fixed-clock inbox test
  that evaluated before the database-known method review. The compatibility and
  point-in-time fixtures were corrected without changing production authority.
- 2026-09-09: a later independent CI run found one additional historical-schema
  fixture invoking the current reparse ORM. Its historical revision-180
  assertion remains in place; the isolated schema advances to application head
  only before the current service call. The final canonical gate passed: 2,734
  backend tests and 233 frontend tests, plus frontend lint and production build.

## Extraction evidence checkpoint

- Issue #134 → PR #140; issue #138 → PR #141; issue #135 → PR #142;
  issue #136 → PR #143; issue #133 → PR #144; issue #137 → PR #145.
- The SEC foundation and bounded publication work are represented by PRs #127
  and #132. The frozen PR #128 supplied requirements and test ideas only; no
  code or migrations were copied or cherry-picked from it.
- This delivery resolves the active document/evidence archival slice. Account
  erasure and the R26 remaining-writer inventory are explicitly deferred, and
  the locked 24-case/gold-set acceptance remains outstanding.
- Final cross-delivery extraction audit, deletion of the local/remote
  `codex/financial-truth-minimal-loop` branch, and global Terra review remain
  pending for the root release step after merge; closed PR #128 is permanently
  retained. None of those release steps is claimed complete here.
