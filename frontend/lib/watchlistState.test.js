/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  sortWatchlistMembers,
  buildFairValueEdits,
  hasFairValueEditChanges,
} = require('./watchlistState');

test('sortWatchlistMembers orders by MOS descending and ticker ascending as tie-breaker', () => {
  const rows = [
    { ticker: 'MSFT', mos: 0.15 },
    { ticker: 'AAPL', mos: 0.4 },
    { ticker: 'AMZN', mos: 0.4 },
    { ticker: 'GOOG', mos: null },
  ];

  assert.deepEqual(
    sortWatchlistMembers(rows).map((row) => row.ticker),
    ['AAPL', 'AMZN', 'MSFT', 'GOOG']
  );
});

test('buildFairValueEdits formats current fair value strings for each stock', () => {
  const rows = [
    { stock_id: 10, fair_value: 120.5 },
    { stock_id: 11, fair_value: null },
    { stock_id: 12, fair_value: 98.4567 },
  ];

  assert.deepEqual(buildFairValueEdits(rows), {
    10: '120.50',
    11: '',
    12: '98.46',
  });
});

test('hasFairValueEditChanges detects identical and changed edit maps', () => {
  assert.equal(
    hasFairValueEditChanges(
      { 10: '120.5', 11: '' },
      { 10: '120.5', 11: '' }
    ),
    false
  );

  assert.equal(
    hasFairValueEditChanges(
      { 10: '120.5', 11: '' },
      { 10: '121', 11: '' }
    ),
    true
  );
});
