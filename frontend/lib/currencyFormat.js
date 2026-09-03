function formatIsoCurrencyAmount(value, currency, digits = 2) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return '—';
  }
  const normalizedCurrency = String(currency ?? '').trim().toUpperCase();
  const amount = parsed.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return /^[A-Z]{3}$/.test(normalizedCurrency)
    ? `${normalizedCurrency} ${amount}`
    : amount;
}

module.exports = { formatIsoCurrencyAmount };
