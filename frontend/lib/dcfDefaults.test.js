/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const { resolveDcfDefaults } = require('./dcfDefaults');
const { computeGrowthValue, computeTerminalValue, computeTotalValue } = require('./dcfMath');

test('resolveDcfDefaults prefers normalized OEPS and lowest growth rate option', () => {
  const defaults = resolveDcfDefaults({
    oeps_normalized: 13.883310657596372,
    oeps_series: [
      { year: 2026, value: 24.85185185185185 },
      { year: 2025, value: 18.250629539951575 },
    ],
    growth_rate_options: [
      { key: 'revenues', label: 'Revenues', value: 14.0 },
      { key: 'cash_flow', label: 'Cash Flow', value: 18.0 },
      { key: 'earnings', label: 'Earnings', value: 19.5 },
    ],
  });

  assert.equal(defaults.basedOnSelection, 'norm');
  assert.equal(defaults.basedOnOverride, '13.883');
  assert.equal(defaults.growthRateSelection, 'revenues');
  assert.equal(defaults.growthRate, 14.0);
});

test('resolveDcfDefaults yields ADBE total from stock data instead of static fallback', () => {
  const defaults = resolveDcfDefaults({
    oeps_normalized: 13.883310657596372,
    oeps_series: [
      { year: 2026, value: 24.85185185185185 },
      { year: 2025, value: 18.250629539951575 },
    ],
    growth_rate_options: [
      { key: 'revenues', label: 'Revenues', value: 14.0 },
      { key: 'cash_flow', label: 'Cash Flow', value: 18.0 },
      { key: 'earnings', label: 'Earnings', value: 19.5 },
    ],
  });

  const basedOn = Number(defaults.basedOnOverride);
  const growthValue = computeGrowthValue(basedOn, 10, 10, defaults.growthRate);
  const terminalValue = computeTerminalValue(basedOn, 10, 10, defaults.growthRate, 1000, 4);
  const totalValue = computeTotalValue(growthValue, terminalValue);

  assert.ok(Math.abs(totalValue - 513.7986375501434) < 0.01);
  assert.notEqual(totalValue.toFixed(2), '844.25');
});

test('resolveDcfDefaults falls back to latest OEPS series entry when normalized value is missing', () => {
  const defaults = resolveDcfDefaults({
    oeps_series: [
      { year: 2026, value: 24.85185185185185 },
      { year: 2025, value: 18.250629539951575 },
    ],
    growth_rate_options: [],
  });

  assert.equal(defaults.basedOnSelection, 2026);
  assert.equal(defaults.basedOnOverride, '24.852');
  assert.equal(defaults.growthRateSelection, null);
  assert.equal(defaults.growthRate, null);
});
