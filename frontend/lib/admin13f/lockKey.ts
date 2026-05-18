/**
 * Shared lock-key derivation for admin job-trigger payloads.
 *
 * Pre-MVP6-08 this helper was duplicated on three routes
 * (`/admin/13f`, `/admin/13f/jobs`, `/admin/13f/readiness`). Per
 * the Staff Engineer review FLAG #8 the three copies had drifted
 * (single-line vs multi-line `if`s, mismatched return-type
 * annotations) — adding a new `job_type` required a lockstep
 * three-site edit with non-trivial drift risk. The MVP6-08
 * follow-up extracted them here.
 *
 * Keep this in sync with backend service lock-key derivation:
 *
 * - `backend/app/services/edgar/backfill_service.py`
 * - `backend/app/services/thirteenf_holdings_ingest.py`
 * - `backend/app/services/thirteenf_batch_reparse.py`
 * - `backend/app/services/edgar/index_fetcher.py`
 *
 * When adding a new admin-triggerable job, add the case here AND
 * the matching backend service. Returning `null` means the job
 * has no lock-key contract — `runJob` will dry-run and rely on
 * the backend `conflict` flag instead.
 */
export function lockKeyForPayload(
  payload: Record<string, unknown>,
): string | null {
  const jobType = String(payload.job_type ?? '');
  if (jobType === 'fetch_quarter_index')
    return `fetch_quarter_index:${String(payload.quarter ?? '')}`;
  if (jobType === 'ingest_holdings')
    return `ingest_holdings:${String(payload.quarter ?? '')}`;
  if (jobType === 'quality_check')
    return `quality_check:${String(payload.quarter ?? '')}`;
  if (jobType === 'enrich_cusip')
    return `enrich_cusip:${String(payload.quarter ?? 'global')}`;
  if (jobType === 'enrich_metadata')
    return `enrich_metadata:${String(payload.quarter ?? 'global')}`;
  if (jobType === 'ingest_accession')
    return `ingest_accession:${String(payload.accession_no ?? '')}`;
  if (jobType === 'reprocess_amendment')
    return `reprocess_amendment:${String(payload.accession_no ?? '')}`;
  if (jobType === 'backfill_quarters') {
    return `backfill_quarters:${String(payload.start_quarter ?? 'latest')}:${String(
      payload.quarters ?? '',
    )}`;
  }
  if (jobType === 'bootstrap_whitelist') return 'bootstrap_whitelist';
  if (jobType === 'match_cik') return 'match_cik';
  if (jobType === 'bootstrap_stocks') return 'bootstrap_stocks';
  if (jobType === 'enrich_stocks_edgar') return 'enrich_stocks_edgar';
  return null;
}
