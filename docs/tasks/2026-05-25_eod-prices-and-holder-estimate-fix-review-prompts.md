# Review prompts — PR #97 (EOD prices + holder $ estimate unit fix)

Task doc: [`2026-05-25_eod-prices-and-holder-estimate-fix.md`](./2026-05-25_eod-prices-and-holder-estimate-fix.md)
PR: https://github.com/d41689/ValuePilot/pull/97
Branch: `claude/eod-prices-and-holder-estimate-fix`

This change ships a per-row unit-disambiguation helper for the SEC 13F `<value>`
field in the Oracle's Lens dashboard, plus an ops backfill of EOD prices for the
2025-Q4 universe. The visible UI bug (1000× spread on holder estimates) is gone;
the underlying data-quality issues that made it surface — `value_usd` not
populated, `is_latest_for_period` only flagged on 2025-Q4 — are scoped out and
spawned as separate tasks.

The three review prompts below are for **three different external agents**. They
review the same PR but from different angles. Run them in parallel; collect each
agent's findings under `2026-05-25_eod-prices-and-holder-estimate-fix-review-results.md`.

---

## Prompt 1 — Backend reviewer (financial-data correctness)

```
You are a senior backend engineer reviewing PR #97 of the ValuePilot 13F
platform. Your specialty is financial-data correctness and SEC filing
semantics.

Repository: https://github.com/d41689/ValuePilot
Branch under review: claude/eod-prices-and-holder-estimate-fix
PR: https://github.com/d41689/ValuePilot/pull/97
Read first:
  - docs/tasks/2026-05-25_eod-prices-and-holder-estimate-fix.md (task doc)
  - AGENTS.md (cross-agent contract; especially the "critical invariants" list)
  - backend/app/edgar/parsers/value_units.py (the existing parser logic this PR
    inherits the TRANSITION_ACCEPTED_DATE constant from)
  - backend/app/services/oracles_lens/dashboard.py (where the change lives)

The motivating bug: Oracle's Lens cards showed "$483.60–$483,620.35" for MSFT —
a 1000× spread because the formula treated SEC <value> as if it were always in
thousands, but post-2023-01-03 the SEC reports it in dollars. Furthermore,
within a single (stock, period), some filers still report in thousands even
post-transition (3 of 32 MSFT 2025-Q4 holders).

The PR introduces two pure helpers in
backend/app/services/oracles_lens/dashboard.py:

  - _holder_price_estimate(*, value_thousands, value_usd, shares, accepted_at,
    period_of_report, peer_anchor) -> float | None
  - _resolve_peer_anchor(holdings: list[ManagerHolding]) -> float | None

and wires them into _stock_payload.

Specifically review:

  1. UNIT-DECISION CORRECTNESS. Is the resolution order
     (value_usd → peer_anchor → accepted_at → period_of_report → None)
     defensible? Is the boundary at TRANSITION_ACCEPTED_DATE (2023-01-03)
     correctly the cliff between "thousands" and "dollars" rules?

  2. PEER-ANCHOR ROBUSTNESS. _resolve_peer_anchor picks the densest cluster
     across the union of dollars-rule and thousands-rule candidates from all
     siblings, using a ±10% band. Walk through these edge cases on paper:

       a) A stock held by exactly 1 superinvestor. No peer cluster — does
          the anchor fall back gracefully and the helper hit the accepted_at /
          period_of_report branch?
       b) A stock held by 2 managers, one in each unit regime. Are both
          rule's candidates within ±10% of each other (and thus the densest
          cluster contains both)? If so, the anchor will be the median of two
          unrelated values and both rows pick the "closer" candidate, which
          could be either. Does this produce a sensible answer or random noise?
       c) A stock with extreme share price (e.g., BRK.A at ~$700,000). Does
          the ±10% band still cluster correctly? Confirm that "100000" is the
          right upper plausibility bound, or argue for a different bound.
       d) A penny stock (e.g., a $0.05 stock). Does the heuristic mistake
          the dollars-rule candidates for the "thousands-rule wrong" cluster?

  3. NUMERICAL STABILITY. The helper uses math.log to compare distances
     between candidate and peer_anchor. Are the guards against log(0) and
     negative values complete?

  4. INTEGRATION SAFETY. _resolve_peer_anchor is called once per stock in
     _stock_payload. Is it correctly idempotent across the legacy in-memory
     path AND the canonical persisted-score path
     (_apply_persisted_scores / _apply_live_filtered_scores)?
     Specifically: does the peer anchor get computed for stocks loaded by
     the filtered/universe-selector path too?

  5. TEST COVERAGE. backend/tests/unit/test_oracles_lens_holder_price_estimate.py
     has 30 tests. Are any critical scenarios missing? Specifically:
       - A row with value_usd populated AND value_thousands inconsistent with
         it (e.g., manual data correction);
       - A row where shares is 0 negative AND value_usd is present;
       - peer_anchor with a single-element holdings list;
       - peer_anchor when ALL rows have value_usd populated (does the helper
         skip the dollars/thousands candidate computation correctly?).

  6. PRE-EXISTING SCOPE BOUNDARY. The PR scopes out two structural issues:
     (a) value_usd is NULL on every existing row because Filing13F.accepted_at
     is missing, (b) Filing13F.is_latest_for_period is only set on 2025-Q4.
     Both are spawned as separate tasks. Is this scope split defensible, or
     should the PR have addressed them inline? If split, is the per-row
     peer-anchor heuristic an acceptable bridge until (a) is fixed?

  7. DASHBOARD SHAPE. _stock_payload returns holder_price_estimate_low /
     _high and per-top-holder holder_price_estimate. Both now go through the
     same helper. Confirm the per-holder result rounding (round(..., 6)) is
     consistent with what the FE expects (lib/oraclesLens.js
     normalizeValuationReference uses formatNumber(..., 2) — so trailing
     precision is truncated for display anyway).

For each finding, classify severity: P0 (must fix before merge), P1 (must
fix in a follow-up), P2 (nice-to-have), or NIT (style/wording). Include a
concrete fix or test case where applicable.
```

