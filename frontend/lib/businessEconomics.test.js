/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');
const { businessEconomics, analysisObservation, appendAnalysisObservation } = require('./businessEconomics');
const ids = { 'is.revenue': 'sec.revenue', 'is.operating_income': 'sec.operating_income',
  'is.gross_profit': 'sec.gross_profit', 'is.operating_cash_flow': 'sec.operating_cash_flow',
  'cf.capital_expenditures': 'sec.capital_expenditures' };
let sequence = 0;
function fact(key, value, year = 2025, extra = {}) {
  const id = ++sequence;
  return { row_kind: 'fact', row_key: `fact:${id}`, status: 'available', reason_code: null,
    fact_id: id, publication_id: id + 1000, metric_key: key, value_numeric_exact: value,
    unit: 'currency', currency: 'USD', fiscal_year: year, fiscal_quarter: null,
    period_type: 'FY', period_basis: 'duration', period_start: `${year}-01-01`, period_end: `${year}-12-31`,
    source_type: 'sec', source_role: 'primary_as_filed_actual', fact_nature: 'actual',
    comparison_identity: { identity_complete: true, definition_family: `canonical:${key}`,
      definition_id: ids[key], definition_basis: 'as_filed', dimensions_identity: 'empty',
      mapping_version: 'canonical-financial-definitions-v1', source_mapping_version: 'sec-us-gaap-v1',
      source_identity: `sec-publication:${id + 1000}`, duration_days: year === 2024 ? 366 : 365,
      period_duration_kind: 'fiscal_year' }, ...extra };
}
const history = rows => ({ schema_version: 1, evaluated_at: '2026-09-10T23:00:00Z',
  annual_window: { status: 'determined', years: [2023, 2024, 2025] }, rows });
function sample() { return [fact('is.revenue', '416161000000'), fact('is.operating_income', '133050000000'),
  fact('is.gross_profit', '195201000000'), fact('is.operating_cash_flow', '111482000000'), fact('cf.capital_expenditures', '12715000000')]; }
const point = (rows, key = 'operating_margin', year = 2025) => businessEconomics(history(rows)).series.find(s => s.id === key).points.find(p => p.year === year);

test('AAPL exact operands produce descriptive margins and CFO less PPE spending, not owner earnings', () => {
  const rows = sample(); const frozen = JSON.stringify(rows);
  assert.equal(point(rows).text, '31.97%');
  assert.equal(point(rows, 'gross_margin').text, '46.91%');
  const cash = point(rows, 'cash_after_ppe');
  assert.equal(cash.valueExact, '98767000000'); assert.equal(cash.text, '98.77');
  assert.equal(cash.unitLabel, 'billion USD');
  assert.deepEqual(cash.inputs.map(r => r.fact_id), [rows[3].fact_id, rows[4].fact_id]);
  assert.equal(JSON.stringify(rows), frozen);
  const model = businessEconomics(history(rows));
  assert.match(model.series.find(s => s.id === 'cash_after_ppe').caveat, /not owner earnings/i);
  assert.deepEqual(model.years, [2023, 2024, 2025]);
  assert.equal(model.series.some(s => s.id === 'roic'), false);
});

test('precision, true zero, small nonzero, negative margin and cash shortfall remain distinct', () => {
  assert.equal(point([fact('is.revenue', '100'), fact('is.operating_income', '-10')]).text, '-10.00%');
  assert.equal(point([fact('is.revenue', '100'), fact('is.operating_income', '0')]).text, '0.00%');
  assert.equal(point([fact('is.revenue', '1000000'), fact('is.operating_income', '0.1')]).text, '<0.01%');
  assert.equal(point([fact('is.revenue', '1000000'), fact('is.operating_income', '-0.1')]).text, '>-0.01%');
  const cash = point([fact('is.operating_cash_flow', '9007199254740993.000000000001'),
    fact('cf.capital_expenditures', '9007199254740993.000000000000')], 'cash_after_ppe');
  assert.equal(cash.valueExact, '0.000000000001'); assert.equal(cash.text, '<0.01');
  assert.equal(point([fact('is.operating_cash_flow', '-10'), fact('cf.capital_expenditures', '20')], 'cash_after_ppe').valueExact, '-30');
  for (const bad of ['0', '-100']) assert.equal(point([fact('is.revenue', bad), fact('is.operating_income', '5')]).reason, 'nonpositive_revenue');
  assert.equal(point([fact('is.operating_cash_flow', '100'), fact('cf.capital_expenditures', '-5')], 'cash_after_ppe').reason, 'negative_capex');
});

