function sortWatchlistMembers(rows) {
  return [...rows].sort((a, b) => {
    const aMos = a.mos ?? -Infinity;
    const bMos = b.mos ?? -Infinity;
    if (bMos === aMos) {
      return a.ticker.localeCompare(b.ticker);
    }
    return bMos - aMos;
  });
}

function buildFairValueEdits(rows) {
  const next = {};
  for (const row of rows) {
    next[row.stock_id] = row.fair_value !== null ? row.fair_value.toString() : '';
  }
  return next;
}

function hasFairValueEditChanges(current, next) {
  const currentKeys = Object.keys(current);
  const nextKeys = Object.keys(next);

  if (currentKeys.length !== nextKeys.length) {
    return true;
  }

  for (const key of nextKeys) {
    if (current[key] !== next[key]) {
      return true;
    }
  }

  return false;
}

module.exports = {
  sortWatchlistMembers,
  buildFairValueEdits,
  hasFairValueEditChanges,
};
