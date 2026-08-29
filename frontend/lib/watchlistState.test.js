/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  OVERVIEW_WATCHLIST_ID,
  sortWatchlistMembers,
  buildFairValueEdits,
  formatOverviewOptionLabel,
  formatWatchlistOptionLabel,
  formatRefreshPricesSuccessDescription,
  getRefreshPricesButtonPresentation,
  hasFairValueEditChanges,
  isOverviewWatchlistId,
  formatPiotroskiFScoreSeries,
  normalizeCanonicalPriceState,
  formatValuationReferenceLabel,
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

test('formatValuationReferenceLabel keeps system reference distinct from user fair value', () => {
  assert.equal(
    formatValuationReferenceLabel(80, 'target.price_18m.mid'),
    '80.00 · VL 18M target'
  );
  assert.equal(formatValuationReferenceLabel(null, null), '—');
});

test('formatValuationReferenceLabel identifies a user-corrected document reference', () => {
  assert.equal(
    formatValuationReferenceLabel(82, 'target.price_18m.mid.manual_correction'),
    '82.00 · User-corrected VL 18M target',
  );
});

test('normalizeCanonicalPriceState preserves fresh quote metadata', () => {
  assert.deepEqual(
    normalizeCanonicalPriceState({
      price: 101.25,
      price_date: '2026-08-28',
      price_currency: 'USD',
      price_source: 'stooq',
      price_freshness: 'fresh',
      price_reason: null,
    }),
    {
      valueLabel: '101.25',
      dateLabel: '2026-08-28',
      currencyLabel: 'USD',
      sourceLabel: 'stooq',
      freshnessLabel: 'Fresh',
      reasonLabel: null,
    },
  );
});

test('normalizeCanonicalPriceState exposes unavailable reason without a price', () => {
  assert.deepEqual(
    normalizeCanonicalPriceState({
      price: null,
      price_date: '2026-08-27',
      price_currency: null,
      price_source: 'stooq',
      price_freshness: 'stale',
      price_reason: 'price_currency_unknown',
    }),
    {
      valueLabel: '—',
      dateLabel: '2026-08-27',
      currencyLabel: 'Currency unknown',
      sourceLabel: 'stooq',
      freshnessLabel: 'Stale',
      reasonLabel: 'Price currency unknown',
    },
  );
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

test('overview watchlist helpers identify and label the virtual list', () => {
  assert.equal(OVERVIEW_WATCHLIST_ID, 'overview');
  assert.equal(isOverviewWatchlistId('overview'), true);
  assert.equal(isOverviewWatchlistId(12), false);
  assert.equal(formatOverviewOptionLabel(4), 'Overview · 4 stocks');
  assert.equal(formatOverviewOptionLabel(1), 'Overview · 1 stock');
  assert.equal(formatOverviewOptionLabel(null), 'Overview');
});

test('getRefreshPricesButtonPresentation returns loading label and spin class', () => {
  assert.deepEqual(getRefreshPricesButtonPresentation(false), {
    iconClassName: 'mr-2 h-4 w-4',
    label: 'Refresh Prices',
  });
  assert.deepEqual(getRefreshPricesButtonPresentation(true), {
    iconClassName: 'mr-2 h-4 w-4 animate-spin',
    label: 'Refreshing',
  });
});

test('formatRefreshPricesSuccessDescription summarizes refreshed prices', () => {
  assert.equal(
    formatRefreshPricesSuccessDescription(
      [
        { stock_id: 1, status: 'refreshed' },
        { stock_id: 2, status: 'skipped' },
        { stock_id: 3, status: 'failed' },
      ],
      3
    ),
    'Updated 1 of 3 stocks.'
  );
  assert.equal(
    formatRefreshPricesSuccessDescription([{ stock_id: 1, status: 'skipped' }], 1),
    'Checked 1 stock; prices are already current.'
  );
  assert.equal(formatRefreshPricesSuccessDescription([], 0), 'No stocks to refresh.');
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
