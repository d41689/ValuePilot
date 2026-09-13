/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');
const { annualReading, compareAnnual, formatBillions, chartGeometry, cashQuestion } = require('./financialTrends');

function fact(year, value, overrides = {}) {
  return { row_kind: 'fact', row_key: `fact:${year}`, status: 'available', fact_id: year,
    metric_key: 'is.revenue', fiscal_year: year, period_type: 'FY', period_basis: 'duration',
    period_start: `${year}-01-01`, period_end: `${year}-12-31`, fiscal_quarter: null,
    unit: 'currency', currency: 'USD', value_numeric_exact: value, source_type: 'sec',
    source_role: 'primary_as_filed_actual', fact_nature: 'actual',
    comparison_identity: { identity_complete: true, definition_family: 'canonical:is.revenue',
      definition_basis: 'as_filed', definition_id: 'sec.revenue', mapping_version: 'v1',
      source_mapping_version: 'v1', dimensions_identity: 'empty', source_identity: `sec-publication:${year}`,
      duration_days: year === 2024 ? 366 : 365, period_duration_kind: 'fiscal_year' }, ...overrides };
}
const history = rows => ({ annual_window: { status: 'determined', years: [2023, 2024, 2025] }, rows });

test('YoY uses exact decimals and retains both identities, not equal publication IDs', () => {
  const before = fact(2024, '391035000000');
  const after = fact(2025, '416161000000');
  const result = compareAnnual(after, before);
  assert.equal(result.text, '+6.4%');
  assert.deepEqual(result.factIds, [2024, 2025]);
  assert.match(result.caveat, /366.*365/);
  assert.equal(compareAnnual(fact(2025, '112010000000'), fact(2024, '93736000000')).text, '+19.5%');
  assert.equal(compareAnnual(fact(2025, '111482000000'), fact(2024, '118254000000')).text, '-5.7%');
  assert.equal(compareAnnual(fact(2025, '100000000000000000000000000001'), fact(2024, '100000000000000000000000000000')).text, '<+0.1%');
  assert.equal(formatBillions(fact(2025, '416161000000')).text, '416.16');
  assert.equal(formatBillions(fact(2025, '1')).text, '<0.01');
  assert.equal(formatBillions(fact(2025, '-1')).text, '>-0.01');
});

test('no arithmetic for missing, zero/negative bases, losses, unknown or incomparable identities', () => {
  const before = fact(2024, '100'); const after = fact(2025, '120');
  assert.equal(compareAnnual(after, null).reason, 'missing_observation');
  for (const value of ['0', '-100']) assert.equal(compareAnnual(after, fact(2024, value)).status, 'not_meaningful');
  assert.equal(compareAnnual(fact(2025, '-1'), before).status, 'not_meaningful');
  for (const override of [{ value_numeric_exact: null }, { value_numeric_exact: '1e9' },
    { currency: null }, { currency: 'CAD' }, { unit: 'shares' }, { fact_nature: 'estimate' },
    { source_role: 'value_line_adjusted_actual' }, { source_type: 'parsed' }, { fiscal_year: 2026 },
    { comparison_identity: null }, { period_start: '2025-04-01' }, { period_end: '2025-02-30' }]) {
    assert.notEqual(compareAnnual({ ...after, ...override }, before).status, 'available', JSON.stringify(override));
  }
  for (const key of ['definition_id', 'definition_basis', 'definition_family', 'mapping_version', 'source_mapping_version', 'dimensions_identity']) {
    for (const value of [null, 'unknown', 'different']) assert.notEqual(compareAnnual({ ...after,
      comparison_identity: { ...after.comparison_identity, [key]: value } }, before).status, 'available', key);
  }
});

