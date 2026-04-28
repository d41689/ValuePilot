# Task: Add review total return card

## Goal / Acceptance Criteria
- Add a `% TOT. RETURN` card immediately after the `PROJECTIONS` card on `/documents/{id}/review`.
- Render the parsed Value Line total return block for document `1453`.
- Preserve existing projections and annual financials behavior.

## Scope
**In**
- Document review frontend card/model logic for total return.
- Focused frontend tests.
- Browser verification on `http://localhost:3001/documents/1453/review`.

**Out**
- Parser changes unless the total return payload is missing.
- Database schema or normalization changes.
- PRD changes.

## Files To Change
- `docs/tasks/2026-04-26_review-total-return-card.md`
- `backend/app/api/v1/endpoints/documents.py`
- `backend/tests/unit/test_documents_api.py`
- `frontend/lib/documentReview.js`
- `frontend/lib/documentReview.test.js`
- `frontend/app/(dashboard)/documents/[id]/review/page.tsx`

## Test Plan
- `docker compose exec api pytest -q tests/unit/test_documents_api.py::test_document_review_endpoint_returns_total_return_block`
- `docker compose exec web node --test lib/documentReview.test.js`
- Browser check on `/documents/1453/review`.

## Progress Log
- [x] Create task log.
- [x] Inspect document `1453` review payload for total return data.
- [x] Add focused backend/frontend tests.
- [x] Implement backend payload and frontend card rendering.
- [x] Run Docker verification.
- [x] Verify in browser.

## Notes / Decisions / Gotchas
- `% TOT. RETURN` should be inserted directly after `PROJECTIONS`.
- The total return block is sourced from the Value Line `price_semantics_and_returns` extraction and rendered as snapshot display data, not as screener/formula facts.

## Verification Results
- `docker compose exec api pytest -q tests/unit/test_documents_api.py::test_document_review_endpoint_returns_total_return_block` passed.
- `docker compose exec web node --test lib/documentReview.test.js` passed: 18 tests passed.
- Browser check on `http://localhost:3001/documents/1453/review` confirmed one `% TOT. RETURN` card, ordered after `PROJECTIONS` and before `Institutional Decisions`.
