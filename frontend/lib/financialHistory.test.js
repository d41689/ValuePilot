/* eslint-disable @typescript-eslint/no-require-imports */
const assert = require('node:assert/strict');
const test = require('node:test');
const { formatFinancialValue, annualCells, pageRows, sameEvidenceIdentity, secEvidencePath, readFinancialEvidence, inputEvidenceFilings } = require('./financialHistory');

test('evidence links include only explicitly bound input filings, not the whole run', () => {
  const filings = [{ accession: 'unrelated' }, { accession: 'direct' }, { accession: 'nested' }];
  assert.deepEqual(inputEvidenceFilings({ filings, inputs: [
    { accession: 'direct' }, { inputs: [{ accession: 'nested' }, { accession: 'direct' }] },
  ] }), [filings[1], filings[2]]);
  assert.deepEqual(inputEvidenceFilings({ filings, inputs: [] }), []);
  const leaf = { accession: 'child-run', form: '10-Q', sec_url: 'https://www.sec.gov/Archives/child.htm' };
  assert.deepEqual(inputEvidenceFilings({ filings, inputs: [{ inputs: [{ statement: leaf }] }] }), [leaf]);
});

function fact(id, overrides = {}) {
  return { row_kind: 'fact', row_key: `fact:${id}`, fact_id: id, publication_id: id + 1000,
    metric_key: 'is.revenue', fiscal_year: 2025, period_type: 'FY', period_basis: 'duration',
    period_start: '2024-09-29', period_end: '2025-09-27', unit: 'currency', currency: 'USD',
    value_numeric_exact: '9007199254740993.000000000001', fact_nature: 'actual',
    source_type: 'sec', source_role: 'primary_as_filed_actual', ...overrides };
}

test('decimal string formatting keeps evidence precision beyond JS Number', () => {
  const row = fact(1);
  assert.deepEqual(formatFinancialValue(row), {
    status: 'display_value', text: '9,007,199,254.74', unitLabel: 'million USD',
    exact: '9007199254740993.000000000001',
  });
  assert.equal(row.value_numeric_exact, '9007199254740993.000000000001');
  assert.equal(formatFinancialValue(fact(1, { value_numeric_exact: '-12715000000' })).text, '-12,715.00');
  assert.equal(formatFinancialValue(fact(1, { value_numeric_exact: '1050000' })).text, '1.05');
  assert.equal(formatFinancialValue(fact(1, { value_numeric_exact: '1005000' })).text, '1.01');
});

test('null, zero, small nonzero and invalid numeric are different states', () => {
  for (const exact of [null, undefined]) {
    assert.equal(formatFinancialValue(fact(1, { value_numeric_exact: exact })).status, 'no_numeric_value');
  }
  for (const exact of ['', ' ', 'NaN', '1e12', '1,000', 123]) {
    assert.equal(formatFinancialValue(fact(1, { value_numeric_exact: exact })).status, 'invalid_numeric');
  }
  assert.equal(formatFinancialValue(fact(1, { value_numeric_exact: '0.000000000000' })).text, '0.00');
  assert.equal(formatFinancialValue(fact(1, { value_numeric_exact: '1.000000000001' })).text, '<0.01');
  assert.equal(formatFinancialValue(fact(1, { value_numeric_exact: '-1.000000000001' })).text, '>-0.01');
  assert.equal(formatFinancialValue(fact(1, { currency: null })).unitLabel, 'million · currency unknown');
  assert.equal(formatFinancialValue(fact(1, { unit: 'shares', currency: null })).unitLabel, 'million shares');
});

test('annual cells preserve all identities and keep unknown/forecast/quarter outside actual cells', () => {
  const rows = [fact(1), fact(2, { source_type: 'parsed', source_role: 'value_line_adjusted_actual' }),
    fact(3, { period_start: '2025-01-01' }), fact(4, { period_basis: 'instant', period_start: null }),
    fact(5, { fact_nature: 'estimate' }), fact(6, { fiscal_year: null }), fact(7, { period_type: 'Q' })];
  const history = { annual_window: { status: 'determined', years: [2025] }, rows };
  const pivot = annualCells(history);
  assert.deepEqual(pivot.cells['is.revenue'][2025].observations.map(row => row.fact_id), [1, 2, 3, 4]);
  assert.deepEqual(pivot.otherRows.map(row => row.fact_id), [5, 6, 7]);
  assert.deepEqual(annualCells({ ...history, rows: [...rows].reverse() }), pivot);
});

test('server missing states are reused without client synthetic rows', () => {
  const missing = { row_kind: 'slot_state', row_key: 'expected:66:bs.cash_and_equivalents:FY:2016:not_returned',
    metric_key: 'bs.cash_and_equivalents', period_type: 'FY', fiscal_year: 2016, reason_code: 'not_returned' };
  const metricState = { row_kind: 'metric_state', row_key: 'metric:x', metric_key: 'is.net_income' };
  const cycle = { row_kind: 'filing_cycle_state', row_key: 'cycle:1', metric_key: null };
  const result = annualCells({ annual_window: { status: 'determined', years: [2016, 2017] }, rows: [missing, metricState, cycle] });
  assert.deepEqual(result.cells['bs.cash_and_equivalents'][2016].states, [missing]);
  assert.deepEqual(result.cells['bs.cash_and_equivalents'][2017].states, []);
  assert.deepEqual(result.metricStates['is.net_income'], [metricState]);
  assert.deepEqual(result.cycleStates, [cycle]);
});

