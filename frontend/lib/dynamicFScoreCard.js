const STATUS_TONES = new Set(['success', 'warning', 'danger', 'secondary']);

function normalizeDynamicFScoreCard(card) {
  if (!card || typeof card !== 'object') {
    return { years: [], rows: [] };
  }

  const years = Array.isArray(card.years) ? card.years.map((year) => String(year)) : [];
  const rows = Array.isArray(card.rows)
    ? card.rows.map((row) => ({
        category: typeof row.category === 'string' ? row.category : '',
        check: typeof row.check === 'string' ? row.check : '',
        metricKey: typeof row.metric_key === 'string' ? row.metric_key : '',
        scores: Array.isArray(row.scores)
          ? row.scores.map((score) => (typeof score === 'number' && Number.isFinite(score) ? score : null))
          : [],
        status: typeof row.status === 'string' ? row.status : '⚠️',
        statusTone: STATUS_TONES.has(row.status_tone) ? row.status_tone : 'warning',
        comment: typeof row.comment === 'string' ? row.comment : '',
      }))
    : [];

  return { years, rows };
}

function formatDynamicFScoreValue(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '—';
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

module.exports = {
  formatDynamicFScoreValue,
  normalizeDynamicFScoreCard,
};
