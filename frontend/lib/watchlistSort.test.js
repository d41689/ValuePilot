/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  WATCHLIST_SORT_KEYS,
  DEFAULT_SORT_DIRECTION,
  DEFAULT_SORT_STATE,
  nextSortState,
  sortMembers,
} = require('./watchlistSort');

// ---------------------------------------------------------------------------
// nextSortState — three-state click cycle
// ---------------------------------------------------------------------------

test('nextSortState: click different column applies that column default direction', () => {
  const before = { key: 'default', direction: 'desc' };
  assert.deepEqual(nextSortState(before, 'conviction'), {
    key: 'conviction',
    direction: 'desc',
  });
  assert.deepEqual(nextSortState(before, 'ticker'), {
    key: 'ticker',
    direction: 'asc',
  });
});

test('nextSortState: click switches between columns using clicked column default', () => {
  const onConviction = { key: 'conviction', direction: 'desc' };
  assert.deepEqual(nextSortState(onConviction, 'ticker'), {
    key: 'ticker',
    direction: 'asc',
  });
  const onTickerAsc = { key: 'ticker', direction: 'asc' };
  assert.deepEqual(nextSortState(onTickerAsc, 'caveat_severity'), {
    key: 'caveat_severity',
    direction: 'desc',
  });
});

test('nextSortState: same column at default direction flips to the other', () => {
  const onConvictionDesc = { key: 'conviction', direction: 'desc' };
  assert.deepEqual(nextSortState(onConvictionDesc, 'conviction'), {
    key: 'conviction',
    direction: 'asc',
  });
  const onTickerAsc = { key: 'ticker', direction: 'asc' };
  assert.deepEqual(nextSortState(onTickerAsc, 'ticker'), {
    key: 'ticker',
    direction: 'desc',
  });
});

test('nextSortState: same column at non-default direction clears to default sort', () => {
  const onConvictionAsc = { key: 'conviction', direction: 'asc' };
  assert.deepEqual(nextSortState(onConvictionAsc, 'conviction'), DEFAULT_SORT_STATE);
  const onTickerDesc = { key: 'ticker', direction: 'desc' };
  assert.deepEqual(nextSortState(onTickerDesc, 'ticker'), DEFAULT_SORT_STATE);
});

test('nextSortState: unknown key is a no-op', () => {
  const current = { key: 'conviction', direction: 'desc' };
  assert.deepEqual(nextSortState(current, 'mos'), current);
  assert.deepEqual(nextSortState(current, 'unknown_field'), current);
});

test('WATCHLIST_SORT_KEYS covers exactly the six sortable columns', () => {
  assert.deepEqual([...WATCHLIST_SORT_KEYS], [
    'ticker',
    'company',
    'conviction',
    'delta_holders',
    'distinctiveness',
    'caveat_severity',
  ]);
});

test('DEFAULT_SORT_DIRECTION covers every WATCHLIST_SORT_KEY', () => {
  for (const key of WATCHLIST_SORT_KEYS) {
    assert.ok(
      DEFAULT_SORT_DIRECTION[key] === 'asc' || DEFAULT_SORT_DIRECTION[key] === 'desc',
      `${key} must have a default direction`,
    );
  }
});

// ---------------------------------------------------------------------------
// sortMembers — fixture
// ---------------------------------------------------------------------------

const _MEMBERS = [
  { stock_id: 1, ticker: 'AAPL', company_name: 'Apple Inc.', mos: 0.10 },
  { stock_id: 2, ticker: 'MSFT', company_name: 'Microsoft Corp.', mos: 0.30 },
  { stock_id: 3, ticker: 'GOOG', company_name: 'Alphabet Inc.', mos: 0.20 },
  { stock_id: 4, ticker: 'NOVL', company_name: 'No Snapshot Co.', mos: 0.05 },
];

const _SNAPSHOTS = new Map([
  [1, {
    available: true,
    conviction_percentile: 0.92,
    delta_holders: 5,
    distinctiveness_tier: 'distinctive',
    caveat_severity: 'ok',
  }],
  [2, {
    available: true,
    conviction_percentile: 0.50,
    delta_holders: -2,
    distinctiveness_tier: 'crowded',
    caveat_severity: 'high-caution',
  }],
  [3, {
    available: true,
    conviction_percentile: 0.75,
    delta_holders: 5,  // tied with AAPL for tiebreak test
    distinctiveness_tier: 'mixed',
    caveat_severity: 'caution',
  }],
  // stock 4 (NOVL) intentionally missing from snapshots
]);

