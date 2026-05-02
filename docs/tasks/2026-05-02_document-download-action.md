# Document Download Action

## Goal / Acceptance Criteria
- Add a `Download` action to the end of each row on the `/documents` page.
- Clicking `Download` opens a folder picker in supported browsers.
- After the user confirms a folder, the selected document's original PDF report is saved into that folder.
- Download access is limited to documents owned by the authenticated user.

## Scope
- In:
  - Add an authenticated backend endpoint that streams the stored PDF for one document.
  - Add frontend download handling for `/documents` rows using the browser File System Access API.
  - Add focused tests for backend ownership and file streaming behavior.
- Out:
  - Bulk downloads.
  - Non-browser/native desktop folder picker integration.
  - Changing document ingestion or parser behavior.

## Files to Change
- `backend/app/api/v1/endpoints/documents.py`
- `backend/tests/unit/test_documents_api.py`
- `frontend/app/(dashboard)/documents/page.tsx`
- `frontend/lib/documentDownload.js`
- `frontend/lib/documentDownload.test.js`

## Test Plan
- `docker compose exec api pytest -q tests/unit/test_documents_api.py`
- If frontend dependencies are available in the container, run the relevant frontend test/lint command.

## Notes
- Browser folder saving depends on `window.showDirectoryPicker`; unsupported browsers should show a clear toast.
- Added `GET /api/v1/documents/{document_id}/download` to stream the owned stored PDF as an attachment.
- The page chooses the target folder before fetching the PDF so canceled selections do not trigger a backend download.
- Production download 404 can happen when the API container loses `/code/storage/uploads`; production compose must persist that directory.
- Download requests use `responseType: blob`, so frontend error handling must parse JSON error blobs to show backend details.

## Verification
- Red check observed before implementation: `docker compose exec api pytest -q tests/unit/test_documents_api.py -q` failed on missing download route.
- Passed: `docker compose exec api pytest -q tests/unit/test_documents_api.py -q`
- Passed: `docker compose exec web node --test lib/documentDownload.test.js`
- Passed: `docker compose exec web npm run lint`
- Partial: `docker compose exec web npm run build` compiled successfully and passed type checks, then failed while prerendering existing route `/watchlist/f-score-compare` with `Cannot read properties of null (reading 'useState')`.
- Follow-up passed: `docker compose exec web node --test lib/documentDownload.test.js`
- Follow-up passed: `docker compose exec web npm run lint`
- Follow-up passed: `docker compose exec api pytest -q tests/unit/test_documents_api.py -q`

## Follow-up: Production 404
- `https://invest.richmom.vip/documents` showed `Request failed with status code 404` for `/api/v1/documents/39/download`.
- Likely root cause for existing deployed documents: production API did not persist `/code/storage/uploads`, so original uploaded PDFs can disappear after API container replacement.
- Added production compose mount `./storage/uploads:/code/storage/uploads` for future uploads.
- Added frontend parsing for JSON error blobs returned from download requests, so future 404s can show `Stored document file not found` instead of a generic Axios status.
- Existing rows whose original PDF files are already missing on the server will need the original PDFs restored into `/code/storage/uploads` or re-uploaded/re-ingested.

## Contract Gate
- Screeners unchanged; they still do not query document download output.
- `metric_facts` and `value_numeric` semantics unchanged.
- No raw SQL from user input added.
- No formula `eval`/`exec` behavior touched.
- Parser lineage fields and `is_current` semantics unchanged.
