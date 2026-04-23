/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildActualConflictDisplayItems,
  formatConflictValue,
} = require('./actualConflicts');

test('buildActualConflictDisplayItems summarizes latest and previous actual values', () => {
  const items = buildActualConflictDisplayItems([
    {
      metric_key: 'is.net_income',
      period_type: 'FY',
      period_end_date: '2024-12-31',
      observations: [
        {
          value_numeric: 120,
          source_report_date: '2026-04-09',
        },
        {
          value_numeric: 100,
          source_report_date: '2026-01-09',
        },
      ],
    },
  ]);

  assert.deepEqual(items, [
    {
      metricLabel: 'is / net_income',
      periodLabel: 'FY · 12/31/2024',
      latestValueLabel: '120',
      previousValueLabel: '100',
      latestReportLabel: '4/9/2026',
      previousReportLabel: '1/9/2026',
      observationCount: 2,
    },
  ]);
});

test('formatConflictValue falls back to text when numeric value is missing', () => {
  assert.equal(
    formatConflictValue({
      value_numeric: null,
      value_text: 'n/a',
    }),
    'n/a'
  );
});
