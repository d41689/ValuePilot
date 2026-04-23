/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  formatActiveReportTickers,
  getActiveReportBadgeLabel,
} = require('./documentActiveReport');

test('formatActiveReportTickers summarizes active ticker coverage', () => {
  assert.equal(formatActiveReportTickers([]), 'Not active for any company');
  assert.equal(formatActiveReportTickers(['FICO']), 'Active for FICO');
  assert.equal(formatActiveReportTickers(['AOS', 'MSFT']), 'Active for AOS, MSFT');
  assert.equal(
    formatActiveReportTickers(['AOS', 'MSFT', 'FICO', 'GOOG']),
    'Active for AOS, MSFT, FICO (+1)'
  );
});

test('getActiveReportBadgeLabel maps active state to compact badge text', () => {
  assert.equal(getActiveReportBadgeLabel(true), 'Active Report');
  assert.equal(getActiveReportBadgeLabel(false), 'Historical');
});
