/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const { computeGrowthValue, computeTerminalValue, computeTotalValue } = require('./dcfMath');

test('DCF example matches expected values', () => {
  const base = 14.55;
  const discountRatePct = 11;
  const growthYears = 10;
  const growthRatePct = 20;
  const terminalYears = 10;
  const terminalRatePct = 4;

  const growthValue = computeGrowthValue(base, discountRatePct, growthYears, growthRatePct);
  const terminalValue = computeTerminalValue(
    base,
    discountRatePct,
    growthYears,
    growthRatePct,
    terminalYears,
    terminalRatePct
  );
  const totalValue = computeTotalValue(growthValue, terminalValue);

  assert.ok(Math.abs(growthValue - 229.04) < 0.01);
  assert.ok(Math.abs(terminalValue - 225.65) < 0.01);
  assert.ok(Math.abs(totalValue - 454.69) < 0.01);
});

test('DCF handles very large terminal years without NaN', () => {
  const base = 14.55;
  const discountRatePct = 11;
  const growthYears = 10;
  const growthRatePct = 20;
  const terminalYears = 100000;
  const terminalRatePct = 4;

  const growthValue = computeGrowthValue(base, discountRatePct, growthYears, growthRatePct);
  const terminalValue = computeTerminalValue(
    base,
    discountRatePct,
    growthYears,
    growthRatePct,
    terminalYears,
    terminalRatePct
  );
  const totalValue = computeTotalValue(growthValue, terminalValue);

  assert.ok(Number.isFinite(growthValue));
  assert.ok(Number.isFinite(terminalValue));
  assert.ok(Number.isFinite(totalValue));
});
