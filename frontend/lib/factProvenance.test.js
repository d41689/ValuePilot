/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  formatFactProvenanceLabel,
  formatComputedFactProvenanceLabel,
} = require('./factProvenance');

test('formatFactProvenanceLabel summarizes report-backed facts', () => {
  assert.equal(
    formatFactProvenanceLabel({
      source_type: 'parsed',
      source_document_id: 42,
      source_report_date: '2026-04-09',
      period_end_date: '2025-12-31',
      is_active_report: true,
    }),
    'Active report · 4/9/2026 · doc #42'
  );

  assert.equal(
    formatFactProvenanceLabel({
      source_type: 'parsed',
      source_document_id: null,
      source_report_date: null,
      period_end_date: '2025-12-31',
      is_active_report: false,
    }),
    'Parsed fact · period end 12/31/2025'
  );
});

test('formatComputedFactProvenanceLabel summarizes computed inputs', () => {
  assert.equal(
    formatComputedFactProvenanceLabel({
      inputs: [
        {
          metric_key: 'is.depreciation',
          source_document_id: 42,
          source_report_date: '2026-04-09',
          is_active_report: true,
        },
        {
          metric_key: 'equity.shares_outstanding',
          source_document_id: 42,
          source_report_date: '2026-04-09',
          is_active_report: true,
        },
      ],
    }),
    'Computed from active report · 4/9/2026 · doc #42'
  );

  assert.equal(formatComputedFactProvenanceLabel(null), null);
});
