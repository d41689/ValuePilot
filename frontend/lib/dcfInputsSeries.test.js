/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const { resolveDcfComponentInputs } = require('./dcfInputsSeries');

test('resolveDcfComponentInputs uses series values for selected year', () => {
  const payload = {
    dcf_inputs: {
      net_profit_per_share: { value: 1.111, source: 'fact' },
      depreciation_per_share: { value: 2.222, source: 'fact' },
      capital_spending_per_share: { value: 3.333, source: 'fact' },
    },
    dcf_inputs_series: [
      {
        year: 2026,
        net_profit_per_share: { value: 10, source: 'fact' },
        depreciation_per_share: { value: 20, source: 'fact' },
        capital_spending_per_share: { value: 30, source: 'fact' },
      },
      {
        year: 2025,
        net_profit_per_share: { value: 11, source: 'fact' },
        depreciation_per_share: { value: 21, source: 'fact' },
        capital_spending_per_share: { value: 31, source: 'fact' },
      },
    ],
  };

  assert.deepEqual(resolveDcfComponentInputs(payload, 2025), {
    netProfitPerShare: '11.000',
    depreciationPerShare: '21.000',
    capexPerShare: '31.000',
  });
});

test('resolveDcfComponentInputs falls back to current dcf_inputs for norm selection', () => {
  const payload = {
    dcf_inputs: {
      net_profit_per_share: { value: 1.111, source: 'fact' },
      depreciation_per_share: { value: 2.222, source: 'fact' },
      capital_spending_per_share: { value: 3.333, source: 'fact' },
    },
    dcf_inputs_series: [],
  };

  assert.deepEqual(resolveDcfComponentInputs(payload, 'norm'), {
    netProfitPerShare: '1.111',
    depreciationPerShare: '2.222',
    capexPerShare: '3.333',
  });
});

test('resolveDcfComponentInputs keeps based-on components aligned for norm selection', () => {
  const payload = {
    dcf_inputs: {
      net_profit_per_share: { value: 11.25, source: 'fact' },
      depreciation_per_share: { value: 2.195945945945946, source: 'computed' },
      capital_spending_per_share: { value: 8.75, source: 'fact' },
    },
    dcf_inputs_series: [
      {
        year: 2026,
        net_profit_per_share: { value: 11.25, source: 'fact' },
        depreciation_per_share: { value: 2.195945945945946, source: 'computed' },
        capital_spending_per_share: { value: 8.75, source: 'fact' },
      },
      {
        year: 2025,
        net_profit_per_share: { value: 10.6, source: 'fact' },
        depreciation_per_share: { value: 1.8333333333333333, source: 'computed' },
        capital_spending_per_share: { value: 7.15, source: 'fact' },
      },
    ],
  };

  const resolved = resolveDcfComponentInputs(payload, 'norm');
  const basedOn =
    Number(resolved.netProfitPerShare) +
    Number(resolved.depreciationPerShare) -
    Number(resolved.capexPerShare);

  assert.deepEqual(resolved, {
    netProfitPerShare: '11.250',
    depreciationPerShare: '2.196',
    capexPerShare: '8.750',
  });
  assert.ok(Math.abs(basedOn - 4.696) < 0.001);
});
