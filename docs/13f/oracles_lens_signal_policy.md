# Oracle's Lens signal policy

Status: approved for P0 implementation  
Decision date: 2026-07-20  
Physical score version: `v1.1`  
Consensus lens: `consensus-v1.1`  
Distinctive lens: `distinctive-v1.1`  
Manager taxonomy: `manager-taxonomy-v2.0`  
13F representativeness: `13f-representativeness-v1.0`

## Product thesis

Oracle's Lens is an idea-discovery and corroboration surface, not a buy list.
A 13F is delayed, omits important asset classes and exposures, and does not
contain transaction prices. The product therefore presents two separate
questions instead of blending them into one unexplained rank.

### Consensus

Consensus asks: **where do multiple independently selected, relevant managers
show durable and economically meaningful long-equity ownership?**

It is the default corroboration lens. Breadth alone is insufficient: manager
fit, position importance, persistence, recent filing action and filing-quality
caveats remain visible components. Large-cap popularity can rank highly here;
that is a property of the question, not proof of mispricing.

### Distinctive

Distinctive asks: **which consensus result is most concentrated, persistent and
supported by managers whose 13F is a credible view of their strategy?**

It is an advanced discovery lens. It can only attenuate the consensus score;
it cannot manufacture conviction where the underlying signal is weak. It is
useful for finding less generic ideas, but fewer managers never means better by
itself.

Both lenses must show their version, component evidence, exclusions and
caveats. Neither may describe reported quarter-end ownership as current
ownership or infer a cost basis.

## Manager taxonomy review

The 82-entry curated universe was reviewed against each entry's individual
`classification_rationale`. It contains no `unknown` style entries:

| V2 style | Count | Legacy scoring type | Review disposition |
| --- | ---: | --- | --- |
| value_deep | 21 | value_concentrated | approved |
| value_concentrated | 26 | value_concentrated | approved |
| quality_compounder | 18 | long_term_fundamental | approved |
| activist | 7 | activist | approved; 13F is partial-strategy evidence |
| growth_long_short | 5 | high_turnover | approved; long book only |
| multi_strategy_macro | 3 | multi_strategy | approved; equity sleeve only |
| special_situations | 1 | multi_strategy | approved; setup can include omitted instruments |
| endowment_passive | 1 | index_like | approved; changes may be donation-driven |

The scoring-relevant edge cases were reviewed first. TCI remains `activist`;
the five named Tiger-Cub/growth-long-short firms remain `high_turnover` on the
legacy weight; Bridgewater, Oaktree and Appaloosa remain
`multi_strategy_macro`; Scion remains `special_situations`; Gates Foundation
Trust remains `endowment_passive`. A future classification change requires a
new policy/taxonomy version and recomputation; it must not rewrite old score
evidence.

## 13F representativeness

Investment style and 13F representativeness answer different questions. The
reviewed projection uses:

| Classification | Factor | Meaning |
| --- | ---: | --- |
| faithful | 1.00 | Reportable long listed equities are the primary reviewed expression of the strategy. |
| partial | 0.70 | Shorts, derivatives, credit, private/control or macro exposures make the filing a sleeve view. |
| unrepresentative | 0.20 | Observed changes are materially driven by a non-investment or non-discretionary mechanism. |
| unknown | 0.50 | Insufficient reviewed evidence; never displayed as faithful. |

The initial 82-manager distribution is 65 `faithful`, 16 `partial`, and 1
`unrepresentative`. Startup seeding persists the current classification,
policy version, reviewer, review time, rationale and evidence basis. It also
inserts one append-only decision record per manager and policy version; a
changed answer must bump the policy version instead of rewriting history. A
score component persists the manager's base weight, representativeness factor,
classification, policy version and effective review time actually used.

Legacy/unreviewed rows are explicitly reported as `unknown` with
`representativeness_scoring_applied=false`. During rollout their historical
weight is not silently rewritten. They become eligible for the documented
factor only after the reviewed policy version is present.

## Interpretation boundary

- `new`, `add`, `reduce` and `exit` mean changes between authoritative reported
  quarter-end snapshots, not trades observed on a specific date.
- Confidential treatment, partial coverage, pending/failed amendments and
  unavailable prior history demote confidence or exclude the affected holder.
- A low-turnover manager's durable new position can remain useful despite the
  filing delay; a fast or omitted-exposure strategy receives less weight.
- The score is a research-priority input. A qualified decision still requires
  business analysis, independent valuation, downside review and written
  evidence.