test('all 330 records across three metrics paginate 50 at a time with exact union', () => {
  const rows = Array.from({ length: 330 }, (_, i) => fact(i + 1, { metric_key: `key.${Math.floor(i / 110)}` }));
  const pages = Array.from({ length: 7 }, (_, i) => pageRows(rows, i + 1));
  assert.deepEqual(pages.map(p => p.rows.length), [50, 50, 50, 50, 50, 50, 30]);
  assert.deepEqual(pages.flatMap(p => p.rows.map(r => r.row_key)), rows.map(r => r.row_key));
  assert.equal(pages[6].end, 330);
  assert.equal(pageRows(rows, 100).page, 7);
  assert.deepEqual(pageRows([], 7), { page: 1, pageCount: 1, start: 0, end: 0, total: 0, rows: [] });
});

test('evidence binds exact fact/publication/value/period/units and never uses a prefixed API path', () => {
  const row = fact(1);
  const evidence = { metric_fact_id: 1, publication_id: 1001, metric_key: row.metric_key,
    value_numeric_exact: row.value_numeric_exact, unit: 'currency', currency: 'USD',
    period: { type: 'FY', basis: 'duration', start: row.period_start, end: row.period_end, fiscal_year: 2025, fiscal_quarter: null },
    source_role: row.source_role, fact_nature: 'actual' };
  assert.equal(sameEvidenceIdentity(row, evidence), true);
  for (const change of [{ metric_fact_id: 2 }, { publication_id: 1002 }, { unit: 'shares' },
    { value_numeric_exact: '9007199254740993.000000000002' }, { currency: 'CAD' }, { fact_nature: 'estimate' },
    { period: { ...evidence.period, end: '2025-12-31' } }]) {
    assert.equal(sameEvidenceIdentity(row, { ...evidence, ...change }), false);
  }
  assert.equal(secEvidencePath(66, row), '/stocks/66/sec-publications/1001/evidence');
  const axios = require('axios');
  for (const baseURL of ['/api/v1', 'https://example.invalid/api/v1']) {
    assert.equal(axios.create({ baseURL }).getUri({ url: secEvidencePath(66, row), params: { fact_id: 1 } }),
      `${baseURL}/stocks/66/sec-publications/1001/evidence?fact_id=1`);
  }
});

test('evidence request clears data on 401/403/404, typed unavailable, mismatch and cancellation', async () => {
  const row = fact(1);
  for (const [status, code] of [[401, 'authentication_required'], [403, 'source_unavailable'], [404, 'evidence_unavailable']]) {
    const client = { get: async () => { throw { response: { status } }; } };
    assert.deepEqual(await readFinancialEvidence(client, 66, row), { error: code });
  }
  const unavailable = { get: async () => ({ data: { evidence_state: 'unavailable', evidence_reason_code: 'evidence_locator_unavailable', inputs: [{ raw_value: 'stale' }] } }) };
  assert.deepEqual(await readFinancialEvidence(unavailable, 66, row), { error: 'evidence_locator_unavailable' });
  assert.deepEqual(await readFinancialEvidence({ get: async () => ({ data: { evidence_state: 'available', metric_fact_id: 999 } }) }, 66, row), { error: 'evidence_identity_mismatch' });
  const controller = new AbortController();
  controller.abort();
  assert.deepEqual(await readFinancialEvidence(unavailable, 66, row, controller.signal), { cancelled: true });
});

test('financial evidence uses the actual auth client 401 refresh and retries the same identity', async () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const vm = require('node:vm');
  const ts = require('typescript');
  const axios = require('axios');
  const row = fact(1);
  const data = { ...row, metric_fact_id: row.fact_id, evidence_state: 'available',
    period: { type: row.period_type, basis: row.period_basis, start: row.period_start,
      end: row.period_end, fiscal_year: row.fiscal_year, fiscal_quarter: null } };
  const values = new Map([['vp_access_token', 'test-expired-access'], ['vp_refresh_token', 'test-refresh']]);
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key) };
  const requests = [];
  let refreshes = 0;
  // Actual client interceptors, isolated transport: no HTTP and no real tokens.
  const transport = {
    create: config => axios.create({ ...config, adapter: async request => {
      requests.push({ url: request.url, fact_id: request.params.fact_id, authorization: request.headers.get('Authorization') });
      if (requests.length === 1) {
        throw new axios.AxiosError('expired', 'ERR_BAD_REQUEST', request, null,
          { status: 401, statusText: 'Unauthorized', headers: {}, config: request, data: {} });
      }
      return { data, status: 200, statusText: 'OK', headers: {}, config: request };
    } }),
    post: async (url, body) => {
      assert.equal(url, '/api/v1/auth/refresh');
      assert.equal(body.refresh_token, 'test-refresh');
      refreshes += 1;
      return { data: { access_token: 'test-renewed-access', refresh_token: 'test-renewed-refresh' } };
    },
  };
  const moduleRecord = { exports: {} };
  const source = fs.readFileSync(path.join(__dirname, 'api/client.ts'), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  vm.runInNewContext(compiled, {
    exports: moduleRecord.exports, module: moduleRecord,
    require: name => {
      if (name === 'axios') return { ...axios, default: transport, __esModule: true };
      if (name === '@/lib/authSession') return require('./authSession');
      throw new Error(`Unexpected client dependency: ${name}`);
    },
    window: { localStorage: storage, location: { pathname: '/research/cases/2', protocol: 'http:' } },
    document: { cookie: '' }, process: { env: {} },
  });
  const result = await readFinancialEvidence(moduleRecord.exports.default, 66, row);
  assert.equal(result.evidence, data);
  assert.equal(refreshes, 1);
  assert.deepEqual(requests, [
    { url: secEvidencePath(66, row), fact_id: 1, authorization: 'Bearer test-expired-access' },
    { url: secEvidencePath(66, row), fact_id: 1, authorization: 'Bearer test-renewed-access' },
  ]);
  assert.equal(values.get('vp_refresh_token'), 'test-renewed-refresh');
});