---

## Prompt 2 — Staff engineer (architecture + invariants)

```
You are a staff engineer reviewing PR #97 of the ValuePilot 13F platform.
Your concern is system-level invariants, not local correctness.

Repository: https://github.com/d41689/ValuePilot
Branch: claude/eod-prices-and-holder-estimate-fix
PR: https://github.com/d41689/ValuePilot/pull/97
Read first:
  - AGENTS.md (cross-agent contract; especially "Critical invariants — never
    violate" and "Workflow / Deferred work")
  - docs/tasks/2026-05-25_eod-prices-and-holder-estimate-fix.md
  - docs/BACKLOG.md (deferred work register)
  - docs/architecture/data-layer.md (canonical units / source of truth)

Review this PR against ValuePilot's core invariants and architectural
posture. Specifically:

  1. CANONICAL SOURCE OF TRUTH. The schema declares
     Holding13F.value_usd as the canonical unit-normalized column. This PR
     adds a per-row display-time heuristic that LOOKS at the unnormalized
     value_thousands and decides the unit per-row. Is that a violation of
     "metric_facts is the only queryable source of truth" by analogy
     (i.e., dashboards should read normalized columns, not re-normalize at
     read time)? If yes, how serious — does it set a precedent we'll
     regret?

  2. SCOPE-CREEP DISCIPLINE. The PR title says "fix holder $ estimate
     unit bug + EOD price backfill". During implementation the author
     discovered two larger structural issues (value_usd never populated,
     is_latest_for_period only set on 2025-Q4) and chose to spawn them as
     separate tasks rather than expand scope. Was that the right call?
     Per AGENTS.md: "A finding that risks data loss, a security hole, or
     production breakage is not yours to defer — stop and tell the user."
     Argue: do these structural issues meet that bar?

  3. PRE-EXISTING TEST POLLUTION. The PR description acknowledges 185
     pre-existing test failures in the dev DB and asserts net-zero
     regressions. Was that verified correctly (run pytest -q before AND
     after the change on the same DB, compare counts and per-test names)?
     Inspect the methodology described in the PR — is the comparison
     sound?

  4. PEER-ANCHOR HEURISTIC LONGEVITY. The author plans to retire the
     peer-anchor logic once value_usd is backfilled. Two failure modes:
       (a) The backfill task gets indefinitely deprioritized, so the
           heuristic stays "temporary" for years and accretes assumptions.
       (b) The backfill lands but no one remembers to delete the heuristic,
           and we accumulate dead code.
     What guardrails should the PR add to make either failure visible?
     (Examples: a structured log when peer-anchor branch is taken; a
     periodic admin-dashboard finding if >1% of rows go through it; a
     module-level docstring TODO with the backlog ID.)

  5. AGENTS.md ALIGNMENT. The PR claims to follow the "test-first"
     workflow. Inspect the commit history of the branch — is there a "red →
     green" sequence visible, or was production code written first and
     tests added after? (One commit is fine if the dev pattern is
     internal-to-author; but the convention is to be able to point to it.)

  6. ROLLBACK SAFETY. If we revert this PR after the EOD backfill has
     run, what's the recovery path? Are there any DB writes that the
     scripts.backfill_13f_period_prices run made that would need to be
     reverted, OR is the price data immutable historical truth that's
     safe to keep?

  7. DESIGN DOC vs CODE DRIFT. The task doc claims the helper uses
     "log-space distance" for the peer_anchor comparison. Confirm the code
     actually uses math.log (not log10 or natural log of ratio with a
     different sign), and that the test fixtures exercise this branch.

For each concern, recommend an action: enforce, defer to backlog with
specific entry, or accept as-is. Be concrete; abstract architectural
critique without a concrete next step is not actionable.
```

