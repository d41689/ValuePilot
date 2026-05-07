/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  freshnessLine,
  normalizeAmendments,
  normalizeCikReviewEvents,
  normalizeQualityReports,
  normalizeQuarters,
  normalizeReadiness,
  normalizeTasks,
  normalizeWorkers,
  readinessTone,
} = require('./thirteenfAdmin');

test('readinessTone maps readiness levels to badge variants', () => {
  assert.equal(readinessTone('ready'), 'success');
  assert.equal(readinessTone('usable_with_warning'), 'warning');
  assert.equal(readinessTone('experimental'), 'warning');
  assert.equal(readinessTone('unavailable'), 'secondary');
});

test('normalizeReadiness preserves consumer-visible freshness fields', () => {
  const readiness = normalizeReadiness({
    readiness_level: 'usable_with_warning',
    frontend_behavior: 'show_with_warning',
    latest_usable_quarter: '2025-Q4',
    current_quarter: {
      quarter: '2026-Q1',
      phase: 'filing_window_open',
      health: 'partial',
      filing_deadline: '2026-05-15',
    },
    amendment_status: 'amendments_applied',
    historical_depth_quarters: 4,
    historical_depth_capabilities: ['position_changes', 'annual_trend'],
  });

  assert.equal(readiness.latestUsableQuarter, '2025-Q4');
  assert.equal(readiness.currentQuarter, '2026-Q1');
  assert.equal(readiness.historicalDepth, 4);
  assert.match(freshnessLine(readiness), /Default data period: 2025-Q4/);
  assert.match(freshnessLine(readiness), /Amendment status: amendments_applied/);
});

test('normalizeQuarters and normalizeTasks prepare table rows', () => {
  const quarters = normalizeQuarters([
    { quarter: '2025-Q4', quarter_health: 'needs_review', filed_managers: 3, tracked_managers: 5 },
  ]);
  const tasks = normalizeTasks([
    {
      priority: 'P1',
      code: 'REVOKED_CIK_DOWNSTREAM_REVIEW',
      title: 'Revoked CIK requires downstream review',
      metadata: { manager_name: 'Revoked Manager', affected_quarters: ['2025-Q4'] },
    },
  ]);

  assert.equal(quarters[0].healthTone, 'danger');
  assert.equal(tasks[0].priorityTone, 'danger');
  assert.equal(tasks[0].metadata.manager_name, 'Revoked Manager');
});

test('normalizeWorkers exposes heartbeat status and current job', () => {
  const workers = normalizeWorkers([
    {
      worker_id: 'worker-1',
      status: 'running',
      current_job_id: 42,
      last_heartbeat_at: '2026-05-06T12:30:00Z',
    },
  ]);

  assert.equal(workers[0].workerId, 'worker-1');
  assert.equal(workers[0].status, 'running');
  assert.equal(workers[0].currentJobId, 42);
});

test('normalizeQualityReports maps persisted report counts and status', () => {
  const reports = normalizeQualityReports([
    {
      id: 7,
      quarter: '2025-Q4',
      status: 'warning',
      error_count: 0,
      warning_count: 2,
      info_count: 4,
      checked_at: '2026-05-06T13:00:00Z',
      issues: [{ check: 'reconciliation', severity: 'warning' }],
    },
  ]);

  assert.equal(reports[0].quarter, '2025-Q4');
  assert.equal(reports[0].statusTone, 'warning');
  assert.equal(reports[0].warningCount, 2);
  assert.equal(reports[0].issues.length, 1);
});

test('normalizeAmendments maps accession status and reprocess action', () => {
  const amendments = normalizeAmendments([
    {
      id: 11,
      accession_no: '0001234567-26-000002',
      form_type: '13F-HR/A',
      status: 'failed',
      manager: { legal_name: 'Test Manager', cik: '0001234567' },
      quarter: '2025-Q4',
      supersedes_accession_no: '0001234567-26-000001',
      holdings_count: 0,
      raw_infotable: { parse_status: 'failed', error_message: 'bad XML' },
      recommended_job: {
        job_type: 'reprocess_amendment',
        accession_no: '0001234567-26-000002',
      },
    },
  ]);

  assert.equal(amendments[0].statusTone, 'danger');
  assert.equal(amendments[0].managerName, 'Test Manager');
  assert.equal(amendments[0].recommendedJob.job_type, 'reprocess_amendment');
  assert.equal(amendments[0].rawInfotable.error_message, 'bad XML');
});

test('normalizeCikReviewEvents maps revocation audit scope', () => {
  const events = normalizeCikReviewEvents([
    {
      id: 31,
      event_type: 'revoke_confirmed_cik',
      old_cik: '0001336528',
      new_cik: null,
      affected_filings_count: 4,
      affected_quarters: ['2025-Q3', '2025-Q4'],
      requires_downstream_review: true,
      note: 'Wrong SEC entity',
    },
  ]);

  assert.equal(events[0].eventType, 'revoke_confirmed_cik');
  assert.equal(events[0].oldCik, '0001336528');
  assert.equal(events[0].affectedFilingsCount, 4);
  assert.deepEqual(events[0].affectedQuarters, ['2025-Q3', '2025-Q4']);
  assert.equal(events[0].requiresDownstreamReview, true);
});
