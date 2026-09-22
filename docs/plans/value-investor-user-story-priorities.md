# ValuePilot Value-Investor User Stories and Product Priorities

Status: Proposed next-phase product target

Date: 2026-09-10

## Conclusion

From the code, ValuePilot is no longer merely a parser project: it already has 13F candidate discovery, Watchlists, research cases, immutable decision versions, a manual position journal, notifications, and data-operations workflows.

From a long-term value investor's real workflow, however, its strongest areas are discovering leads, preserving records, and operating data. Its weakest core middle is still:

```
trusted financial facts
  -> business understanding
  -> normalized owner earnings
  -> falsifiable valuation
  -> thesis-driven monitoring
```

“Implemented” below means that a user-facing page, API, model, or service exists in the code. Product documents and backlog items are not counted as implementation.

## Existing User Stories Found in Code

| User story | Status | Code evidence |
|---|---|---|
| As a user, I can register, sign in, refresh or end my session, and view my account. | Implemented | `backend/app/api/v1/endpoints/auth.py` |
| As a user, I can request deletion of my account data. | Implemented | `backend/app/api/v1/endpoints/users.py` |
| As a user, I can upload, list, download, delete, and reparse Value Line documents. | Implemented | `backend/app/api/v1/endpoints/documents.py` |
| As a user, I can inspect raw text, evidence, extracted values, and a structured report review. | Implemented | `backend/app/api/v1/endpoints/documents.py` |
| As a user, I can compare facts and evidence between two reports. | Implemented | `backend/app/api/v1/endpoints/documents.py` |
| As a user, I can submit a manual correction without mutating the original extraction. | Implemented | `backend/app/api/v1/endpoints/extractions.py` |
| As a user, I can inspect a company summary with price, P/E, report provenance, F-Score, conflict indicators, and 13F holder context. | Implemented | `frontend/app/(dashboard)/stocks/[ticker]/summary/page.tsx` |
| As a user, I can retrieve canonical facts, source-reconciliation results, and SEC publication evidence for a stock. | Backend implemented; frontend presentation incomplete | `backend/app/api/v1/endpoints/stocks.py` |
| As a user, I can use a DCF workspace, adjust assumptions, and save my own fair value. | Implemented, but lightweight | `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx` |
| As a user, I can run a JSON-rule stock screen and open research from its results. | Implemented, but technically oriented | `frontend/app/(dashboard)/screener/page.tsx` |
| As a user, I can create Watchlists, add or remove tickers, refresh prices, maintain fair value, and inspect margin of safety and F-Score. | Implemented | `frontend/app/(dashboard)/watchlist/page.tsx` |
| As a user, I can compare three years of Piotroski F-Scores across Watchlist companies. | Implemented | `backend/app/api/v1/endpoints/stock_pools.py` |
| As a user, I can browse value-investor managers, filings, holdings, ownership changes, and a single-stock history. | Implemented | `backend/app/api/v1/endpoints/institutions.py` |
| As a user, I can use 13F as caveated candidate discovery and corroboration rather than a trading instruction. | Implemented | `frontend/app/(dashboard)/13f/oracles-lens/page.tsx` |
| As a user, I can inspect Watchlist × 13F conviction, holder change, distinctiveness, and caveats. | Implemented | `backend/app/api/v1/endpoints/stocks_13f.py` |
| As a user, I can create a research case from ticker search, a screen, Watchlist, Oracle's Lens, or a manager holding and retain the discovery origin. | Implemented | `backend/app/api/v1/endpoints/research.py` |
| As a user, I can record a thesis, disconfirming view, assumptions, risks, external evidence, a valuation range, a decision, and a next-review date. | Implemented, primarily free text | `frontend/app/(dashboard)/research/cases/[id]/page.tsx` |
| As a user, I can save immutable research revisions, handle concurrent edits, and inspect revision and event history. | Implemented | `backend/app/api/v1/endpoints/research.py` |
| As a user, I can move a case through researching, monitoring, closed, or voided states and record watch, own, or pass. | Implemented | `backend/app/models/research.py` |
| As a user, I can view, snooze, dismiss, or complete research actions. | Implemented | `backend/app/api/v1/endpoints/research.py` |
| As a user, I can see whether a case lacks prices, reports, valuation inputs, or identity verification. | Implemented | `backend/app/api/v1/endpoints/coverage.py` |
| As a user, I can follow managers; configure Slack or email destinations, frequencies, quiet hours, and thresholds; and manage my notification inbox. | Implemented | `backend/app/api/v1/endpoints/notifications.py` |
| As a user, I can create a manual portfolio and record open, resize, review, and close events linked to research cases and revisions. | Implemented | `backend/app/api/v1/endpoints/portfolios.py` |
| As an operator, I can maintain 13F managers, CIKs, CUSIPs, amendments, filings, parse runs, jobs, backfills, quality reports, and recovery actions. | Implemented | `backend/app/api/v1/endpoints/thirteenf_admin.py` |
| As an administrator, I can record method-classification and method-risk reviews. | Implemented | `backend/app/api/v1/endpoints/admin.py` |
| As a parser-quality owner, I can review parser calibration runs. | Not implemented: the UI is an explicit placeholder. | `frontend/app/(dashboard)/calibration/page.tsx` |

## Prioritized Product Story Map

Priority is ordered by whether the capability helps a long-term investor avoid permanent capital loss and make an independent, falsifiable capital-allocation decision. It is not ordered by development effort.

