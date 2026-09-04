/* eslint-disable @typescript-eslint/no-require-imports */
const assert = require('node:assert/strict');
const test = require('node:test');

const { computeGrowthValue, computeTerminalValue } = require('./dcfMath');
const { buildDcfModelPayload } = require('./dcfModel');

const manifest = {
  manifest_version: 'dcf-input-manifest-v1',
  selection: 'norm',
  facts: [],
};

test('buildDcfModelPayload records the gold scenario and every user override', () => {
  const canonicalInputs = {
    net_profit_per_share: '10.000',
    depreciation_per_share: '6.550',
    capital_spending_per_share: '2.000',
    based_on_per_share: '14.550',
  };
  const actualInputs = {
    net_profit_per_share: '11.000',
    depreciation_per_share: '6.550',
    capital_spending_per_share: '2.000',
    based_on_per_share: '15.550',
    discount_rate_pct: 11,
    growth_years: 10,
    growth_rate_pct: 20,
    terminal_years: 10,
    terminal_rate_pct: 4,
  };
  const growth = computeGrowthValue(15.55, 11, 10, 20);
  const terminal = computeTerminalValue(15.55, 11, 10, 20, 10, 4);

  assert.deepEqual(
    buildDcfModelPayload({
      selection: 'norm',
      inputManifest: manifest,
      inputManifestToken: 'token',
      canonicalInputs,
      actualInputs,
      growthRateSelection: 'sales',
      clientResultPerShare: growth + terminal,
    }),
    {
      model_version: 'dcf_model_v1',
      selection: 'norm',
      input_manifest: manifest,
      input_manifest_token: 'token',
      actual_inputs: {
        ...actualInputs,
        discount_rate_pct: '11',
        growth_years: '10',
        growth_rate_pct: '20',
        terminal_years: '10',
        terminal_rate_pct: '4',
      },
      user_override_fields: ['net_profit_per_share', 'based_on_per_share'],
      growth_rate_selection: 'sales',
      client_result_per_share: String(growth + terminal),
    }
  );
});

test('buildDcfModelPayload rejects non-finite and incomplete scenarios', () => {
  const shared = {
    selection: 2025,
    inputManifest: manifest,
    inputManifestToken: 'token',
    canonicalInputs: {
      net_profit_per_share: '10.000',
      depreciation_per_share: '10.000',
      capital_spending_per_share: '2.000',
      based_on_per_share: '18.000',
    },
    actualInputs: {
      net_profit_per_share: '10.000',
      depreciation_per_share: '10.000',
      capital_spending_per_share: '2.000',
      based_on_per_share: '18.000',
      discount_rate_pct: 10,
      growth_years: 10.9,
      growth_rate_pct: 6,
      terminal_years: 100000,
      terminal_rate_pct: 4,
    },
    growthRateSelection: null,
    clientResultPerShare: 700.433543,
  };

  assert.equal(buildDcfModelPayload(shared).actual_inputs.growth_years, '10.9');
  assert.equal(
    buildDcfModelPayload({
      ...shared,
      actualInputs: { ...shared.actualInputs, terminal_rate_pct: Number.NaN },
    }),
    null
  );
  assert.equal(
    buildDcfModelPayload({ ...shared, inputManifestToken: '' }),
    null
  );
});
