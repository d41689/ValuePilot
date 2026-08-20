# Research Decision Support Architecture — adversarial review

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

The pass means the compact architecture states the agreed cross-system
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

## Round 5 — external review disposition

Result: **PASS WITH MINOR REVISIONS — four document changes accepted; one
implementation concern kept out of Architecture**

| ID | Feedback | Disposition |
| --- | --- | --- |
| E5-01 | Normalize the title casing. | Accepted as an editorial correction. |
| E5-02 | The AI-to-user arrow still resembles workflow state progression. | Accepted. Replaced the arrow with an authority-boundary table and explicitly excluded workflow, lifecycle, and enum semantics. |
| E5-03 | Standardize ownership and granularity for model, prompt, valuation-policy, and extraction-policy versions. | Valid implementation concern, but not an Architecture change. Its object/storage contract belongs in the PRD or implementation spec before persisted AI/version provenance ships. |
| E5-04 | Make provider-specific post-revocation retention granularity explicit. | Accepted narrowly. Architecture now delegates retained claims, identities, and excerpts to PRD §G.3 plus the applicable source-specific retention contract; it defines no provider fields. |
| E5-05 | Separate Architecture conformance from feature readiness and product acceptance. | Accepted verbatim in §12. |

Version advanced from 1.0 to 1.1 because E5-02, E5-04, and E5-05 clarify
normative boundaries. No schema, API, enum, source permission, or release gate
was added.

## Round 6 — revision-induced authority collision

Result: **FAIL — one valid issue found and fixed**

| ID | Severity | Finding | Resolution |
| --- | --- | --- | --- |
| R6-01 | medium | The first retention edit said the source-specific contract “alone” determined retained fields, which could exclude PRD §G.3 and its privacy/account-erasure rules. | Replaced “alone” with an explicit joint delegation to PRD §G.3 and the applicable source-specific retention contract. |

## Round 7 — fresh ten-boundary attack

Result: **PASS — no new valid contract finding**

| Boundary | Adversarial implementation attempted | Why it is rejected |
| --- | --- | --- |
| Authority | Treat Architecture 1.1 as permission to define version or retention fields. | §§2.1–2.3 keep schema in the PRD and provider retention in the source contract. |
| Ownership | Reuse one accepted thesis or projection across users sharing a stock. | §§3 and 10 require user ownership and server-side visibility independently of stock identity. |
| AI/human | Persist the three authority labels as a lifecycle enum or auto-advance them. | §4.1 calls them vocabulary, not states; §4.2 requires explicit authenticated acceptance and canonical publication. |
| Financial truth | Query revision snapshots or AI numbers as a second fact store. | §5 permits snapshots only as evidence and reserves queryable truth to `metric_facts`. |
| Valuation truth | Publish a saved/AI/system value outside the canonical service. | §§4.2 and 6 preserve the PRD §G.4 atomic writer and typed unavailable behavior. |
| Point in time | Recompute history with today's model/policy or silently invent missing timestamps. | §7 requires knowledge-time-eligible versions and typed unknown time without defining their storage. |
| Orthogonal states | Implement the authority labels, decision, zone, and option eligibility as one state machine. | §§4.1 and 8 separately prohibit both collapses. |
| Trading boundary | Interpret option analysis or a published value as authorization to submit an order. | §9 prohibits every trading rail and keeps option analysis optional and provider-gated. |
| Privacy/visibility | Retain or show a revoked proprietary snippet because it appears in a historical revision. | §10.2 grants research history no independent retention right and delegates allowed fields to the governing contracts. |
| Origins/integration | Route every idea through Oracle's Lens or overwrite a prior origin. | §11 defines parallel entry, idempotent create/open, and append-only validated origins. |

## Round 8 — ambiguity and regression repeat

Result: **PASS — no new valid contract finding**

The repeat targeted the five revised areas specifically. The authority table
cannot be read as a persistence contract; accepted revisions still do not
create a second valuation writer; retention language neither grants content
retention nor displaces PRD §G.3; version-object granularity remains visibly
outside Architecture; and Architecture conformance cannot be used as a release
or product-acceptance gate. Link, terminology, and whitespace checks found no
regression.

## Final sign-off

**Granted.** No valid authority, ownership, AI-promotion, canonical-truth,
point-in-time, state, trading-boundary, privacy, or integration defect remains
in the architecture's declared scope. This sign-off is for the documentation
contract, not an assertion that every described implementation exists.