// ---------------------------------------------------------------------------
// sortMembers — default delegates to sortWatchlistMembers
// ---------------------------------------------------------------------------

test("sortMembers with key='default' matches sortWatchlistMembers (MOS desc, ticker tiebreak)", () => {
  const sorted = sortMembers(_MEMBERS, _SNAPSHOTS, { key: 'default', direction: 'desc' });
  assert.deepEqual(sorted.map((r) => r.ticker), ['MSFT', 'GOOG', 'AAPL', 'NOVL']);
});

test('sortMembers does not mutate the input array', () => {
  const input = [..._MEMBERS];
  const inputCopy = [..._MEMBERS];
  sortMembers(input, _SNAPSHOTS, { key: 'conviction', direction: 'desc' });
  assert.deepEqual(input, inputCopy);
});

// ---------------------------------------------------------------------------
// sortMembers — ticker
// ---------------------------------------------------------------------------

test('sortMembers ticker asc orders alphabetically', () => {
  const sorted = sortMembers(_MEMBERS, _SNAPSHOTS, { key: 'ticker', direction: 'asc' });
  assert.deepEqual(sorted.map((r) => r.ticker), ['AAPL', 'GOOG', 'MSFT', 'NOVL']);
});

test('sortMembers ticker desc reverses', () => {
  const sorted = sortMembers(_MEMBERS, _SNAPSHOTS, { key: 'ticker', direction: 'desc' });
  assert.deepEqual(sorted.map((r) => r.ticker), ['NOVL', 'MSFT', 'GOOG', 'AAPL']);
});

// ---------------------------------------------------------------------------
// sortMembers — company
// ---------------------------------------------------------------------------

test('sortMembers company asc orders by company name', () => {
  const sorted = sortMembers(_MEMBERS, _SNAPSHOTS, { key: 'company', direction: 'asc' });
  assert.deepEqual(sorted.map((r) => r.ticker), ['GOOG', 'AAPL', 'MSFT', 'NOVL']);
});

// ---------------------------------------------------------------------------
// sortMembers — conviction (numeric, 13F)
// ---------------------------------------------------------------------------

test('sortMembers conviction desc puts highest percentile first, unavailable at bottom', () => {
  const sorted = sortMembers(_MEMBERS, _SNAPSHOTS, { key: 'conviction', direction: 'desc' });
  assert.deepEqual(sorted.map((r) => r.ticker), ['AAPL', 'GOOG', 'MSFT', 'NOVL']);
});

test('sortMembers conviction asc puts lowest percentile first, unavailable STILL at bottom', () => {
  const sorted = sortMembers(_MEMBERS, _SNAPSHOTS, { key: 'conviction', direction: 'asc' });
  // NOVL (unavailable) stays at the bottom even though direction flipped.
  assert.deepEqual(sorted.map((r) => r.ticker), ['MSFT', 'GOOG', 'AAPL', 'NOVL']);
});

// ---------------------------------------------------------------------------
// sortMembers — delta_holders tiebreak
// ---------------------------------------------------------------------------

test('sortMembers delta_holders desc: ties broken by ticker asc', () => {
  const sorted = sortMembers(_MEMBERS, _SNAPSHOTS, { key: 'delta_holders', direction: 'desc' });
  // AAPL and GOOG both have delta_holders=5 → ticker asc → AAPL before GOOG.
  // MSFT has -2. NOVL unavailable.
  assert.deepEqual(sorted.map((r) => r.ticker), ['AAPL', 'GOOG', 'MSFT', 'NOVL']);
});

// ---------------------------------------------------------------------------
// sortMembers — distinctiveness (ordinal, 13F)
// ---------------------------------------------------------------------------