---

## Prompt 3 — PO / value-investor reviewer (UX + financial sanity)

```
You are the Product Owner of ValuePilot reviewing PR #97. You are a
practicing value investor who uses the Oracle's Lens dashboard to make
real sizing decisions. Your concern is "can I trust what I'm seeing"
rather than code.

Repository: https://github.com/d41689/ValuePilot
PR: https://github.com/d41689/ValuePilot/pull/97
After the PR is merged and the EOD backfill has run:
  - Open http://localhost:3001/13f/oracles-lens
  - Switch to the 2025-Q4 quarter (the only one with full data)
  - Open the top 10 candidate cards and look at the "Holder estimate"
    range, the current price, and the discount-to-reference line

Review questions:

  1. DOES THE NUMBER MAKE SENSE? Before this PR, MSFT showed
     "$483.60–$483,620.35". After: "$483.60–$483.62" against a current
     price of $483.62. Is that range NOW too tight, suggesting we're
     hiding real holder-cost diversity behind a per-stock anchor? Or is
     it actually right because all holders report the SAME quarter-end
     fair value, so the holder estimate IS just the quarter-end price?
     (Hint: read the helper's docstring and decide whether
     "holder_price_estimate" is named accurately — it's not really
     "what the holder paid", it's "implied per-share value at the
     quarter-end snapshot".)

  2. NAMING ACCURACY. Given (1), should we rename
     holder_price_estimate → quarter_end_implied_per_share (or similar)
     before more UI features depend on the field name? The current
     name suggests it's the holder's COST BASIS, which it isn't.

  3. EDGE CASES IN THE UI. Visit:
       - BRK/B (no current price because yfinance can't resolve "BRK/B")
       - Any stock with only 1 superinvestor holder (the peer-anchor
         heuristic has no peers to anchor against)
       - A pre-2025-Q4 quarter (2025-Q3 or earlier) — the Oracle's Lens
         page is mostly empty because of the is_latest_for_period bug.
         Does the page handle the empty state gracefully, or does it
         look broken?
     Note any UX gap that would lead a real user to second-guess the
     data.

  4. ANNOTATED HONESTY. For the 3 MSFT 2025-Q4 holders whose value field
     used the legacy "thousands" rule (AKO Capital, Robert Olstein,
     Triple Frond Partners): should the drawer/detail UI indicate "this
     holder's value field is in legacy units; we inferred the per-share
     price from sibling consensus"? Or is that level of detail noise to
     a value-investor user?

  5. SCOPE PRIORITIZATION. The PR spawned two follow-up tasks:
       (a) value_usd backfill across 12 quarters (~1 day's work)
       (b) is_latest_for_period repair for 11 quarters (~half-day's work
           plus an ops re-run)
     Plus the still-open backlog from prior PRs (Value Line PDF parsing,
     Watchlist thesis, caution flags, 1Q median streak investigation).
     Rank these for the next sprint. Justify the top pick from a
     value-investor's perspective (what's the highest-leverage data
     issue to fix next?).

  6. TRUST CALIBRATION. After this PR ships, can you make a real sizing
     decision using the 2025-Q4 Oracle's Lens dashboard, or are there
     still gating data-quality issues? List them in priority order.

Submit your review as freeform paragraphs grouped by question number.
Use "BLOCKER" prefix for anything that would make you NOT merge.
```

---

## How to consume the review results

After collecting all three agents' findings into
`2026-05-25_eod-prices-and-holder-estimate-fix-review-results.md`, group
issues by severity:

- **P0 (BLOCKER)**: address before merge. Push a follow-up commit on the
  same branch.
- **P1**: address before merge if any reviewer flags. If split between
  reviewers, the author decides (with a written rationale in the PR
  thread).
- **P2 / NIT**: defer to `docs/BACKLOG.md` with a link to the review
  doc. Mention the deferral explicitly in the PR description before
  merging.

Run the canonical CI commands one more time after addressing P0/P1
findings:

```
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```
