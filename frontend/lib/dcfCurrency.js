/* eslint-disable @typescript-eslint/no-require-imports */
const { formatIsoCurrencyAmount } = require('./currencyFormat');

const unavailable = (reasonCode) => ({
  status: 'unavailable',
  reason_code: reasonCode,
  value: null,
});

const resolveDcfInputsPayload = (payload, selection) => {
  if (!payload || typeof payload !== 'object') return null;
  if (typeof selection === 'number') {
    const match = Array.isArray(payload.dcf_inputs_series)
      ? payload.dcf_inputs_series.find((entry) => entry?.year === selection)
      : null;
    if (match) return match;
  }
  return payload.dcf_inputs ?? null;
};

const resolveDcfCurrencyState = (payload, selection) => {
  const state = resolveDcfInputsPayload(payload, selection)?.currency_state;
  if (
    state?.status === 'available' &&
    typeof state.currency === 'string' &&
    /^[A-Z]{3}$/.test(state.currency)
  ) {
    return state;
  }
  return state?.status === 'unavailable'
    ? state
    : { status: 'unavailable', reason_code: 'dcf_input_currency_unavailable', currency: null };
};

const formatDcfMoney = (value, currencyState) =>
  currencyState?.status === 'available' && currencyState.currency
    ? formatIsoCurrencyAmount(value, currencyState.currency, 2)
    : 'Unavailable';

const formatDcfExactMoney = (value, currencyState) => {
  if (
    currencyState?.status !== 'available' ||
    !currencyState.currency ||
    typeof value !== 'string'
  ) {
    return 'Unavailable';
  }
  const match = value.trim().match(/^([+-]?)(\d+)(?:\.(\d*))?$/);
  if (!match) return 'Unavailable';
  const [, sign, integerDigits, rawFraction = ''] = match;
  const fraction = rawFraction.padEnd(3, '0');
  let wholeDigits = integerDigits.replace(/^0+(?=\d)/, '');
  let centsValue = Number(fraction.slice(0, 2));
  if (fraction[2] >= '5') centsValue += 1;
  if (centsValue === 100) {
    centsValue = 0;
    const digits = wholeDigits.split('');
    let carry = 1;
    for (let index = digits.length - 1; index >= 0 && carry; index -= 1) {
      const next = Number(digits[index]) + carry;
      digits[index] = String(next % 10);
      carry = next >= 10 ? 1 : 0;
    }
    wholeDigits = `${carry ? '1' : ''}${digits.join('')}`;
  }
  const whole = wholeDigits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const cents = String(centsValue).padStart(2, '0');
  const displaySign = sign === '-' && (wholeDigits !== '0' || centsValue !== 0) ? '-' : '';
  return `${currencyState.currency} ${displaySign}${whole}.${cents}`;
};

const resolveSafeMarginState = ({ currencyState, currentPrice, totalValue }) => {
  if (currencyState?.status !== 'available' || !currencyState.currency) {
    return unavailable(currencyState?.reason_code ?? 'dcf_input_currency_unavailable');
  }
  if (currentPrice?.status !== 'available' || typeof currentPrice.value !== 'number') {
    return unavailable(currentPrice?.reason_code ?? 'price_unavailable');
  }
  if (currentPrice.currency !== currencyState.currency) {
    return unavailable('valuation_price_currency_mismatch');
  }
  if (typeof totalValue !== 'number' || !Number.isFinite(totalValue) || totalValue <= 0) {
    return unavailable('valuation_value_invalid');
  }
  return {
    status: 'available',
    reason_code: null,
    value: 100 * (1 - currentPrice.value / totalValue),
  };
};

module.exports = {
  formatDcfExactMoney,
  formatDcfMoney,
  resolveDcfCurrencyState,
  resolveSafeMarginState,
};
