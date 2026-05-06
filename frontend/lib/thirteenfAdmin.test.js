/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  freshnessLine,
  normalizeQuarters,
  normalizeReadiness,
  normalizeTasks,
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
    { priority: 'P1', code: 'AMENDMENT_PENDING_OR_FAILED', title: 'Amendment pending or failed' },
  ]);

  assert.equal(quarters[0].healthTone, 'danger');
  assert.equal(tasks[0].priorityTone, 'danger');
});
