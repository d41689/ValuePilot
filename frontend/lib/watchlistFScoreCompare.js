function normalizeFScoreComparePayload(payload) {
  const years = Array.isArray(payload?.years)
    ? payload.years.filter((year) => Number.isInteger(year))
    : [];
  const rows = Array.isArray(payload?.rows)
    ? payload.rows.map((row) => {
        const scoreByYear = new Map(
          Array.isArray(row?.scores)
            ? row.scores
                .filter((score) => Number.isInteger(score?.fiscal_year))
                .map((score) => [score.fiscal_year, normalizeScoreCell(score)])
            : []
        );
        return {
          stockId: typeof row?.stock_id === 'number' ? row.stock_id : null,
          ticker: typeof row?.ticker === 'string' ? row.ticker : '',
          exchange: typeof row?.exchange === 'string' ? row.exchange : '',
          companyName: typeof row?.company_name === 'string' ? row.company_name : '',
          scores: years.map((year) => scoreByYear.get(year) || emptyScoreCell(year)),
        };
      })
    : [];
  return {
    watchlist: {
      id: payload?.watchlist?.id ?? null,
      name: typeof payload?.watchlist?.name === 'string' ? payload.watchlist.name : 'Watchlist',
    },
    years,
    rows,
  };
}

function normalizeScoreCell(score) {
  const numericScore = typeof score?.score === 'number' && Number.isFinite(score.score)
    ? score.score
    : null;
  return {
    fiscalYear: score.fiscal_year,
    score: numericScore,
    displayScore: typeof score?.display_score === 'string' ? score.display_score : formatScoreValue(numericScore),
    factNature: typeof score?.fact_nature === 'string' ? score.fact_nature : null,
    status: typeof score?.status === 'string' ? score.status : null,
    tone: scoreTone(numericScore),
  };
}

function emptyScoreCell(year) {
  return {
    fiscalYear: year,
    score: null,
    displayScore: '—',
    factNature: null,
    status: null,
    tone: 'missing',
  };
}

function formatScoreValue(score) {
  if (typeof score !== 'number' || !Number.isFinite(score)) {
    return '—';
  }
  return score.toFixed(0);
}

function scoreTone(score) {
  if (typeof score !== 'number' || !Number.isFinite(score)) {
    return 'missing';
  }
  if (score >= 7) return 'strong';
  if (score >= 4) return 'mixed';
  return 'weak';
}

module.exports = {
  normalizeFScoreComparePayload,
  scoreTone,
};
