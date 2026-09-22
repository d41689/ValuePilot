/* Non-persistent reading calculations over one authorized workspace response. */
/* eslint-disable @typescript-eslint/no-require-imports */
const { observationProblem, formatBillions } = require('./financialTrends');
const { emptyResearchNotes } = require('./researchPath');
const POLICY = 'business-economics-reading-v1';
const ANALYSIS_METRICS = [
  { key: 'is.operating_income', label: 'Operating income', description: 'Reported operating profit before financing and tax; not NOPAT', definition: 'sec.operating_income' },
  { key: 'is.gross_profit', label: 'Gross profit', description: 'Reported revenue less cost of sales; not operating profit', definition: 'sec.gross_profit' },
  { key: 'is.revenue', label: 'Revenue', definition: 'sec.revenue' },
  { key: 'is.operating_cash_flow', label: 'Operating cash flow', definition: 'sec.operating_cash_flow' },
  { key: 'cf.capital_expenditures', label: 'PPE capital expenditures', definition: 'sec.capital_expenditures' },
];
const CALCULATIONS = [
  { id: 'operating_margin', label: 'Operating margin', keys: ['is.operating_income', 'is.revenue'], kind: 'ratio',
    formula: 'Operating income ÷ revenue × 100%', question: 'What explains the change in operating profitability?',
    caveat: 'As-reported operating margin, not ROIC. Pricing, mix, costs and one-off items require investigation; a higher margin alone does not prove a moat.' },
  { id: 'gross_margin', label: 'Gross margin', keys: ['is.gross_profit', 'is.revenue'], kind: 'ratio',
    formula: 'Gross profit ÷ revenue × 100%', question: 'Are pricing, product mix or production costs changing?',
    caveat: 'As-reported gross margin; definitions and business models matter. This is not a peer ranking or an investment conclusion.' },
  { id: 'cash_after_ppe', label: 'CFO less PPE capital expenditures', keys: ['is.operating_cash_flow', 'cf.capital_expenditures'], kind: 'difference',
    formula: 'Operating cash flow − purchases of property, plant and equipment', question: 'What cash remains after reported PPE spending, and what obligations are still missing?',
    caveat: 'This difference is not owner earnings or cash available for distribution. It does not separately adjust for SBC, acquisitions, debt service or maintenance-versus-growth spending; working-capital movements remain inside CFO.' },
];
const REASONS = {
  missing_observation: 'No usable annual input returned; this does not mean it was not disclosed.',
  annual_identity_unproven: 'An annual input has no proven fiscal-year identity.',
  multiple_observations: 'Competing annual observations; no input was selected.',
  blocked_or_conflicting: 'A relevant input is blocked or conflicting; inspect financial details.',
  identity_unproven: 'This view requires proven, consolidated SEC as-filed inputs.',
  incompatible_inputs: 'The inputs do not share the same period, currency or source semantics.',
  nonpositive_revenue: 'Revenue is zero or negative; this margin is not meaningful.',
  negative_capex: 'PPE spending has a negative amount; no sign convention was guessed.',
};
function covers(row, key, year) {
  if (row.row_kind === 'fact') return false;
  if (row.row_kind === 'filing_cycle_state' || !row.metric_key) {
    return (!Array.isArray(row.scope?.metric_keys) || row.scope.metric_keys.includes(key))
      && (!Array.isArray(row.scope?.fiscal_years) || row.scope.fiscal_years.includes(year));
  }
  if (row.metric_key !== key) return false;
  if (row.row_kind === 'metric_state') return true;
  if (row.period_type && row.period_type !== 'FY') return false;
  return !Number.isInteger(row.fiscal_year) || row.fiscal_year === year;
}
function input(history, key, year) {
  if (history.rows.some(row => covers(row, key, year))) return { reason: 'blocked_or_conflicting' };
  const candidates = history.rows.filter(row => row.row_kind === 'fact' && row.metric_key === key && row.period_type === 'FY');
  if (candidates.some(row => !Number.isInteger(row.fiscal_year))) return { reason: 'annual_identity_unproven' };
  const rows = candidates.filter(row => row.fiscal_year === year);
  if (rows.length !== 1) return { reason: rows.length ? 'multiple_observations' : 'missing_observation' };
  const row = rows[0]; const identity = row.comparison_identity;
  if (observationProblem(row) || row.period_basis !== 'duration' || row.unit !== 'currency'
    || row.source_type !== 'sec' || row.source_role !== 'primary_as_filed_actual'
    || !Number.isInteger(row.fact_id) || row.fact_id <= 0 || !Number.isInteger(row.publication_id) || row.publication_id <= 0
    || identity.definition_family !== `canonical:${key}` || identity.definition_id !== ANALYSIS_METRICS.find(m => m.key === key).definition
    || identity.definition_basis !== 'as_filed' || identity.dimensions_identity !== 'empty'
    || identity.source_identity !== `sec-publication:${row.publication_id}`) return { reason: 'identity_unproven' };
  return { row };
}
function numbers(rows) {
  const parts = rows.map(row => { const [whole, fraction = ''] = row.value_numeric_exact.split('.'); return { n: BigInt(whole + fraction), scale: fraction.length }; });
  const scale = Math.max(...parts.map(p => p.scale));
  return { scale, values: parts.map(p => p.n * 10n ** BigInt(scale - p.scale)) };
}
function exact(n, scale) {
  const sign = n < 0n ? '-' : ''; const magnitude = n < 0n ? -n : n;
  if (!scale) return sign + magnitude;
  const digits = magnitude.toString().padStart(scale + 1, '0');
  return (sign + digits.slice(0, -scale) + '.' + digits.slice(-scale)).replace(/\.?0+$/, '') || '0';
}
function percent(n, d) {
  const negative = n < 0n; const magnitude = negative ? -n : n;
  const hundredths = (magnitude * 10000n + d / 2n) / d;
  if (magnitude && !hundredths) return negative ? '>-0.01%' : '<0.01%';
  return `${negative && hundredths ? '-' : ''}${hundredths / 100n}.${String(hundredths % 100n).padStart(2, '0')}%`;
}
function calculate(history, spec, year) {
  const blank = reason => ({ year, status: 'unavailable', reason, inputs: [], valueExact: null, text: 'Not available', unitLabel: '', policy: POLICY });
  const selected = spec.keys.map(key => input(history, key, year));
  const problem = selected.find(i => i.reason); if (problem) return blank(problem.reason);
  const inputs = selected.map(i => i.row); const [a, b] = inputs;
  if (['currency', 'period_start', 'period_end', 'period_basis', 'source_type', 'source_role'].some(k => a[k] !== b[k])
    || ['mapping_version', 'source_mapping_version', 'definition_basis', 'dimensions_identity'].some(k => a.comparison_identity[k] !== b.comparison_identity[k])) return blank('incompatible_inputs');
  const { values: [n, d], scale } = numbers(inputs);
  if (spec.kind === 'ratio' && d <= 0n) return blank('nonpositive_revenue');
  if (spec.kind === 'difference' && d < 0n) return blank('negative_capex');
  const valueExact = spec.kind === 'difference' ? exact(n - d, scale) : null;
  const display = spec.kind === 'ratio' ? { text: percent(n, d), unitLabel: '%' }
    : formatBillions({ value_numeric_exact: valueExact, unit: 'currency', currency: a.currency });
  return { year, status: 'available', reason: null, inputs, valueExact, ...display, policy: POLICY };
}
function businessEconomics(history) {
  const years = history.annual_window.status === 'determined' ? history.annual_window.years : [];
  return { years, evaluatedAt: history.evaluated_at, series: CALCULATIONS.map(spec => ({ ...spec, points: years.map(year => calculate(history, spec, year)) })) };
}
function analysisObservation(series, point, evaluatedAt) {
  if (point.status !== 'available') return null;
  const currency = point.inputs[0].currency;
  return `Display calculation — ${series.label}, FY${point.year}: ${point.text}${point.unitLabel === '%' ? '' : ` ${point.unitLabel}`} (${series.formula}).\n`
    + `${point.inputs[0].period_start} → ${point.inputs[0].period_end}; ${currency}; as-reported SEC actuals.\n`
    + point.inputs.map(r => `${ANALYSIS_METRICS.find(m => m.key === r.metric_key).label}: ${r.value_numeric_exact} ${r.currency}; fact #${r.fact_id}, publication #${r.publication_id}.`).join('\n')
    + `\n${series.caveat}\nReading policy ${POLICY}; evaluated ${evaluatedAt}. Source evidence must be reviewed and attached separately. No explanation or investment judgment recorded.`;
}
function appendAnalysisObservation(notes, text) {
  if (!text) return notes;
  const prior = { ...emptyResearchNotes(), ...notes };
  return { ...prior, observation: `${prior.observation}${prior.observation ? '\n\n' : ''}${text}` };
}
module.exports = { businessEconomics, analysisObservation, appendAnalysisObservation, ANALYSIS_METRICS, REASONS };
