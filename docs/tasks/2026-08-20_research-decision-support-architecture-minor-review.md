# Research Decision Support Architecture minor review

Date: 2026-08-20

Owner: Product / Engineering

Status: complete

## Goal

Validate the external Architecture review, apply only the feedback that belongs
at the architecture boundary, and repeat adversarial review until a complete
round finds no new valid contract defect.

## Acceptance criteria

- Every external comment has an explicit accept, defer, or reject disposition.
- Accepted architecture changes remain concise and do not redefine PRD, schema,
  source-retention, version-object, or release-readiness contracts.
- The AI/human section describes authority relationships without resembling a
  new workflow enum.
- Source permission loss delegates retained-field granularity to the applicable
  source-specific retention contract.
- Architecture conformance is explicitly distinct from feature readiness and
  product acceptance.
- A fresh ten-boundary adversarial pass finds no new valid issue.
- Local Markdown links resolve and the scoped diff passes `git diff --check`.

## Scope

### In

- `docs/architecture/research-decision-support.md`
- The architecture adversarial-review record
- Documentation-only mechanical verification

### Out

- PRD, schema, API, source-policy, roadmap, or implementation changes
- Defining version-object storage ownership or granularity
- Defining provider-specific retention fields
- Feature-readiness or product-acceptance gates

## Files to change

- `docs/architecture/research-decision-support.md`
- `docs/tasks/2026-08-20_research-decision-support-architecture-review.md`
- this task record

## Test plan

1. Validate local Markdown links in the scoped documents.
2. Search the Architecture for accidental enums, duplicate truths, and delivery
   requirements introduced by the revisions.
3. Repeat the ten-boundary adversarial matrix and record the result.
4. Run `git diff --check` on the scoped files.

## External-review disposition

- Accepted directly: title casing, authority-relationship presentation,
  source-retention delegation, and explicit separation of Architecture
  conformance from feature/product acceptance.
- Accepted as an implementation concern, not an Architecture change: ownership
  and granularity of model, prompt, extraction-policy, and valuation-policy
  version objects. The PRD or implementation spec must define these before a
  persisted provenance feature relies on them.
- Rejected: none. The only scope decision was to avoid expanding Architecture
  with implementation-owned object and storage detail.

## Adversarial review outcome

- Round 6 found and corrected one defect introduced by the first retention
  edit: source policy cannot displace PRD §G.3.
- Round 7 repeated all ten declared boundaries and found no new valid issue.
- Round 8 attacked only the revised ambiguities and found no new valid issue.
- Full findings and dispositions are recorded in
  `2026-08-20_research-decision-support-architecture-review.md`.

## Verification

- All local Markdown links in the three scoped documents resolve.
- No scoped file contains trailing whitespace; the tracked scoped diff passes
  `git diff --check`.
- Architecture title/version and the explicit conformance disclaimer are
  present.
- Architecture remains below the agreed 800-line ceiling at 529 lines.
- No workflow-arrow form remains for the AI/user/publication authority layers.
- The review record contains the external disposition, one revision-induced
  finding and fix, and two consecutive clean adversarial rounds.
- Docker/CI suites were not run because this change affects documentation only
  and no executable contract or implementation changed.
