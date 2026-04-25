# Review Header Summary Card

## Goal / Acceptance Criteria

Implement the first-stage cleanup for `/documents/{id}/review` by adding a top summary card that shows:

- company name
- exchange
- ticker
- recent price
- p/e ratio
- p/e trailing
- p/e median
- relative p/e ratio
- div'd yld

The card must use document review data only and render missing values safely. For this stage, remove the other review cards below it, then add back a focused Rating card that shows:

- TIMELINESS with rank and event label/date when available
- SAFETY with rank and event label/date when available
- TECHNICAL with rank and event label/date when available
- BETA value

Add a focused `18-Month Target Price Range` card that shows:

- Low
- High
- Midpoint
- `% to Mid`

Add a focused `PROJECTIONS` card that renders a table with:

- Rows: High, Low
- Columns: Price, Gain, Ann'l Total Return

Add a focused `Institutional Decisions` card that renders a table with:

- Rows: to Buy, to Sell, Hld's(000)
- Columns: available quarterly periods from the parsed facts

Add a focused `CAPITAL STRUCTURE` card that shows the parsed capital structure block.

Add a focused `CURRENT POSITION` card that renders the parsed current-position block as a table.

Add a focused `ANNUAL FINANCIALS` card that renders the parsed annual financials block as a table.

Add focused parser-backed table cards for:

- `ANNUAL RATES`
- `QUARTERLY SALES`
- `EARNINGS PER SHARE`
- `QUARTERLY DIVIDENDS PAID`

Add bottom narrative cards for:

- `BUSINESS NARRATIVE`
- `ANALYST COMMENT`

Add a focused `Quality` card directly below the Rating card.

## Scope

### In

- Extend document review API payload with header summary fields needed by the page.
- Add frontend rendering for the top summary card on the review page.
- Remove the other review cards/panels from the page for this stage.
- Add a focused Rating card using fact-backed rating values plus evidence-only rating event dates.
- Add a focused Quality card using fact-backed quality values.
- Add a focused 18-month target price range card using current review facts.
- Add a focused projections card using current review facts.
- Add a focused institutional decisions card using current review facts.
- Add a focused capital structure card using current review facts plus parser-backed notes/placeholders that are not fact rows.
- Add a focused current position table using the parser-backed current-position block.
- Add a focused annual financials table using the parser-backed annual financials block, with fact-backed groups as fallback.
- Add focused parser-backed tables for annual rates, quarterly sales, earnings per share, and quarterly dividends paid.
- Add bottom evidence-backed narrative cards for business narrative and analyst comment.
- Add focused backend/frontend tests for the new payload and formatting behavior.

### Out

- No PRD changes.
- No schema changes.
- No parser changes.
- No changes to review correction behavior.
- No redesign of lower review sections in this stage; non-summary/non-rating cards are temporarily hidden/removed from the page.

## PRD References

- `docs/prd/value-pilot-prd-v0.1.md`
  - `C. Data Modeling & Storage (PostgreSQL)`
  - `metric_facts (queryable facts for formulas/screeners)`
  - `Data Traceability Requirements`
- `docs/prd/value-pilot-prd-v0.1-multipage.md`
  - `4.3 Output Contract (API)`
  - `5.4 metric_facts`
  - `6. Normalization`

## Files To Change

- `backend/app/api/v1/endpoints/documents.py`
- `backend/tests/unit/test_documents_api.py`
- `.gitignore`
- `frontend/app/(dashboard)/documents/[id]/review/page.tsx`
- `frontend/lib/documentReview.js`
- `frontend/lib/documentReview.test.js`

## Execution Plan

1. Add failing backend test for review payload summary fields.
2. Add failing frontend helper test for summary card formatting.
3. Extend backend review response with document header summary derived from current document facts and stock identity.
4. Render the new top summary card in the review page and remove the lower review cards for this stage.
5. Add a Rating card that combines review facts with `/documents/{id}/evidence` rating event metadata.
6. Add an 18-month target price range card from the review fact groups.
7. Add a projections table card from the review fact groups.
8. Add an institutional decisions table card from the review fact groups.
9. Add a capital structure card from the review fact groups and parser-backed capital structure block.
10. Move the capital structure card behind the currently visible focused cards.
11. Add a current position table card from the parser-backed current-position block.
12. Add an annual financials table card from the parser-backed annual financials block, falling back to review fact groups.
13. Add parser-backed annual rates and quarterly time-series table cards.
14. Add bottom business narrative and analyst comment cards from evidence-only narrative fields.
15. Add a Quality card below Rating from the existing ratings/quality fact group.
16. Run focused tests in Docker, then broader relevant verification if needed.

