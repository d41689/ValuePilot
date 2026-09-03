/* eslint-disable @typescript-eslint/no-require-imports */
const assert = require('node:assert/strict');
const test = require('node:test');

const { formatIsoCurrencyAmount } = require('./currencyFormat');

test('formatIsoCurrencyAmount renders CAD without a misleading dollar symbol', () => {
  assert.equal(formatIsoCurrencyAmount(100, 'CAD'), 'CAD 100.00');
  assert.equal(formatIsoCurrencyAmount(100, 'USD'), 'USD 100.00');
  assert.equal(formatIsoCurrencyAmount(100, null), '100.00');
});
