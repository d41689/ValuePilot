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
    next[row.stock_id] = row.fair_value !== null ? row.fair_value.toFixed(2) : '';
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

function formatPiotroskiFScore(score) {
  if (!score) return '—';
  const fiscalYear = score.fiscal_year ? String(score.fiscal_year) : 'FY';
  if (score.score !== null && score.score !== undefined && Number.isFinite(score.score)) {
    return `${fiscalYear}: ${score.score.toFixed(0)}/9`;
  }
  if (
    score.partial_score !== null &&
    score.partial_score !== undefined &&
    score.max_available_score !== null &&
    score.max_available_score !== undefined
  ) {
    return `${fiscalYear}: ${score.partial_score}/${score.max_available_score} partial`;
  }
  return `${fiscalYear}: partial`;
}

function formatPiotroskiFScoreSeries(scores) {
  if (!Array.isArray(scores) || scores.length === 0) {
    return '—';
  }
  return scores.slice(0, 3).map(formatPiotroskiFScore).join('\n');
}

module.exports = {
  sortWatchlistMembers,
  buildFairValueEdits,
  hasFairValueEditChanges,
  formatPiotroskiFScore,
  formatPiotroskiFScoreSeries,
};
