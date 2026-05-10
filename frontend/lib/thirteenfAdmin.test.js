/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  freshnessLine,
  jobPreviewRows,
  managerCikReviewDefaults,
  jobPreviewLine,
  normalizeAmendments,
  normalizeCikReviewEvents,
  normalizeEdgarRateLimit,
  normalizeAdminFilings,
  normalizeHoldingsCoverage,
  normalizeParseRuns,
  normalizeQualityReports,
  normalizeQuarters,
  normalizeReadiness,
  normalizeTasks,
  normalizeUnresolvedCusips,
  normalizeWorkers,
  operationsHealth,
  prioritizeManagersForReview,
  taskPrimaryAction,
  visibleWorkerRows,
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
    scheduler_enabled: true,
    smart_retry_enabled: true,
  });

  assert.equal(readiness.latestUsableQuarter, '2025-Q4');
  assert.equal(readiness.currentQuarter, '2026-Q1');
  assert.equal(readiness.historicalDepth, 4);
  assert.equal(readiness.schedulerEnabled, true);
  assert.equal(readiness.smartRetryEnabled, true);
  assert.deepEqual(readiness.setupChecklist, []);
  assert.match(freshnessLine(readiness), /Default data period: 2025-Q4/);
  assert.match(freshnessLine(readiness), /Amendment status: amendments_applied/);
});

test('normalizeEdgarRateLimit computes usage tone and capacity fields', () => {
  const status = normalizeEdgarRateLimit({
    mode: 'live',
    request_delay_s: 0.2,
    max_retries: 3,
    window_seconds: 60,
    recent_request_count: 240,
    estimated_capacity: 300,
    remaining_estimated_capacity: 60,
    global_pause_until: null,
  });

  assert.equal(status.mode, 'live');
  assert.equal(status.recentRequestCount, 240);
  assert.equal(status.remainingEstimatedCapacity, 60);
  assert.equal(status.usageRatio, 0.8);
  assert.equal(status.tone, 'warning');
});