test('no picking a source or prefix, no loss/invalid/unknown inputs converted to zero', () => {
  for (const extra of [{ value_numeric_exact: null }, { value_numeric_exact: '' }, { value_numeric_exact: '1e5' },
    { value_numeric_exact: '9'.repeat(257) }, { currency: null }, { currency: 'EUR' }, { unit: 'shares' },
    { source_type: 'parsed' }, { source_role: 'value_line_adjusted_actual' }, { fact_nature: 'estimate' },
    { comparison_identity: null }, { period_start: '2025-03-01' }, { period_end: '2025-02-30' },
    { fiscal_quarter: 4 }, { publication_id: null }, { fact_id: null }]) {
    const rows = sample(); rows[1] = { ...rows[1], ...extra };
    const p = point(rows); assert.equal(p.status, 'unavailable', JSON.stringify(extra));
    assert.equal(p.valueExact, null); assert.deepEqual(p.inputs, []);
  }
  for (const key of ['definition_family', 'definition_id', 'definition_basis', 'dimensions_identity', 'mapping_version', 'source_mapping_version', 'source_identity']) {
    const rows = sample(); rows[1].comparison_identity[key] = 'different';
    assert.equal(point(rows).status, 'unavailable', key);
  }
  const rows = sample(); rows.push({ ...rows[1], fact_id: 999, row_key: 'fact:999' });
  assert.equal(point(rows).reason, 'multiple_observations');
  rows.pop(); rows[1].fiscal_year = null;
  assert.equal(point(rows).reason, 'annual_identity_unproven');
});

test('blocking metric, slot and cycle states are not erased by positive observations', () => {
  const state = { row_kind: 'slot_state', metric_key: 'is.operating_income', period_type: 'FY', fiscal_year: 2025, status: 'unavailable' };
  for (const blocked of [state, { ...state, fiscal_year: null }, { ...state, row_kind: 'metric_state' },
    { row_kind: 'filing_cycle_state', scope: null }, { row_kind: 'filing_cycle_state', scope: { metric_keys: ['is.operating_income'], fiscal_years: [2025] } }]) {
    assert.equal(point([...sample(), blocked]).reason, 'blocked_or_conflicting');
  }
  assert.equal(point([...sample(), { ...state, fiscal_year: 2024 }]).status, 'available');
  assert.equal(point([...sample(), { ...state, period_type: 'Q' }]).status, 'available');
  assert.equal(point([...sample(), { row_kind: 'filing_cycle_state', scope: { metric_keys: ['is.net_income'], fiscal_years: [2025] } }]).status, 'available');
});

test('no invented annual window, mismatched period, FY alignment or annualization', () => {
  assert.deepEqual(businessEconomics({ ...history(sample()), annual_window: { status: 'undetermined', years: [] } }).years, []);
  const rows = sample(); rows[1].period_start = '2024-12-30'; rows[1].period_end = '2025-12-28';
  rows[1].comparison_identity.duration_days = 364;
  assert.equal(point(rows).reason, 'incompatible_inputs');
  const fy2024 = sample().map(r => ({ ...r, fiscal_year: 2024 }));
  assert.equal(point(fy2024).status, 'unavailable');
});

test('explicit research context is factual, attributed and does not invent an explanation or replace notes', () => {
  const model = businessEconomics(history(sample())); const series = model.series[0]; const p = series.points.at(-1);
  const text = analysisObservation(series, p, model.evaluatedAt);
  assert.match(text, /Display calculation/); assert.match(text, /31.97%/);
  assert.match(text, /2025-01-01.*2025-12-31/); assert.match(text, /2026-09-10T23:00:00Z/);
  for (const row of p.inputs) { assert.ok(text.includes(`fact #${row.fact_id}`)); assert.ok(text.includes(row.value_numeric_exact)); }
  assert.doesNotMatch(text, /buy|undervalued|strong moat|therefore/i);
  assert.equal(analysisObservation(series, series.points[0], model.evaluatedAt), null);
});

test('user-triggered insertion preserves every existing answer and never writes thesis or evidence', () => {
  const before = { observation: '  My original observation.  ', explanations: 'My hypothesis', judgment: 'Unknown', evidenceNeeded: 'Check report', falsification: 'Counterexample' };
  const after = appendAnalysisObservation(before, 'Display calculation — explicit context');
  assert.equal(after.observation, before.observation + '\n\nDisplay calculation — explicit context');
  for (const key of Object.keys(before).filter(k => k !== 'observation')) assert.equal(after[key], before[key]);
  assert.equal(before.observation, '  My original observation.  ');
  assert.equal(appendAnalysisObservation(before, null), before);
  assert.deepEqual(appendAnalysisObservation(undefined, 'Context'), { observation: 'Context', explanations: '', evidenceNeeded: '', falsification: '', judgment: '' });
});
