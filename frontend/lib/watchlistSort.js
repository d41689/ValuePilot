/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * MVP7-06: Watchlist click-to-sort helpers.
 *
 * Pure JS so the unit test file can `require()` it directly under
 * `node --test` (matches the sibling `watchlistState.test.js`
 * pattern). TypeScript types are mirrored in ./watchlistSort.d.ts.
 *
 * The default-sort path delegates to `sortWatchlistMembers` from
 * watchlistState.js so the no-active-sort behavior is bit-identical
 * to pre-MVP7-06 (MOS desc, ticker asc tiebreak).
 */

const { sortWatchlistMembers } = require('./watchlistState');

const WATCHLIST_SORT_KEYS = Object.freeze([
  'ticker',
  'company',
  'conviction',
  'delta_holders',
  'distinctiveness',
  'caveat_severity',
]);

const DEFAULT_SORT_DIRECTION = Object.freeze({
  ticker: 'asc',
  company: 'asc',
  conviction: 'desc',
  delta_holders: 'desc',
  distinctiveness: 'desc',
  // Diverges from Pre-MVP7-01 D1 spec ("severity asc"): users clicking
  // the Caveats column usually want to see RISKY signals first, not
  // clean ones. See MVP7-06 spec for rationale.
  caveat_severity: 'desc',
});

const DEFAULT_SORT_STATE = Object.freeze({ key: 'default', direction: 'desc' });

const DISTINCTIVENESS_RANK = Object.freeze({
  distinctive: 3,
  mixed: 2,
  crowded: 1,
});

const CAVEAT_SEVERITY_RANK = Object.freeze({
  ok: 1,
  caution: 2,
  'high-caution': 3,
});

/**
 * Three-state click cycle:
 *   click different column → default direction for that column
 *   click same column at default direction → flip
 *   click same column at non-default direction → clear (return to default sort)
 */
function nextSortState(currentState, clickedKey) {
  if (!WATCHLIST_SORT_KEYS.includes(clickedKey)) {
    return currentState;
  }
  const defaultDir = DEFAULT_SORT_DIRECTION[clickedKey];

  if (currentState.key !== clickedKey) {
    return { key: clickedKey, direction: defaultDir };
  }

  // Same column.
  if (currentState.direction === defaultDir) {
    return {
      key: clickedKey,
      direction: defaultDir === 'desc' ? 'asc' : 'desc',
    };
  }

  // Was on the non-default direction → clear.
  return { ...DEFAULT_SORT_STATE };
}

function _isThirteenfSortKey(key) {
  return (
    key === 'conviction' ||
    key === 'delta_holders' ||
    key === 'distinctiveness' ||
    key === 'caveat_severity'
  );
}

function _availableSnapshot(snapshotsByStockId, stockId) {
  if (!snapshotsByStockId) return null;
  const snap = typeof snapshotsByStockId.get === 'function'
    ? snapshotsByStockId.get(stockId)
    : snapshotsByStockId[stockId];
  if (!snap || snap.available !== true) return null;
  return snap;
}

function _thirteenfValue(snap, key) {
  if (!snap) return null;
  switch (key) {
    case 'conviction':
      return typeof snap.conviction_percentile === 'number'
        ? snap.conviction_percentile
        : null;
    case 'delta_holders':
      return typeof snap.delta_holders === 'number' ? snap.delta_holders : null;
    case 'distinctiveness':
      return DISTINCTIVENESS_RANK[snap.distinctiveness_tier] ?? null;
    case 'caveat_severity':
      return CAVEAT_SEVERITY_RANK[snap.caveat_severity] ?? null;
    default:
      return null;
  }
}

/**
 * Sort `members` according to `sortState`. Returns a NEW array; does
 * not mutate the input.
 *
 * Contract:
 * - key='default' → delegates to sortWatchlistMembers (legacy behavior)
 * - Ticker / Company → string sort via localeCompare
 * - 13F keys → numeric/ordinal sort over the snapshot value
 * - Unavailable rows for 13F keys: always sorted to the bottom
 *   regardless of direction. Tiebreak among unavailable: ticker asc.
 * - Tiebreak among equal values: ticker asc.
 */
function sortMembers(members, snapshotsByStockId, sortState) {
  if (!Array.isArray(members)) return [];
  if (!sortState || sortState.key === 'default') {
    return sortWatchlistMembers(members);
  }
  if (!WATCHLIST_SORT_KEYS.includes(sortState.key)) {
    return sortWatchlistMembers(members);
  }

  const directionFactor = sortState.direction === 'asc' ? 1 : -1;
  const rows = [...members];

  if (sortState.key === 'ticker') {
    rows.sort((a, b) =>
      directionFactor * String(a.ticker).localeCompare(String(b.ticker)),
    );
    return rows;
  }

  if (sortState.key === 'company') {
    rows.sort((a, b) => {
      const av = String(a.company_name ?? '');
      const bv = String(b.company_name ?? '');
      const cmp = av.localeCompare(bv, undefined, { sensitivity: 'base' });
      if (cmp !== 0) return directionFactor * cmp;
      return String(a.ticker).localeCompare(String(b.ticker));
    });
    return rows;
  }

  if (_isThirteenfSortKey(sortState.key)) {
    rows.sort((a, b) => {
      const aSnap = _availableSnapshot(snapshotsByStockId, a.stock_id);
      const bSnap = _availableSnapshot(snapshotsByStockId, b.stock_id);
      const aVal = _thirteenfValue(aSnap, sortState.key);
      const bVal = _thirteenfValue(bSnap, sortState.key);

      // Unavailable rows (null value) ALWAYS at the bottom — not flipped
      // by direction. Locks predictable position across direction toggles.
      if (aVal === null && bVal === null) {
        return String(a.ticker).localeCompare(String(b.ticker));
      }
      if (aVal === null) return 1;
      if (bVal === null) return -1;

      if (aVal === bVal) {
        return String(a.ticker).localeCompare(String(b.ticker));
      }
      return directionFactor * (aVal - bVal);
    });
    return rows;
  }

  return sortWatchlistMembers(members);
}

module.exports = {
  WATCHLIST_SORT_KEYS,
  DEFAULT_SORT_DIRECTION,
  DEFAULT_SORT_STATE,
  nextSortState,
  sortMembers,
};