test('sortMembers distinctiveness desc: distinctive → mixed → crowded → unavailable', () => {
  const sorted = sortMembers(_MEMBERS, _SNAPSHOTS, {
    key: 'distinctiveness',
    direction: 'desc',
  });
  assert.deepEqual(sorted.map((r) => r.ticker), ['AAPL', 'GOOG', 'MSFT', 'NOVL']);
});

test('sortMembers distinctiveness asc: crowded → mixed → distinctive, unavailable still bottom', () => {
  const sorted = sortMembers(_MEMBERS, _SNAPSHOTS, {
    key: 'distinctiveness',
    direction: 'asc',
  });
  assert.deepEqual(sorted.map((r) => r.ticker), ['MSFT', 'GOOG', 'AAPL', 'NOVL']);
});

// ---------------------------------------------------------------------------
// sortMembers — caveat_severity (ordinal, 13F)
// ---------------------------------------------------------------------------

test('sortMembers caveat_severity desc: worst first (high-caution → caution → ok)', () => {
  const sorted = sortMembers(_MEMBERS, _SNAPSHOTS, {
    key: 'caveat_severity',
    direction: 'desc',
  });
  assert.deepEqual(sorted.map((r) => r.ticker), ['MSFT', 'GOOG', 'AAPL', 'NOVL']);
});

test('sortMembers caveat_severity asc: cleanest first (ok → caution → high-caution)', () => {
  const sorted = sortMembers(_MEMBERS, _SNAPSHOTS, {
    key: 'caveat_severity',
    direction: 'asc',
  });
  assert.deepEqual(sorted.map((r) => r.ticker), ['AAPL', 'GOOG', 'MSFT', 'NOVL']);
});

// ---------------------------------------------------------------------------
// sortMembers — unavailable rows DON'T jump position on direction flip
// ---------------------------------------------------------------------------

test('sortMembers: unavailable row position is identical for asc and desc on 13F sort', () => {
  const desc = sortMembers(_MEMBERS, _SNAPSHOTS, { key: 'conviction', direction: 'desc' });
  const asc = sortMembers(_MEMBERS, _SNAPSHOTS, { key: 'conviction', direction: 'asc' });
  // Last row is the unavailable one in both directions.
  assert.equal(desc[desc.length - 1].ticker, 'NOVL');
  assert.equal(asc[asc.length - 1].ticker, 'NOVL');
});

// ---------------------------------------------------------------------------
// sortMembers — defensive
// ---------------------------------------------------------------------------

test('sortMembers handles null snapshotsByStockId by treating all 13F rows as unavailable', () => {
  const sorted = sortMembers(_MEMBERS, null, { key: 'conviction', direction: 'desc' });
  // All rows unavailable → tiebreak ticker asc.
  assert.deepEqual(sorted.map((r) => r.ticker), ['AAPL', 'GOOG', 'MSFT', 'NOVL']);
});

test('sortMembers accepts a plain object map for snapshotsByStockId', () => {
  const snapsObj = {
    1: { available: true, conviction_percentile: 0.10 },
    2: { available: true, conviction_percentile: 0.99 },
  };
  const sorted = sortMembers(_MEMBERS, snapsObj, { key: 'conviction', direction: 'desc' });
  // 2 (MSFT) is highest, then 1 (AAPL), then unavailable (GOOG, NOVL) alpha.
  assert.deepEqual(sorted.map((r) => r.ticker), ['MSFT', 'AAPL', 'GOOG', 'NOVL']);
});

test('sortMembers returns empty array when members input is invalid', () => {
  assert.deepEqual(sortMembers(null, _SNAPSHOTS, { key: 'ticker', direction: 'asc' }), []);
  assert.deepEqual(sortMembers(undefined, _SNAPSHOTS, { key: 'ticker', direction: 'asc' }), []);
});

test('sortMembers falls back to default sort when sortState is missing or invalid', () => {
  const expected = ['MSFT', 'GOOG', 'AAPL', 'NOVL'];
  assert.deepEqual(
    sortMembers(_MEMBERS, _SNAPSHOTS, null).map((r) => r.ticker),
    expected,
  );
  assert.deepEqual(
    sortMembers(_MEMBERS, _SNAPSHOTS, { key: 'bogus', direction: 'asc' }).map((r) => r.ticker),
    expected,
  );
});
