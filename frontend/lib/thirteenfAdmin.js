function formatPercent(value, digits = 0) {
  if (typeof value !== 'number') return '—';
  return `${(value * 100).toFixed(digits)}%`;
}

function readinessTone(level) {
  if (level === 'ready') return 'success';
  if (level === 'usable_with_warning') return 'warning';
  if (level === 'experimental') return 'warning';
  return 'secondary';
}

function healthTone(health) {
  if (health === 'complete') return 'success';
  if (health === 'failed' || health === 'needs_review' || health === 'setup_required') return 'danger';
  if (health === 'warning' || health === 'partial' || health === 'stale' || health === 'index_fetched' || health === 'running') return 'warning';
  return 'secondary';
}

function priorityTone(priority) {
  if (priority === 'P0' || priority === 'P1') return 'danger';
  if (priority === 'P2') return 'warning';
  return 'secondary';
}

function normalizeReadiness(payload) {
  const data = payload && typeof payload === 'object' ? payload : {};
  const currentQuarter = data.current_quarter && typeof data.current_quarter === 'object'
    ? data.current_quarter
    : {};
  return {
    readinessLevel: data.readiness_level ?? 'unavailable',
    readinessTone: readinessTone(data.readiness_level),
    frontendBehavior: data.frontend_behavior ?? 'show_setup_required',
    latestUsableQuarter: data.latest_usable_quarter ?? '—',
    currentQuarter: currentQuarter.quarter ?? '—',
    currentPhase: currentQuarter.phase ?? 'unknown',
    currentHealth: currentQuarter.health ?? 'unknown',
    filingDeadline: currentQuarter.filing_deadline ?? null,
    amendmentStatus: data.amendment_status ?? 'unknown',
    historicalDepth: Number(data.historical_depth_quarters ?? 0),
    capabilities: Array.isArray(data.historical_depth_capabilities)
      ? data.historical_depth_capabilities
      : [],
    setupChecklist: Array.isArray(data.setup_checklist)
      ? data.setup_checklist.map((item) => ({
          code: item.code,
          label: item.label ?? item.code,
          status: item.status ?? 'blocked',
          statusTone: item.status === 'complete' ? 'success' : item.status === 'warning' ? 'warning' : 'danger',
          completeWhen: item.complete_when ?? '',
          adminAction: item.admin_action ?? '',
        }))
      : [],
    warnings: Array.isArray(data.warnings) ? data.warnings : [],
    blockers: Array.isArray(data.blockers) ? data.blockers : [],
    counts: data.counts && typeof data.counts === 'object' ? data.counts : {},
    topTask: data.top_task && typeof data.top_task === 'object' ? data.top_task : null,
    schedulerEnabled: Boolean(data.scheduler_enabled),
    smartRetryEnabled: Boolean(data.smart_retry_enabled),
  };
}

function normalizeQuarters(items) {
  return (Array.isArray(items) ? items : []).map((item) => ({
    quarter: item.quarter,
    phase: item.quarter_phase,
    health: item.quarter_health,
    healthTone: healthTone(item.quarter_health),
    deadline: item.filing_deadline,
    filedManagers: item.filed_managers ?? 0,
    trackedManagers: item.tracked_managers ?? 0,
    holdingsCount: item.holdings_count ?? 0,
    linkedRatio: item.linked_holding_ratio,
    linkedUnavailableReason: item.linked_holding_unavailable_reason ?? null,
    amendmentStatus: item.amendment_status ?? 'unknown',
    failedFilings: item.failed_filings ?? 0,
    activeJobId: item.active_job_id ?? null,
    activeJobType: item.active_job_type ?? null,
  }));
}

function normalizeTasks(items) {
  return (Array.isArray(items) ? items : []).map((item) => ({
    priority: item.priority ?? 'P3',
    priorityTone: priorityTone(item.priority),
    code: item.code,
    title: item.title ?? item.problem ?? 'Task',
    evidence: item.evidence ?? '',
    recommendedAction: item.recommended_action ?? '',
    whyItMatters: item.why_it_matters ?? '',
    metadata: item.metadata && typeof item.metadata === 'object' ? item.metadata : null,
  }));
}

