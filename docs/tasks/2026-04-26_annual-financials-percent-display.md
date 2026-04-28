# Task: Fix annual financials percent display

## Goal / Acceptance Criteria
- In `/documents/578/review`, the ANNUAL FINANCIALS card must show percent metrics with a trailing `%`.
- Cover all annual financial rows that semantically represent percentages, including income statement ratios, balance sheet return ratios, valuation percentage rows, and dividend yield rows.
- Keep normalized database values unchanged; this is a display formatting fix.

## Scope
**In**
- Frontend annual financials table formatting.
- Focused frontend tests for percent rows.
- Browser/API verification of document `578` review data if needed.

**Out**
- Parser schema changes.
- Metric facts normalization changes.
- Unrelated review page layout changes.

## Files To Change
- `docs/tasks/2026-04-26_annual-financials-percent-display.md`
- `frontend/lib/documentReview.js`
- `frontend/lib/documentReview.test.js`

## Test Plan
- `docker compose exec web node --test lib/documentReview.test.js`
- `docker compose exec api pytest -q` if backend behavior is touched.

## Progress Log
- [x] Create task log.
- [x] Add failing frontend test for annual financial percent rows.
- [x] Implement display formatting fix.
- [x] Run Docker verification.
- [x] Verify document `578` review page in the in-app browser.

## Notes / Decisions / Gotchas
- User provided local login credentials for browser verification if needed.
- Annual financial raw block values are display-oriented page values; this task should append `%` without mutating underlying numeric values or backend facts.
- Added an explicit frontend percent-row registry for annual financial metrics rather than inferring from labels. Covered operating/income statement ratios, balance-sheet return/dividend percentage rows, price-to-book percentage, and average dividend yield.
- In-app browser verification found the existing session already authenticated. The page showed `%` for Return on Total Capital, Return on Shareholders Equity, Retained to Common Equity, All Dividends to Net Profit, and Avg Annual Dividend Yield.

## Verification Results
- `docker compose exec web node --test lib/documentReview.test.js` -> passed (`17 passed`)
