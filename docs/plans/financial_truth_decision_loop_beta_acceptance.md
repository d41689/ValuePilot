# Financial Truth & Decision Loop Beta — acceptance protocol

Status: FT-00 locked required delivery gate; subordinate to the authoritative
PRD, architecture boundaries, mapping spec, and source policy

Version: 0.2

Last updated: 2026-08-27

## 1. Purpose and authority

This document makes the beta's delivery tests repeatable. It does not define
metric semantics, schemas, APIs, source permissions, retention rights, or
investment formulas. Those remain owned by:

- `docs/metric_facts_mapping_spec.yml` for metric semantics;
- `docs/prd/value-pilot-prd-v0.1.md` for behavior, storage, and APIs;
- `docs/architecture/coverage-source-policy.md` for acquisition, retention,
  automation, and visibility;
- `docs/architecture/research-decision-support.md` for cross-system boundaries;
- `docs/plans/research_decision_loop_product_roadmap.md` for sequencing.

If an acceptance test requires a behavior those authorities do not yet define,
the owning authority must be approved first. A passing test cannot create a new
contract by implication.

## 2. Versioned gold-set manifest

FT-00 locked and approved
`docs/acceptance/financial_truth_beta_gold_set.yml` on 2026-08-27 before any
ValuePilot SEC-financial parser result was observed. The manifest is fixed for
this beta evaluation cycle; failures cannot be removed or reclassified merely
to make the gate pass. A deterministic validator is exercised by the canonical
backend suite.

The manifest contains exactly 24 distinct economic issuers, each represented by
one primary listing case. Alternate share classes or ADR relationships are tags
and test fixtures, not additional issuers. Each case has stable test identity,
CIK when applicable, listing/share-class identity, reporting
currency, fiscal-year end, filing regime, primary stratum, cross-cutting tags,
expected available-history start, and the reason it represents a required edge.

Primary strata are mutually exclusive and must total 24:

| Primary stratum | Required cases |
| --- | ---: |
| Ordinary US non-financial operating businesses | 6 |
| Banks or other regulated financial institutions | 3 |
| Insurers | 3 |
| REITs | 3 |
| High-SBC or materially acquisitive businesses | 3 |
| Cyclical or commodity businesses | 3 |
| Foreign issuers using 20-F/6-K or another approved regime | 3 |

Across those cases, the manifest must include at least three non-calendar fiscal
years, two 52/53-week reporters, three ADR/share-class/corporate-action cases,
two filing amendments or restatements, and two non-USD reporting currencies.
One issuer may satisfy multiple cross-cutting tags but only one primary stratum.

For each case, the expected history denominator is every fiscal year available
from the approved primary filing source, capped at the ten most recent completed
fiscal years at the locked evaluation cutoff. A recently listed issuer does not
receive invented pre-listing history. Every unavailable year remains in the
manifest denominator with a typed expected/unexpected coverage disposition.

## 3. Repeatable evidence and interaction test

An **interaction** is one user activation—pointer click/tap or keyboard
activation—that changes route or reveals a previously hidden panel. Scrolling,
hovering, passive loading, and reading do not count. Authentication and opening
the initial case URL are setup, not evidence interactions.

For each gold-set decision conclusion sampled by the test, an authorized user
must reach both its calculation/mapping explanation and its original retained
source artifact in no more than two interactions from the visible conclusion.
If policy no longer permits source content, the second target is the typed
`source_unavailable` state plus only the identity/claim fields the PRD and source
policy permit. The test must include authorized, permission-revoked, missing,
conflicting, superseded, and privacy-redacted evidence.

An automated traceability audit covers every displayed fundamental fact and
derived financial conclusion on the locked gold-set routes/fixtures. The manual
two-interaction sample contains every required decision-metric category and at
least 30 facts across at least 10 gold-set issuers. Both layers require 100%
correct source identity, period, knowledge date, unit/currency, fact nature, and
mapping or calculation version; any missing required field, cross-user
disclosure, or silent substitution fails the gate.

## 4. Moderated usability protocol

The scored beta usability run includes exactly five participants who personally
perform long-term fundamental equity research. No participant may have authored
the tested implementation, and no more than one may be a ValuePilot contributor.
Participant eligibility and conflicts are recorded without putting private
research content in the report.

Each participant receives the same locked case fixtures and must complete five
tasks without database-key knowledge or moderator instruction about navigation:

1. identify whether the company is inside their circle of competence and state
   the unresolved question that most limits confidence;
2. explain one material ten-year business-quality trend and reach its source;
3. identify an actual/estimate or SEC/Value Line conflict without treating one
   source as silently authoritative;
4. create a bear/base/bull valuation range and state the most sensitive
   assumption;
5. save a human-authored decision with a disconfirming view, kill criterion,
   and review trigger, then explain what would cause a later revision.

A task succeeds only when the participant satisfies every required observation
and saved-field assertion in the locked moderator rubric and identifies every
seeded source/price/estimate conflict relevant to that task. The beta passes
when each task succeeds for at least four of five participants, no participant
mistakes a system/13F/AI output
for a recommendation or user decision, and no participant acts on a conflicting
or unavailable price as if it were valid. Raw notes, seeded fixtures, per-task
results, and moderator rubric are retained under the approved test-data and
participant-consent policy. Reports use participant pseudonyms and contain no
private portfolio or unrelated research content.

## 5. Oracle's Lens consumer-settling SLO

Against the locked Docker acceptance dataset, each Oracle's Lens consumer query
must settle into data, an explicit empty state, or a typed actionable error
within 10 seconds. The client hard-stops the loading state at 15 seconds and
shows retry plus a correlation-safe diagnostic; an indefinite spinner fails.

The browser test covers ready, warning, empty, server error, client timeout,
period change, filtered universe, and superseded-signal fixtures. It compares
the selected period, snapshot/version identity, manager count, linked-holding
count, and candidate count across dashboard, inbox, watchlist, and case origin.
Any undocumented scope difference or stale mixed snapshot fails the test.

These numbers are beta acceptance thresholds, not production capacity claims.
A future change belongs in this delivery protocol and must be reviewed before
the evaluation cycle begins.

## 6. Stage evidence package

The stage gate requires one version-pinned evidence package, retained under the
approved project/test-data policy, that records:

- the approved manifest and evaluation cutoff;
- source-policy authorization decisions used by the run;
- ingestion and point-in-time replay results;
- canonical publication and reconciliation reports;
- traceability and cross-user authorization results;
- calculation golden cases and unsupported-method outcomes;
- EOD/history, corporate-action, and current-price consistency results;
- browser/SLO results;
- moderated usability rubric and anonymized outcomes;
- the exact commit and policy/mapping/calculation versions tested.

No aggregate percentage can hide a critical failure: a privacy leak, second
queryable financial truth, look-ahead, silent source substitution, unsupported
industry formula published as valid, or conflicting current price is an
automatic stage failure.