function normalizeWorkers(items) {
  return (Array.isArray(items) ? items : []).map((item) => ({
    workerId: item.worker_id ?? '—',
    workerType: item.worker_type ?? '13f_admin',
    hostname: item.hostname ?? '—',
    processId: item.process_id ?? null,
    status: item.status ?? 'unknown',
    statusTone: healthTone(item.status),
    currentJobId: item.current_job_id ?? null,
    lastHeartbeatAt: item.last_heartbeat_at ?? null,
    startedAt: item.started_at ?? null,
  }));
}

function operationsHealth(readiness, tasks, hasAvailableWorker, options = {}) {
  const checklist = Array.isArray(readiness?.setupChecklist) ? readiness.setupChecklist : [];
  const taskItems = Array.isArray(tasks) ? tasks : [];
  const workersIndeterminate = Boolean(options.workersIndeterminate);
  const blockedSetupCount = checklist.filter((item) => item.status === 'blocked').length;
  const warningSetupCount = checklist.filter((item) => item.status === 'warning').length;
  const p0Count = taskItems.filter((item) => item.priority === 'P0').length;
  const p1Count = taskItems.filter((item) => item.priority === 'P1').length;
  const reasons = [];

  if (blockedSetupCount > 0) {
    reasons.push(`${blockedSetupCount} blocked setup item${blockedSetupCount === 1 ? '' : 's'}`);
  }
  if (warningSetupCount > 0) {
    reasons.push(`${warningSetupCount} warning setup item${warningSetupCount === 1 ? '' : 's'}`);
  }
  if (p0Count > 0) {
    reasons.push(`${p0Count} P0 task${p0Count === 1 ? '' : 's'}`);
  }
  if (p1Count > 0) {
    reasons.push(`${p1Count} P1 task${p1Count === 1 ? '' : 's'}`);
  }
  if (workersIndeterminate) {
    reasons.push('worker heartbeat unavailable');
  } else if (!hasAvailableWorker) {
    reasons.push('no active worker heartbeat');
  }

  if (
    blockedSetupCount === 0 &&
    warningSetupCount === 0 &&
    p0Count === 0 &&
    p1Count === 0 &&
    taskItems.length === 0 &&
    workersIndeterminate
  ) {
    return {
      level: 'unknown',
      tone: 'secondary',
      label: 'operations unknown',
      summary: 'Worker heartbeat unavailable; refresh or inspect the workers API.',
      reasons,
    };
  }

  if (blockedSetupCount > 0 || p0Count > 0 || (!hasAvailableWorker && !workersIndeterminate)) {
    return {
      level: 'blocked',
      tone: 'danger',
      label: 'operations blocked',
      summary: reasons.join(', '),
      reasons,
    };
  }
  if (warningSetupCount > 0 || p1Count > 0 || taskItems.length > 0) {
    const warningReasons = reasons.length > 0
      ? reasons
      : [`${taskItems.length} task${taskItems.length === 1 ? '' : 's'} pending`];
    return {
      level: 'attention',
      tone: 'warning',
      label: 'needs attention',
      summary: warningReasons.join(', '),
      reasons: warningReasons,
    };
  }
  return {
    level: 'healthy',
    tone: 'success',
    label: 'operations healthy',
    summary: 'No operational blockers detected.',
    reasons: [],
  };
}

function visibleWorkerRows(workers, showHistory, limit = 12) {
  const items = Array.isArray(workers) ? workers : [];
  const sorted = [...items].sort((left, right) =>
    String(right.lastHeartbeatAt ?? '').localeCompare(String(left.lastHeartbeatAt ?? ''))
  );
  const stoppedCount = sorted.filter((worker) => worker.status === 'stopped').length;
  if (showHistory) {
    const rows = sorted.slice(0, limit);
    return {
      rows,
      hiddenCount: Math.max(sorted.length - rows.length, 0),
      stoppedHiddenCount: Math.max(stoppedCount - rows.filter((worker) => worker.status === 'stopped').length, 0),
      overflowHiddenCount: Math.max(sorted.length - rows.length, 0),
    };
  }
  const nonStopped = sorted.filter((worker) => worker.status !== 'stopped');
  const rows = nonStopped.slice(0, limit);
  if (rows.length > 0) {
    const overflowHiddenCount = Math.max(nonStopped.length - rows.length, 0);
    return {
      rows,
      hiddenCount: stoppedCount + overflowHiddenCount,
      stoppedHiddenCount: stoppedCount,
      overflowHiddenCount,
    };
  }
  const fallbackRows = sorted.slice(0, Math.min(3, limit));
  return {
    rows: fallbackRows,
    hiddenCount: Math.max(sorted.length - fallbackRows.length, 0),
    stoppedHiddenCount: Math.max(stoppedCount - fallbackRows.length, 0),
    overflowHiddenCount: 0,
  };
}