test('52/53 weeks disclosed, short years and noncontiguous periods refused, instant separate', () => {
  const before = fact(2023, '100', { period_start: '2022-09-25', period_end: '2023-09-30' });
  before.comparison_identity.duration_days = 371;
  const after = fact(2024, '110', { period_start: '2023-10-01', period_end: '2024-09-28' });
  after.comparison_identity.duration_days = 364;
  assert.equal(compareAnnual(after, before).text, '+10.0%');
  assert.match(compareAnnual(after, before).caveat, /371.*364/);
  assert.notEqual(compareAnnual({ ...after, period_start: '2023-10-02' }, before).status, 'available');
  const instant = row => ({ ...row, period_basis: 'instant', period_start: null,
    comparison_identity: { ...row.comparison_identity, duration_days: null, period_duration_kind: null } });
  assert.equal(compareAnnual(instant(after), instant(before)).status, 'available');
  assert.notEqual(compareAnnual(instant(after), before).status, 'available');
});

test('reading preserves ambiguity and states; chart segments never cross gaps or semantic changes', () => {
  const rows = [fact(2023, '100'), fact(2025, '120')];
  let reading = annualReading(history(rows), 'is.revenue');
  assert.equal(reading.points[1].row, null);
  assert.equal(reading.points[2].change.status, 'unavailable');
  assert.deepEqual(chartGeometry([reading]).series[0].segments.map(s => s.length), [1, 1]);
  const duplicate = { ...rows[1], fact_id: 8, row_key: 'fact:8' };
  reading = annualReading(history([...rows, duplicate]), 'is.revenue');
  assert.equal(reading.points[2].reason, 'multiple_observations');
  assert.equal(reading.points[2].observations.length, 2);
  const blocked = { row_kind: 'metric_state', metric_key: 'is.revenue', row_key: 'state:1', status: 'unavailable' };
  assert.equal(annualReading(history([...rows, blocked]), 'is.revenue').points[0].row, null);
  const cycle = { row_kind: 'filing_cycle_state', row_key: 'cycle:1', scope: null };
  assert.equal(annualReading(history([...rows, cycle]), 'is.revenue').points[0].row, null);
  const different = fact(2024, '110', { currency: 'CAD' });
  assert.equal(chartGeometry([annualReading(history([...rows, different]), 'is.revenue')]).reason, 'mixed_units_or_sources');
  const segment = fact(2024, '110'); segment.comparison_identity.dimensions_identity = 'segment:services';
  assert.equal(chartGeometry([annualReading(history([...rows, segment]), 'is.revenue')]).reason, 'mixed_units_or_sources');
  const semantic = fact(2024, '110'); semantic.comparison_identity.definition_id = 'changed';
  assert.deepEqual(chartGeometry([annualReading(history([...rows, semantic]), 'is.revenue')]).series[0].segments.map(s => s.length), [1, 1, 1]);
  const otherPeriod = fact(2025, '50', { metric_key: 'is.net_income', period_start: '2024-04-01', period_end: '2025-03-31' });
  assert.equal(chartGeometry([annualReading(history(rows), 'is.revenue'), annualReading(history([otherPeriod]), 'is.net_income')]).reason, 'unaligned_fiscal_periods');
});

test('bounded chart coordinates include zero, handle negatives and keep input facts intact', () => {
  const reading = annualReading(history([fact(2023, '-100'), fact(2024, '0'), fact(2025, '100')]), 'is.revenue');
  const geometry = chartGeometry([reading]);
  assert.equal(geometry.zeroY, 50);
  assert.deepEqual(geometry.series[0].segments.flat().map(p => p.y), [100, 50, 0]);
  assert.deepEqual(geometry.series[0].segments.flat().map(p => p.row.fact_id), [2023, 2024, 2025]);
  const huge = annualReading(history([fact(2023, '9'.repeat(240)), fact(2024, '0')]), 'is.revenue');
  assert.ok(chartGeometry([huge]).series[0].segments.flat().every(p => Number.isFinite(p.y)));
});

test('reported share counts require proven split basis; no misleading YoY or connected share trend', () => {
  const before = fact(2024, '4648913000', { metric_key: 'equity.weighted_average_diluted_shares', unit: 'shares', currency: null });
  const after = fact(2025, '17528214000', { metric_key: before.metric_key, unit: 'shares', currency: null });
  assert.equal(compareAnnual(after, before).reason, 'share_split_basis_unproven');
  const reading = annualReading(history([before, after]), before.metric_key);
  assert.equal(reading.points[2].row, after);
  assert.deepEqual(chartGeometry([reading]).series[0].segments.map(s => s.length), [1, 1]);
});