test('normalizeReadiness maps setup checklist states', () => {
  const readiness = normalizeReadiness({
    setup_checklist: [
      {
        code: 'SCHEDULER_CONFIGURED',
        label: 'Scheduler configured',
        status: 'complete',
        complete_when: 'scheduler enabled',
        admin_action: 'Enable scheduler',
      },
      {
        code: 'HOLDINGS_INGESTED',
        label: 'Holdings ingested',
        status: 'blocked',
        complete_when: 'holdings exist',
        admin_action: 'Ingest holdings',
      },
    ],
  });

  assert.equal(readiness.setupChecklist[0].statusTone, 'success');
  assert.equal(readiness.setupChecklist[1].statusTone, 'danger');
  assert.equal(readiness.setupChecklist[1].adminAction, 'Ingest holdings');
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

test('jobPreviewLine summarizes dry-run preview for confirmation', () => {
  const line = jobPreviewLine({
    lock_key: 'ingest_holdings:2025-Q4',
    target_quarter: '2025-Q4',
    rate_limit_warning: 'Respect SEC rate limits.',
    estimated_scope: {
      tracked_managers: 3,
      filings_in_quarter: 8,
      pending_filings: 5,
      failed_filings: 1,
    },
  });

  assert.match(line, /Lock: ingest_holdings:2025-Q4/);
  assert.match(line, /Pending filings: 5/);
  assert.match(line, /Respect SEC rate limits/);
});

test('jobPreviewRows keeps zero and false dry-run scope values', () => {
  const rows = jobPreviewRows({
    lock_key: 'ingest_accession:0001',
    accession_no: '0001',
    estimated_scope: {
      pending_filings: 0,
      failed_filings: 0,
      filing_exists: false,
    },
  });

  assert.deepEqual(
    rows.map((row) => row.label),
    ['Lock key', 'Accession', 'Pending filings', 'Failed filings', 'Filing exists']
  );
  assert.equal(rows.find((row) => row.label === 'Filing exists').value, false);
});

test('operationsHealth separates data readiness from operational blockers', () => {
  const readiness = normalizeReadiness({
    readiness_level: 'ready',
    setup_checklist: [
      {
        code: 'SCHEDULER_CONFIGURED',
        label: 'Scheduler configured',
        status: 'blocked',
        admin_action: 'Enable scheduler',
      },
    ],
  });
  const health = operationsHealth(readiness, normalizeTasks([
    { priority: 'P0', code: 'EDGAR_SCHEDULER_DISABLED', title: 'Scheduler disabled' },
  ]), true);

  assert.equal(readiness.readinessLevel, 'ready');
  assert.equal(health.level, 'blocked');
  assert.equal(health.tone, 'danger');
  assert.match(health.summary, /1 blocked setup item/);
});

test('operationsHealth treats worker API errors as indeterminate', () => {
  const readiness = normalizeReadiness({
    readiness_level: 'ready',
    setup_checklist: [],
  });
  const health = operationsHealth(readiness, [], false, { workersIndeterminate: true });

  assert.equal(health.level, 'unknown');
  assert.equal(health.tone, 'secondary');
  assert.match(health.summary, /Worker heartbeat unavailable/);
});

test('operationsHealth preserves P1 tasks when workers are indeterminate', () => {
  const readiness = normalizeReadiness({
    readiness_level: 'ready',
    setup_checklist: [],
  });
  const health = operationsHealth(
    readiness,
    normalizeTasks([{ priority: 'P1', code: 'FILING_PARSE_FAILURES', title: 'Parse failures' }]),
    false,
    { workersIndeterminate: true }
  );

  assert.equal(health.level, 'attention');
  assert.equal(health.tone, 'warning');
  assert.match(health.summary, /1 P1 task/);
  assert.match(health.summary, /worker heartbeat unavailable/);
});

test('operationsHealth preserves warning setup when workers are indeterminate', () => {
  const readiness = normalizeReadiness({
    readiness_level: 'ready',
    setup_checklist: [
      {
        code: 'QUALITY_CHECKED',
        label: 'Quality checked',
        status: 'warning',
      },
    ],
  });
  const health = operationsHealth(readiness, [], false, { workersIndeterminate: true });

  assert.equal(health.level, 'attention');
  assert.equal(health.tone, 'warning');
  assert.match(health.summary, /1 warning setup item/);
});

test('visibleWorkerRows hides stopped worker history by default', () => {
  const workers = normalizeWorkers([
    { worker_id: 'idle-1', status: 'idle', last_heartbeat_at: '2026-05-08T02:00:00Z' },
    { worker_id: 'stale-1', status: 'stale', last_heartbeat_at: '2026-05-08T01:00:00Z' },
    { worker_id: 'stopped-1', status: 'stopped', last_heartbeat_at: '2026-05-07T22:00:00Z' },
  ]);

  const collapsed = visibleWorkerRows(workers, false);
  assert.deepEqual(collapsed.rows.map((worker) => worker.workerId), ['idle-1', 'stale-1']);
  assert.equal(collapsed.hiddenCount, 1);
  assert.equal(collapsed.stoppedHiddenCount, 1);
  assert.equal(collapsed.overflowHiddenCount, 0);

  const expanded = visibleWorkerRows(workers, true);
  assert.deepEqual(expanded.rows.map((worker) => worker.workerId), ['idle-1', 'stale-1', 'stopped-1']);
  assert.equal(expanded.hiddenCount, 0);
});

test('visibleWorkerRows separates stopped history from limit overflow', () => {
  const workers = normalizeWorkers([
    ...Array.from({ length: 13 }, (_, index) => ({
      worker_id: `idle-${index}`,
      status: 'idle',
      last_heartbeat_at: `2026-05-08T02:${String(index).padStart(2, '0')}:00Z`,
    })),
    { worker_id: 'stopped-1', status: 'stopped', last_heartbeat_at: '2026-05-07T22:00:00Z' },
    { worker_id: 'stopped-2', status: 'stopped', last_heartbeat_at: '2026-05-07T21:00:00Z' },
  ]);

  const collapsed = visibleWorkerRows(workers, false, 12);

  assert.equal(collapsed.rows.length, 12);
  assert.equal(collapsed.hiddenCount, 3);
  assert.equal(collapsed.stoppedHiddenCount, 2);
  assert.equal(collapsed.overflowHiddenCount, 1);
});

test('taskPrimaryAction maps safe admin tasks to concrete operations', () => {
  assert.deepEqual(
    taskPrimaryAction(
      normalizeTasks([{ code: 'QUALITY_ERRORS', title: 'Quality errors' }])[0],
      '2025-Q4'
    ),
    {
      label: 'Run quality check',
      payload: { job_type: 'quality_check', quarter: '2025-Q4' },
      kind: 'job',
    }
  );

  assert.deepEqual(
    taskPrimaryAction(
      normalizeTasks([{ code: 'EDGAR_SCHEDULER_DISABLED', title: 'Scheduler disabled' }])[0],
      '2025-Q4'
    ),
    {
      label: 'Config change required',
      kind: 'manual',
    }
  );
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

test('normalizeAdminFilings exposes caveat-driving fields without inferring from form type alone', () => {
  const filings = normalizeAdminFilings({
    items: [
      {
        id: 1,
        accession_number: '0001234567-26-000001',
        form_type: '13F-HR/A',
        report_type: 'combination_report',
        coverage_completeness: 'partial',
        coverage_type: 'combination_partial',
        has_confidential_treatment: true,
        confidential_treatment_status: 'applied',
        amendment_status: 'amendments_pending',
        amendment_type: 'RESTATEMENT',
        parse_status: 'needs_review',
        official_filing_deadline: '2026-05-15',
        report_quarter: '2026-Q1',
        manager: { display_name: 'Admin Manager', cik: '0001234567' },
        holdings_count: 0,
      },
      {
        id: 2,
        accession_number: '0001234567-26-000002',
        form_type: '13F-NT',
        report_type: 'notice_report',
        coverage_type: 'notice_reported_elsewhere',
        coverage_completeness: 'unknown',
        parse_status: 'succeeded',
        manager: { legal_name: 'Notice Manager' },
      },
    ],
    total: 2,
    page: 1,
    page_size: 50,
  });

  assert.equal(filings.total, 2);
  assert.equal(filings.pageSize, 50);
  assert.equal(filings.items[0].managerName, 'Admin Manager');
  assert.equal(filings.items[0].statusTone, 'danger');
  assert.deepEqual(filings.items[0].caveatCodes, [
    'COMBINATION_REPORT',
    'CONFIDENTIAL_TREATMENT',
    'AMENDMENTS_PENDING',
  ]);
  assert.equal(filings.items[0].holdingsCountLabel, '0');
  assert.deepEqual(filings.items[1].caveatCodes, ['NOTICE_REPORTED_ELSEWHERE']);
});

test('normalizeParseRuns preserves pagination and current audit marker', () => {
  const runs = normalizeParseRuns({
    accession_number: '0001234567-26-000001',
    items: [
      { id: 10, parser_version: 'v2', status: 'succeeded', is_current: true, holdings_count: 12 },
      { id: 9, parser_version: 'v1', status: 'failed', is_current: false, error: 'bad XML' },
    ],
    total: 2,
    page: 1,
    page_size: 50,
  });

  assert.equal(runs.accessionNumber, '0001234567-26-000001');
  assert.equal(runs.total, 2);
  assert.equal(runs.items[0].isCurrent, true);
  assert.equal(runs.items[0].statusTone, 'success');
  assert.equal(runs.items[1].statusTone, 'danger');
});

test('normalizeHoldingsCoverage keeps unavailable ratios distinct from zero', () => {
  const empty = normalizeHoldingsCoverage({
    report_quarter: '2026-Q1',
    common_holdings_count: 0,
    linked_common_holding_ratio: null,
  });
  const populated = normalizeHoldingsCoverage({
    report_quarter: '2026-Q1',
    total_holdings_count: 3,
    common_holdings_count: 2,
    linked_common_holdings_count: 1,
    unresolved_common_holdings_count: 1,
    options_count: 1,
    linked_common_holding_ratio: 0.5,
  });

  assert.equal(empty.linkedCommonHoldingRatioLabel, '—');
  assert.equal(empty.commonHoldingsCount, 0);
  assert.equal(populated.linkedCommonHoldingRatioLabel, '50%');
  assert.equal(populated.optionsCount, 1);
});

test('normalizeUnresolvedCusips maps current unresolved groups for admin review', () => {
  const unresolved = normalizeUnresolvedCusips({
    items: [
      {
        cusip: '000000007',
        cusip_mapping_status: 'unresolved',
        issuer_name: 'Issuer 7',
        holding_count: 2,
      },
    ],
    total: 1,
    page: 1,
    page_size: 50,
  });

  assert.equal(unresolved.total, 1);
  assert.equal(unresolved.items[0].cusip, '000000007');
  assert.equal(unresolved.items[0].statusTone, 'warning');
  assert.equal(unresolved.items[0].holdingCount, 2);
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

test('managerCikReviewDefaults prepares confirm and reject dialog copy', () => {
  const defaults = managerCikReviewDefaults({
    legal_name: 'Test Manager',
    candidate_cik: '0001234567',
    cik: '0007654321',
    candidate_legal_name: 'Test Manager LP',
  });

  assert.equal(defaults.managerName, 'Test Manager');
  assert.equal(defaults.defaultCik, '0001234567');
  assert.match(defaults.confirmDescription, /Confirm the SEC CIK/);
  assert.match(defaults.rejectDescription, /Reject this CIK candidate/);
});

test('prioritizeManagersForReview surfaces actionable CIK review rows first', () => {
  const managers = [
    { id: 1, legal_name: 'Alpha Confirmed', match_status: 'confirmed', cik: '0000000001' },
    { id: 2, legal_name: 'QA Pending CIK Manager', match_status: 'candidate', candidate_cik: '0001336528' },
    { id: 3, legal_name: 'Beta Seeded', match_status: 'seeded' },
    { id: 4, legal_name: 'Gamma Revoked', match_status: 'revoked', cik: null },
    { id: 5, legal_name: 'Delta Rejected', match_status: 'rejected' },
  ];

  const rows = prioritizeManagersForReview(managers);

  assert.deepEqual(
    rows.map((manager) => manager.legal_name),
    ['QA Pending CIK Manager', 'Beta Seeded', 'Gamma Revoked', 'Delta Rejected', 'Alpha Confirmed']
  );
  assert.equal(managers[0].legal_name, 'Alpha Confirmed');
});
