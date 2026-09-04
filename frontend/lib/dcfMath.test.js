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

test('DCF preserves the existing 1000-year terminal default without NaN', () => {
  const base = 14.55;
  const discountRatePct = 11;
  const growthYears = 10;
  const growthRatePct = 20;
  const terminalYears = 1000;
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
  assert.ok(Math.abs(totalValue - 700.433543) < 0.000001);
});

test('DCF is stable at bounded near-equal ratio maxima', () => {
  const growth = computeGrowthValue(1_000_000, 1000, 1000, 1000);
  const terminal = computeTerminalValue(
    1_000_000,
    1000,
    1000,
    1000,
    1000,
    999.999
  );
  assert.ok(Math.abs(growth + terminal - 1999545137.709673) < 0.01);
});

test('DCF rejects out-of-schema workloads before iterating', () => {
  assert.equal(Number.isNaN(computeGrowthValue(1, 10, 1001, 6)), true);
  assert.equal(Number.isNaN(computeTerminalValue(1, 10, 1, 6, 100000, 4)), true);
  assert.equal(Number.isNaN(computeGrowthValue(1, 1000.001, 10, 6)), true);
  assert.equal(Number.isNaN(computeGrowthValue(1_000_000.001, 10, 10, 6)), true);
});