## Contract Checks

- Summary values must come from `metric_facts`, not `metric_extractions`.
- Rating rank/BETA values must come from `metric_facts`; rating change labels/dates may come from evidence-only `metric_extractions`.
- Quality values must come from `metric_facts`.
- Target price range values must come from `metric_facts`.
- Projection values must come from `metric_facts`.
- Institutional decision values must come from `metric_facts`.
- Capital structure numeric values must prefer `metric_facts`; parser-backed notes/placeholders may come from immutable `metric_extractions`.
- Current position table values may come from immutable parser-backed `metric_extractions` until the block is normalized into individual fact rows.
- Annual financials values should prefer the parser-backed annual financials block for full Value Line table coverage; fact-backed groups remain the fallback.
- Annual rates and quarterly time-series cards may come from immutable parser-backed `metric_extractions` until those blocks are normalized into individual fact rows.
- Business narrative and analyst comment cards may come from immutable evidence-only `metric_extractions`.
- Numeric display must use normalized/current facts already attached to the reviewed document.
- No raw SQL from user input.
- Existing lineage fields and correction immutability behavior remain unchanged.

## Rollback Strategy

- Revert the new review summary payload fields and header card only.
- Keep existing review groups and correction flow untouched.

## Test Plan

- `docker compose up -d --build`
- `docker compose exec api pytest -q backend/tests/unit/test_documents_api.py`
- `docker compose exec frontend npm test -- documentReview.test.js`

## Progress Notes

- 2026-04-24: Task created for stage-one cleanup of the document review page header area.
- 2026-04-24: Added backend review summary payload for recent price, P/E, trailing P/E, median P/E, relative P/E, dividend yield, plus stock exchange on the document header.
- 2026-04-24: Added frontend summary-card rendering at the top of `/documents/[id]/review` with a stable six-metric grid and company identity badges.
- 2026-04-24: Added focused backend and frontend tests for summary payload shape, metric order, and fallback display formatting.
- 2026-04-24: Revised the page to keep only the summary card visible after loading; lower report-layout cards and evidence/correction panels are removed for this stage.
- 2026-04-24: Added a focused Rating card for TIMELINESS, SAFETY, TECHNICAL, and BETA, with event labels/dates sourced from the evidence endpoint where available.
- 2026-04-24: Added the focused 18-month target price range card for Low, High, Midpoint, and `% to Mid`.
- 2026-04-24: Adjusted `% to Mid` display to render decimal display values as percentages.
- 2026-04-24: Added the focused PROJECTIONS table card for High/Low price, gain, and annual total return.
- 2026-04-24: Confirmed parser JSON has `long_term_projection.scenarios.*.price_gain`; added canonical mappings so Gain is written to `metric_facts` as `proj.long_term.*_price_gain`.
- 2026-04-24: Added the focused Institutional Decisions card for quarterly to Buy, to Sell, and Hld's(000), with holdings normalized to shares in `metric_facts` and displayed in thousands.
- 2026-04-24: Added the focused CAPITAL STRUCTURE card for parsed debt, preferred, shares, and market-cap facts.
- 2026-04-24: Revising CAPITAL STRUCTURE to show the full parser-backed block and move the card to the end of the focused review cards.
- 2026-04-24: Expanded CAPITAL STRUCTURE to use the parser-backed block for null placeholders and notes while preferring fact-backed normalized values when available.
- 2026-04-24: Added the focused CURRENT POSITION table card using the parser-backed current-position block.
- 2026-04-24: Fixed CURRENT POSITION row filtering so Inventory and Debt Due remain visible even when the parsed values are null.
- 2026-04-24: Added the focused ANNUAL FINANCIALS table card using current annual metric facts, with distinct rows by metric key to avoid same-label collisions.
- 2026-04-24: Expanded ANNUAL FINANCIALS to prefer the parser-backed annual financials block so valuation, balance sheet, null cells, and projection columns are displayed.
- 2026-04-24: Marked ANNUAL FINANCIALS estimate-year and projection cells so the UI renders them in red.
- 2026-04-24: Verified the red styling was not applied to the ANNUAL FINANCIALS table cells; moving the estimate-specific color logic onto those cells and removing conflicting default text color.
- 2026-04-24: Adding parser-backed table cards for ANNUAL RATES, QUARTERLY SALES, EARNINGS PER SHARE, and QUARTERLY DIVIDENDS PAID.
- 2026-04-24: Added review API payload fields and frontend table cards for the four parser-backed annual/quarterly blocks; estimate cells render in red consistently with the annual financials table.
- 2026-04-24: Added the TypeScript incremental build cache file to `.gitignore` after running `tsc --noEmit`.
- 2026-04-24: Adding bottom evidence-backed BUSINESS NARRATIVE and ANALYST COMMENT cards.
- 2026-04-24: Added bottom BUSINESS NARRATIVE and ANALYST COMMENT cards using evidence-only narrative fields already loaded by the review page.
- 2026-04-24: Adding a focused Quality card below Rating using current quality facts.
- 2026-04-24: Added the focused Quality card below Rating for Financial Strength, Price Stability, Price Growth Persistence, and Earnings Predictability.
- 2026-04-24: Investigating ANNUAL FINANCIALS numeric formatting on document 1453 where floating-point artifacts produce overly long decimal tails.
- 2026-04-24: Updated ANNUAL FINANCIALS row formatting to infer decimal places per metric row and format all numeric cells consistently, removing floating-point tails.