test('cash prompt requires compatible periods/currency and observed opposite changes, not causal claims', () => {
  const pair = (metric, a, b) => annualReading(history([fact(2024, a, { metric_key: metric }), fact(2025, b, { metric_key: metric })]), metric);
  const ni = pair('is.net_income', '100', '120'); const cfo = pair('is.operating_cash_flow', '110', '100');
  assert.match(cashQuestion(ni, cfo), /profit rose.*operating cash flow fell/i);
  cfo.points[2].row.currency = 'CAD';
  assert.doesNotMatch(cashQuestion(ni, cfo), /profit rose/i);
});

function renderCard(rows, annualWindow) {
  const fs = require('node:fs'); const path = require('node:path'); const vm = require('node:vm');
  const ts = require('typescript'); const React = require('react');
  const cache = new Map(); const root = path.resolve(__dirname, '..');
  function load(file) {
    if (cache.has(file)) return cache.get(file);
    const exports = {};
    const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
    } }).outputText;
    vm.runInNewContext(compiled, { exports, require: name => {
      if (!name.startsWith('@/') && !name.startsWith('.')) return require(name);
      const base = name.startsWith('@/') ? path.join(root, name.slice(2)) : path.resolve(path.dirname(file), name);
      const target = ['.tsx', '.ts', '.js'].map(ext => base + ext).find(p => fs.existsSync(p));
      return target.endsWith('.js') ? require(target) : load(target);
    } });
    cache.set(file, exports); return exports;
  }
  const { AnnualFinancialsTable } = load(path.join(root, 'components/research/AnnualFinancialsTable.tsx'));
  return require('react-dom/server').renderToStaticMarkup(React.createElement(AnnualFinancialsTable, {
    history: { ...history(rows), ...(annualWindow ? { annual_window: annualWindow } : {}), schema_version: 1, evaluated_at: '2026-09-10T00:00:00Z',
      total_rows: rows.length, available_fact_count: rows.filter(r => r.row_kind === 'fact').length,
      state_count: rows.filter(r => r.row_kind !== 'fact').length }, onSelect() {}, onRefresh() {}, refreshing: false,
  }));
}

test('actual card initially prioritizes overview, research question, chart and gaps, not audit rows', () => {
  const html = renderCard([fact(2024, '391035000000'), fact(2025, '416161000000'),
    { row_kind: 'slot_state', row_key: 'missing-cash', metric_key: 'bs.cash_and_equivalents',
      period_type: 'FY', fiscal_year: 2023, reason_code: 'not_returned', status: 'unavailable' }]);
  assert.match(html, /Operating performance &amp; cash quality/);
  assert.match(html, /\+6.4%/);
  assert.match(html, /Cash and equivalents.*FY2023/);
  assert.match(html, /Show ten-year annual table/);
  assert.doesNotMatch(html, /detail rows|fact:2025|<table/);
  assert.match(html, /Cash conversion/);
});

test('actual card refuses to pick a same-year competing fact for overview', () => {
  const html = renderCard([fact(2024, '100'), fact(2025, '120'), fact(2025, '125', { fact_id: 99, row_key: 'fact:99' })]);
  assert.match(html, /Multiple observations/);
  assert.doesNotMatch(html, /\+20.0%|\+25.0%/);
});

test('undetermined annual window still exposes whole-metric states without expanding detail', () => {
  const html = renderCard([{ row_kind: 'metric_state', row_key: 'blocked-revenue',
    metric_key: 'is.revenue', status: 'unavailable', reason_code: 'candidate_bound_exceeded' }],
  { status: 'undetermined', years: [] });
  assert.match(html, /Annual window undetermined/);
  assert.match(html, /candidate_bound_exceeded/);
  assert.match(html, /disabled=""[^>]*>Show ten-year annual table/);
});