function normalizeQualityReports(items) {
  return (Array.isArray(items) ? items : []).map((item) => ({
    id: item.id,
    quarter: item.quarter ?? '—',
    status: item.status ?? 'not_checked',
    statusTone: healthTone(item.status),
    errorCount: item.error_count ?? null,
    warningCount: item.warning_count ?? null,
    infoCount: item.info_count ?? null,
    summary: item.summary ?? '',
    checkedAt: item.checked_at ?? null,
    sourceJobId: item.source_job_id ?? null,
    issues: Array.isArray(item.issues) ? item.issues : [],
  }));
}

function amendmentTone(status) {
  if (status === 'applied') return 'success';
  if (status === 'pending') return 'warning';
  if (status === 'failed') return 'danger';
  return 'secondary';
}

function normalizeAmendments(items) {
  return (Array.isArray(items) ? items : []).map((item) => {
    const manager = item.manager && typeof item.manager === 'object' ? item.manager : {};
    const rawInfotable =
      item.raw_infotable && typeof item.raw_infotable === 'object' ? item.raw_infotable : {};
    const rawPrimary =
      item.raw_primary && typeof item.raw_primary === 'object' ? item.raw_primary : {};
    return {
      id: item.id,
      accessionNo: item.accession_no ?? '—',
      formType: item.form_type ?? '—',
      status: item.status ?? 'unknown',
      statusTone: amendmentTone(item.status),
      managerName: manager.display_name ?? manager.legal_name ?? '—',
      managerCik: manager.cik ?? '—',
      quarter: item.quarter ?? '—',
      filedAt: item.filed_at ?? null,
      supersedesAccessionNo: item.supersedes_accession_no ?? null,
      latestEffectiveAccessionNo: item.latest_effective_accession_no ?? null,
      holdingsCount: item.holdings_count ?? 0,
      rawPrimary,
      rawInfotable,
      recommendedJob: item.recommended_job && typeof item.recommended_job === 'object'
        ? item.recommended_job
        : null,
    };
  });
}

function normalizeCikReviewEvents(items) {
  return (Array.isArray(items) ? items : []).map((item) => ({
    id: item.id,
    managerId: item.manager_id,
    eventType: item.event_type ?? 'unknown',
    oldCik: item.old_cik ?? null,
    newCik: item.new_cik ?? null,
    oldMatchStatus: item.old_match_status ?? null,
    newMatchStatus: item.new_match_status ?? null,
    note: item.note ?? '',
    affectedFilingsCount: item.affected_filings_count ?? 0,
    affectedQuarters: Array.isArray(item.affected_quarters) ? item.affected_quarters : [],
    requiresDownstreamReview: Boolean(item.requires_downstream_review),
    createdAt: item.created_at ?? null,
  }));
}

function freshnessLine(readiness) {
  const deadline = readiness.filingDeadline ? ` Filing deadline: ${readiness.filingDeadline}.` : '';
  return `Default data period: ${readiness.latestUsableQuarter}. Current quarter: ${readiness.currentQuarter} (${readiness.currentPhase}).${deadline} Amendment status: ${readiness.amendmentStatus}.`;
}