| Priority | Investor story that should exist | Current code-aligned support | Main gap / next target |
|---:|---|---|---|
| 1 | As an investor, I can see trustworthy, complete, source-traceable core financial history and know explicitly when it is missing, conflicting, or inapplicable. | Partially implemented; S1 enables retained AAPL SEC facts. | Complete annual financial tables, usable evidence navigation, and broader company coverage are still missing. |
| 2 | I can understand how a business earns money, its moat, growth drivers, capital needs, and circle-of-competence boundaries. | Partial. | Current thesis fields are free text; there is no structured business model, competitive advantage, management, capital-allocation, or key-variable framework. |
| 3 | I can reconstruct and review normalized owner earnings from revenue, profit, CFO, capex, working capital, SBC, and acquisitions. | Partial. | DCF inputs and some calculations exist, but there is no user-facing owner-earnings bridge, adjustment rationale, or annual trend review. |
| 4 | I can express intrinsic value as scenarios and a range, with assumptions, currency, date, price source, and margin of safety visible. | Partial. | DCF and fair value exist, but scenario analysis, sensitivity, assumption changes, and thesis linkage are insufficient. |
| 5 | I can record the strongest opposing case, falsification conditions, and unknowns, each connected to supporting or contradicting evidence. | Partial. | `variant_view`, risks, and evidence exist, but there is no structured claim–evidence–counterevidence–decision-rule model. |
| 6 | I receive low-noise prompts when a thesis-relevant fundamental, filing, valuation assumption, or review deadline changes. | Partial. | Inbox, notifications, 13F events, and review dates exist, but not thesis-specific triggers or a clear explanation of what changed. |
| 7 | I can preserve each judgment and its contemporaneous evidence, then review it later without hindsight bias. | Implemented and comparatively strong. | Add outcome and learning structures rather than only revisions and position events. |
| 8 | I can discover companies worth researching from a high-quality candidate set while understanding 13F delay and limits. | Implemented and comparatively mature. | Do not prioritize more 13F scoring before the candidate-to-financial-truth research handoff works. |
| 9 | I can review a value investor's holdings, changes, history, and data caveats as a research lead. | Implemented. | 13F does not establish cost basis, complete portfolios, or investment rationale; UI must continue to prevent “follow the guru” implications. |
| 10 | I can manage a Watchlist with my valuation, prices, MOS, F-Score, and 13F context. | Implemented. | Evolve it from a table into an action surface: what deserves research or review now and why. |
| 11 | I can inspect source documents, locators, parsed values, and corrections to decide whether a number is trustworthy. | Implemented for Value Line; SEC support is incomplete in the user experience. | Finish SEC evidence navigation, authorization states, and usable financial statements. |
| 12 | I can screen companies using understandable definitions, periods, provenance, and missing-data states. | Partial. | The current JSON editor is a developer-facing interface, not a value-investor screener. |
| 13 | I can compare active candidates by business quality, valuation, decisive risks, research completeness, and opportunity cost. | Not implemented. | Current Watchlist, case, and DCF views are separate; there is no genuine opportunity-comparison workspace. |
| 14 | I can link manual holdings to the decision/revision that justified them and later review position changes. | Basic implementation exists. | Missing holding-period outcome, expected-vs-actual variance, decision quality, and non-price-driven postmortem. |
| 15 | I can safely manage account access, private research, notification consent, and deletion. | Implemented. | Necessary trust foundation, but not the primary reason an investor chooses ValuePilot. |
| 16 | As an operator, I can keep 13F data recoverable, auditable, repairable, and unable to silently contaminate product surfaces. | Implemented and mature. | Its complexity should continue to serve data trust rather than become the dominant product investment. |
| 17 | As a parser-quality owner, I can run, compare, and audit calibration results and quantify parser error. | Not implemented. | The current Calibration UI is a placeholder; this is required to scale parser trust beyond individual gold-set successes. |

## Product Assessment

The current product is best described as:

> A research system with credible research memory and candidate discovery, now building its financial-truth layer, but not yet a complete experience for understanding a business and making a capital-allocation decision.

The strongest product decisions are that 13F and DCF are not presented as direct buy/sell signals; research cases preserve immutable revisions, sources, valuation ranges, risks, review dates, and manual-portfolio boundaries.

The principal risk is prioritization mismatch. 13F operations and administrative capabilities are deep, while the central investor workflow—financial truth, owner earnings, business-quality judgment, disconfirmation, and thesis-driven monitoring—remains incomplete. For a serious value investor, these missing middle capabilities are more valuable than additional 13F score dimensions.

## Recommended Direction

1. **Finish one trustworthy company research page before expanding more data sources.**

   Turn S1 SEC facts into a readable annual financial table with field evidence, source/conflict/missing states, and basic trends. Make AAPL usable for independent research before scaling company count.

2. **Upgrade the free-text case into a structured research canvas.**

   Add business model, competitive advantage, growth drivers, capital intensity, management and capital allocation, key risks, key variables, disconfirming conditions, and unresolved questions. Preserve narrative text, but do not make it the only structure.

3. **Build a user-visible owner-earnings bridge.**

   Explain why reported CFO is not automatically owner earnings; identify capex, SBC, working-capital, acquisition, and other adjustments; clearly distinguish reported facts from user judgments.

4. **Make monitoring thesis-driven rather than price- or event-driven.**

   Each key assumption or kill criterion should have observable indicators, trigger conditions, data sources, ownership, and a review date.

5. **Build comparison and postmortem after the single-company foundation is trustworthy.**

   Only then add candidate comparison, capital-allocation comparison, decision-quality measurement, and postmortems. Otherwise the product will compare incomplete evidence more elegantly without improving judgment.

## North-Star User Story

> As a long-term investor, when a company enters my research universe, I can see which facts are trustworthy, which questions remain unresolved, what must be true, what would falsify the view, and at what price range action would be justified; later I can review that judgment against new evidence.
