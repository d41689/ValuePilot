const STATUS_TONES = new Set(['success', 'warning', 'danger', 'secondary']);

function normalizeFormulaDetails(details) {
  if (!details || typeof details !== 'object') {
    return {
      standardDefinition: '',
      standardFormula: '',
      fallbackFormulas: [],
      usedFormula: '',
      usedValues: [],
    };
  }
  return {
    standardDefinition:
      typeof details.standard_definition === 'string' ? details.standard_definition : '',
    standardFormula: typeof details.standard_formula === 'string' ? details.standard_formula : '',
    fallbackFormulas: Array.isArray(details.fallback_formulas)
      ? details.fallback_formulas.filter((formula) => typeof formula === 'string')
      : [],
    usedFormula: typeof details.used_formula === 'string' ? details.used_formula : '',
    usedValues: Array.isArray(details.used_values)
      ? details.used_values.map((value) => ({
          metricKey: typeof value?.metric_key === 'string' ? value.metric_key : '',
          valueNumeric:
            typeof value?.value_numeric === 'number' && Number.isFinite(value.value_numeric)
              ? value.value_numeric
              : null,
          periodEndDate: typeof value?.period_end_date === 'string' ? value.period_end_date : '',
          factNature: typeof value?.fact_nature === 'string' ? value.fact_nature : '',
        }))
      : [],
  };
}

function visibleFallbackFormulas(details) {
  const usedFormula = typeof details?.usedFormula === 'string' ? details.usedFormula.trim() : '';
  const seen = new Set();
  return (Array.isArray(details?.fallbackFormulas) ? details.fallbackFormulas : []).filter((formula) => {
    if (typeof formula !== 'string') {
      return false;
    }
    const normalized = formula.trim();
    if (!normalized || normalized === usedFormula || seen.has(normalized)) {
      return false;
    }
    seen.add(normalized);
    return true;
  });
}

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
        formula: typeof row.formula === 'string' ? row.formula : '',
        formulaDetails: normalizeFormulaDetails(row.formula_details),
        scores: Array.isArray(row.scores)
          ? row.scores.map((score) => (typeof score === 'number' && Number.isFinite(score) ? score : null))
          : [],
        scoreFactNatures: Array.isArray(row.score_fact_natures)
          ? row.score_fact_natures.map((nature) => (typeof nature === 'string' ? nature : null))
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
  normalizeFormulaDetails,
  visibleFallbackFormulas,
};
