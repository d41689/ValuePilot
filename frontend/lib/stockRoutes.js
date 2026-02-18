const normalizeTicker = (value) => {
  if (!value) {
    return '';
  }
  return value.trim().toUpperCase();
};

const buildStockRoute = (ticker, view) => {
  const normalized = normalizeTicker(ticker);
  if (!normalized) {
    return '';
  }
  const target = view === 'dcf' ? 'dcf' : 'summary';
  return `/stocks/${encodeURIComponent(normalized)}/${target}`;
};

module.exports = { buildStockRoute, normalizeTicker };