function jobPreviewLine(preview) {
  if (!preview || typeof preview !== 'object') return 'No preview available.';
  const scope = preview.estimated_scope && typeof preview.estimated_scope === 'object'
    ? preview.estimated_scope
    : {};
  const parts = [
    `Lock: ${preview.lock_key ?? '—'}`,
    preview.target_quarter ? `Quarter: ${preview.target_quarter}` : null,
    preview.accession_no ? `Accession: ${preview.accession_no}` : null,
    'tracked_managers' in scope ? `Tracked managers: ${scope.tracked_managers}` : null,
    'filings_in_quarter' in scope ? `Filings in quarter: ${scope.filings_in_quarter}` : null,
    'pending_filings' in scope ? `Pending filings: ${scope.pending_filings}` : null,
    'failed_filings' in scope ? `Failed filings: ${scope.failed_filings}` : null,
    preview.rate_limit_warning ? `Warning: ${preview.rate_limit_warning}` : null,
  ].filter(Boolean);
  return parts.join('\n');
}

function jobPreviewRows(preview) {
  const data = preview && typeof preview === 'object' ? preview : {};
  const scope = data.estimated_scope && typeof data.estimated_scope === 'object'
    ? data.estimated_scope
    : {};
  return [
    ['Lock key', data.lock_key],
    ['Target quarter', data.target_quarter],
    ['Accession', data.accession_no],
    ['Tracked managers', scope.tracked_managers],
    ['Filings in quarter', scope.filings_in_quarter],
    ['Pending filings', scope.pending_filings],
    ['Failed filings', scope.failed_filings],
    ['Start quarter', scope.start_quarter],
    ['Quarters', scope.quarters],
    ['Filing exists', scope.filing_exists],
  ]
    .filter(([, value]) => value !== undefined && value !== null)
    .map(([label, value]) => ({ label, value }));
}

function taskPrimaryAction(task, latestQuarter) {
  if (!task || typeof task !== 'object') return null;
  const quarter = task.metadata?.quarter || latestQuarter;
  const code = task.code;
  if (code === 'EDGAR_SCHEDULER_DISABLED') {
    return { label: 'Config change required', kind: 'manual' };
  }
  if (code === 'NO_CONFIRMED_MANAGER_CIK_WHITELIST') {
    return { label: 'Bootstrap whitelist', payload: { job_type: 'bootstrap_whitelist' }, kind: 'job' };
  }
  if (code === 'CIK_CANDIDATES_NEED_REVIEW') {
    return { label: 'Review managers', kind: 'anchor', target: 'managers' };
  }
  if ((code === 'QUALITY_ERRORS' || code === 'QUALITY_WARNINGS') && quarter) {
    return { label: 'Run quality check', payload: { job_type: 'quality_check', quarter }, kind: 'job' };
  }
  if (code === 'LOW_STOCK_LINK_COVERAGE' && quarter) {
    return { label: 'Run CUSIP enrichment', payload: { job_type: 'enrich_metadata', quarter }, kind: 'job' };
  }
  if (code === 'HISTORICAL_COVERAGE_BELOW_TARGET' || code === 'EXTENDED_BACKFILL_RECOMMENDED') {
    return { label: 'Backfill quarters', payload: { job_type: 'backfill_quarters', quarters: 4 }, kind: 'job' };
  }
  if (code === 'FILING_PARSE_FAILURES' && quarter) {
    return { label: 'Retry holdings ingest', payload: { job_type: 'ingest_holdings', quarter }, kind: 'job' };
  }
  return null;
}

function managerCikReviewDefaults(manager) {
  const data = manager && typeof manager === 'object' ? manager : {};
  const managerName = data.legal_name || data.display_name || 'this manager';
  const candidateName = data.candidate_legal_name || managerName;
  const defaultCik = data.candidate_cik || data.cik || '';
  return {
    managerName,
    candidateName,
    defaultCik,
    confirmDescription: `Confirm the SEC CIK for ${managerName}. This manager will be eligible for 13F ingestion using the confirmed identity.`,
    rejectDescription: `Reject this CIK candidate for ${managerName}. The manager will remain unresolved until a new candidate is reviewed.`,
  };
}

module.exports = {
  formatPercent,
  freshnessLine,
  jobPreviewRows,
  managerCikReviewDefaults,
  jobPreviewLine,
  normalizeAmendments,
  normalizeCikReviewEvents,
  healthTone,
  normalizeQuarters,
  normalizeQualityReports,
  normalizeReadiness,
  normalizeTasks,
  normalizeWorkers,
  operationsHealth,
  priorityTone,
  readinessTone,
  taskPrimaryAction,
  visibleWorkerRows,
};
