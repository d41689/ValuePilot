# Research Decision Support architecture — adversarial review

Date: 2026-08-20

Target: `docs/architecture/research-decision-support.md`

Review scope: the ten decisions declared in architecture §1

Status: signed off

## Method

Each round attempted to make an implementation produce one of these failures:

1. choose the wrong authority or create a duplicate truth;
2. expose or merge two users' research;
3. promote AI text without an explicit user action;
4. bypass canonical financial or valuation publication;
5. leak future knowledge into a historical decision;
6. collapse lifecycle, decision, valuation, portfolio, risk, or option states;
7. infer permission from technical source access;
8. turn option analysis into a trade or mandatory investment stage;
9. lose or overwrite discovery provenance;
10. silently add schema/enums not authorized by the PRD.

A finding passes only after the architecture is changed or the alleged issue is
shown inconsistent with an existing authoritative contract. Adding detail that
belongs in the PRD is not an acceptable architecture-only fix.

## Round 1 — authority and contract collision

Result: **FAIL — six valid findings found and fixed**

| ID | Severity | Finding | Resolution |
| --- | --- | --- | --- |
| R1-01 | high | The new boundary would be invisible to future agents if it existed only as an unreferenced file. | Added a narrow discovery instruction to `AGENTS.md`; the architecture remains subordinate to PRD/mapping authorities. |
| R1-02 | high | “Provider observations whose terms permit product use” could be read as permission for cross-user display when terms authorize only acquisition/retention. | Visibility now requires explicit authorization for the audience; acquisition and cross-user display are separate decisions. |
| R1-03 | high | Requiring an accepted revision to record a proposal/input reference silently invented fields absent from PRD §G.2. | Proposal/input references are required only after PRD-authorized storage; existing acceptance still records actor, expected head, time, and revision. |
| R1-04 | medium | Universal “links the superseded version” language implied every source already had a physical supersession FK. | The architecture now requires preserved authority/supersession semantics while deferring physical fields to the source PRD/schema. |
| R1-05 | high | The discovery diagram implied a distinct Value Line case-origin enum, but PRD §G.2 does not authorize one. | Value Line attaches as evidence or enters through an existing supported origin; a new origin type explicitly requires a PRD change. |
| R1-06 | medium | “Orthogonal state” could be misread as requiring one table per axis, while “one cross-axis transition” ignored the PRD lifecycle/decision matrix. | Clarified semantic rather than physical orthogonality, preserved the PRD matrix, and limited the statement to derived automatic effects. |

Regression check: every Round 1 change still defers metric, schema, API, source,
and sequencing detail to its existing authority.

## Round 2 — AI provenance and option activation

Result: **FAIL — two valid findings found and fixed**

| ID | Severity | Finding | Resolution |
| --- | --- | --- | --- |
| R2-01 | high | An ephemeral AI proposal could be accepted into a user revision without enough persisted provenance to distinguish AI-proposed from user-authored content. | In-product AI acceptance is blocked until the PRD defines proposal provenance; unrelated external copy/paste is explicitly outside reliable classification. |
| R2-02 | high | Describing option quote-bound analysis could be treated as implicit permission to integrate any convenient option-chain provider. | Automated option analysis is configuration-blocked until the source authority records provider permission, retention, provenance, freshness, and automation limits. |

## Round 3 — repeated ten-boundary attack

Result: **PASS — no new valid contract finding**

| Boundary | Evidence checked | Result |
| --- | --- | --- |
| Authority | Mapping semantics, PRD behavior, locked data rules, source policy, 13F policy, roadmap, Vision/examples | One bounded owner per concern; no override |
| Ownership | Shared identity, permitted observations, user-scoped documents, private cases/revisions/valuation | No platform thesis or cross-user merge |
| AI/human | Proposal, explicit acceptance, revision concurrency, V1 atomic value publication | No automatic promotion path |
| Financial truth | `metric_facts`, immutable extractions, evidence snapshots, derived calculations | No second fact store |
| Valuation truth | User value vs system reference, one service, newest-null behavior, alert pause | No second current-value writer |
| Point in time | Time meanings, unknown time, knowledge-as-of, source correction | No later-data rewrite |
| Orthogonal states | Lifecycle, decision, zone, portfolio, risk/action, option eligibility | No combined lifecycle enum |
| Trading boundary | Optional option branch, no broker/order/margin/tax authority, provider gate | Analysis only |
| Privacy/visibility | Session ownership, admin boundary, private artifacts, untrusted content, AI access | No ID- or stock-based permission shortcut |
| Origins/integration | Parallel discovery, idempotent create/open, append-only origins, source interpretation | No forced Oracle/Watchlist funnel |

## Pass interpretation

The pass means the 520-line architecture states the agreed cross-system
boundaries without redefining the underlying metric, storage, source, scoring,
or roadmap contracts. It does not certify an implementation and does not make
the old 7,056-line document normative.

## Round 4 — post-extraction conformance repeat

Result: **PASS — no new valid finding**

The old source was replaced in the active tree only after the contract pass.
The frozen content remains recoverable from commit `626f797`. The final repeat
verified:

- the architecture's Vision and case-study targets now exist;
- the Vision declares itself non-normative and lists the contracts it cannot
  define;
- normative roadmap, state-machine, data-model, MVP, and acceptance material is
  absent from the Vision;
- EXLS figures and hypotheses are isolated in a clearly illustrative,
  non-authoritative case study;
- the Vision's AI, valuation, ownership, source, and option language conforms to
  the architecture boundary;
- all ten Round 3 boundary results remain unchanged.

## Final sign-off

**Granted.** No valid authority, ownership, AI-promotion, canonical-truth,
point-in-time, state, trading-boundary, privacy, or integration defect remains
in the architecture's declared scope. This sign-off is for the documentation
contract, not an assertion that every described implementation exists.
