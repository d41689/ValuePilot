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
  if (health === 'partial' || health === 'stale' || health === 'index_fetched') return 'warning';
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
    warnings: Array.isArray(data.warnings) ? data.warnings : [],
    blockers: Array.isArray(data.blockers) ? data.blockers : [],
    counts: data.counts && typeof data.counts === 'object' ? data.counts : {},
    topTask: data.top_task && typeof data.top_task === 'object' ? data.top_task : null,
    schedulerEnabled: Boolean(data.scheduler_enabled),
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
    amendmentStatus: item.amendment_status ?? 'unknown',
    failedFilings: item.failed_filings ?? 0,
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
  }));
}

function freshnessLine(readiness) {
  const deadline = readiness.filingDeadline ? ` Filing deadline: ${readiness.filingDeadline}.` : '';
  return `Default data period: ${readiness.latestUsableQuarter}. Current quarter: ${readiness.currentQuarter} (${readiness.currentPhase}).${deadline} Amendment status: ${readiness.amendmentStatus}.`;
}

module.exports = {
  formatPercent,
  freshnessLine,
  healthTone,
  normalizeQuarters,
  normalizeReadiness,
  normalizeTasks,
  priorityTone,
  readinessTone,
};
