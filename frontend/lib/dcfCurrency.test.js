/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  formatDcfMoney,
  resolveDcfCurrencyState,
  resolveSafeMarginState,
} = require('./dcfCurrency');

const available = (currency) => ({
  status: 'available',
  reason_code: null,
  currency,
  provenance: [],
});

test('DCF renders its validated ISO currency without a dollar assumption', () => {
  assert.equal(formatDcfMoney(1234.5, available('DKK')), 'DKK 1,234.50');
  assert.equal(formatDcfMoney(1234.5, available('EUR')), 'EUR 1,234.50');
  assert.equal(formatDcfMoney(1234.5, available('TWD')), 'TWD 1,234.50');
});

test('DCF currency selection follows the selected input set', () => {
  const payload = {
    dcf_inputs: { currency_state: available('EUR') },
    dcf_inputs_series: [
      { year: 2025, currency_state: available('DKK') },
    ],
  };
  assert.deepEqual(resolveDcfCurrencyState(payload, 'norm'), available('EUR'));
  assert.deepEqual(resolveDcfCurrencyState(payload, 2025), available('DKK'));
});

test('safe margin requires two available values in the exact same currency', () => {
  const matching = resolveSafeMarginState({
      currencyState: available('EUR'),
      currentPrice: { status: 'available', value: 80, currency: 'EUR' },
      totalValue: 100,
    });
  assert.equal(matching.status, 'available');
  assert.equal(matching.reason_code, null);
  assert.ok(Math.abs(matching.value - 20) < 1e-9);
  for (const currency of ['DKK', 'EUR', 'TWD']) {
    assert.deepEqual(
      resolveSafeMarginState({
        currencyState: available(currency),
        currentPrice: { status: 'available', value: 80, currency: 'USD' },
        totalValue: 100,
      }),
      { status: 'unavailable', reason_code: 'valuation_price_currency_mismatch', value: null }
    );
  }
});

test('safe margin preserves typed DCF and price blockers', () => {
  assert.equal(
    resolveSafeMarginState({
      currencyState: { status: 'unavailable', reason_code: 'dcf_input_currency_invalid' },
      currentPrice: { status: 'available', value: 80, currency: 'USD' },
      totalValue: 100,
    }).reason_code,
    'dcf_input_currency_invalid'
  );
  assert.equal(
    resolveSafeMarginState({
      currencyState: available('USD'),
      currentPrice: { status: 'unavailable', reason_code: 'price_currency_unavailable' },
      totalValue: 100,
    }).reason_code,
    'price_currency_unavailable'
  );
});
