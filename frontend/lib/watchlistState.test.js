/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  sortWatchlistMembers,
  buildFairValueEdits,
  formatWatchlistOptionLabel,
  hasFairValueEditChanges,
  formatPiotroskiFScoreSeries,
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

test('formatWatchlistOptionLabel includes the watchlist member count', () => {
  assert.equal(formatWatchlistOptionLabel({ name: 'Core', member_count: 3 }), 'Core · 3 stocks');
  assert.equal(formatWatchlistOptionLabel({ name: 'Ideas', member_count: 1 }), 'Ideas · 1 stock');
  assert.equal(formatWatchlistOptionLabel({ name: 'Empty' }), 'Empty · 0 stocks');
});

test('formatPiotroskiFScoreSeries formats complete and partial yearly scores', () => {
  assert.equal(
    formatPiotroskiFScoreSeries([
      { fiscal_year: 2024, score: 8, status: 'calculated', variant: 'valueline_proxy' },
      {
        fiscal_year: 2023,
        score: null,
        status: 'partial',
        variant: 'insurance_adjusted',
        partial_score: 6,
        max_available_score: 8,
      },
      { fiscal_year: 2022, score: 4, status: 'calculated', variant: 'standard' },
      { fiscal_year: 2021, score: 3, status: 'calculated', variant: 'standard' },
    ]),
    '2024: 8/9\n2023: 6/8 partial\n2022: 4/9'
  );

  assert.equal(formatPiotroskiFScoreSeries([]), '—');
});