## Verification Results

- `docker compose up -d --build` -> pass.
- `docker compose exec -T api pytest -q tests/unit/test_documents_api.py` -> pass (`16 passed`).
- `docker compose exec -T api pytest -q tests/unit/test_metric_facts_mapping_spec.py` -> pass (`1 passed`).
- `docker compose exec -T api pytest -q tests/unit/test_value_line_field_taxonomy.py` -> pass (`2 passed`).
- `docker compose exec -T web node --test lib/documentReview.test.js` -> pass (`13 passed`).
- `docker compose exec -T web node --test lib/documentReview.test.js` -> pass after moving red estimate styling to the ANNUAL FINANCIALS table cells (`13 passed`).
- `docker compose exec -T web node --test lib/documentReview.test.js` -> pass after adding annual/quarterly table helpers (`15 passed`).
- `docker compose exec -T api pytest -q tests/unit/test_documents_api.py -q` -> pass after adding annual/quarterly review payload fields (`17 passed`).
- `docker compose exec -T web npx tsc --noEmit` -> pass.
- Browser sanity check on `http://localhost:3001/documents/578/review` -> found `ANNUAL RATES`, `QUARTERLY SALES`, `EARNINGS PER SHARE`, and `QUARTERLY DIVIDENDS PAID` cards plus representative table values.
- `docker compose exec -T web node --test lib/documentReview.test.js` -> pass after adding narrative card helper (`16 passed`).
- `docker compose exec -T web npx tsc --noEmit` -> pass after adding bottom narrative cards.
- Browser sanity check on `http://localhost:3001/documents/578/review` -> found `BUSINESS NARRATIVE`, `ANALYST COMMENT`, and representative business/commentary text.
- `docker compose exec -T web node --test lib/documentReview.test.js` -> pass after adding Quality helper (`17 passed`).
- `docker compose exec -T web npx tsc --noEmit` -> pass after adding Quality card.
- Browser sanity check on `http://localhost:3001/documents/578/review` -> found `Quality`, `Financial Strength`, `Price Stability`, `Price Growth Persistence`, and `Earnings Predictability`.
- `docker compose exec -T web node --test lib/documentReview.test.js` -> pass after annual financials decimal formatting update (`17 passed`).
- `docker compose exec -T web npx tsc --noEmit` -> pass after annual financials decimal formatting update.
- Frontend helper sanity check using document 1453's problematic annual values -> long floating tails format as `0.014`, `0.041`, `0.054`, etc.
- `docker compose exec -T web npm run build` -> fails on an existing Next.js prerender issue for `/404` with `Error: <Html> should not be imported outside of pages/_document.` The app compiled, linted, and type-checked before hitting that unrelated build-time error.
- After the build check, cleared `/app/.next`, restarted the `web` service, and confirmed `docker compose exec -T web node -e "fetch('http://127.0.0.1:3000/login').then(r=>console.log(r.status))"` returns `200`.
