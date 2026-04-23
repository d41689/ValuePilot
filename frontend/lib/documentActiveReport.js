function formatActiveReportTickers(tickers, max = 3) {
  if (!Array.isArray(tickers) || tickers.length === 0) {
    return 'Not active for any company';
  }
  if (tickers.length <= max) {
    return `Active for ${tickers.join(', ')}`;
  }
  const shown = tickers.slice(0, max);
  return `Active for ${shown.join(', ')} (+${tickers.length - max})`;
}

function getActiveReportBadgeLabel(isActiveReport) {
  return isActiveReport ? 'Active Report' : 'Historical';
}

module.exports = {
  formatActiveReportTickers,
  getActiveReportBadgeLabel,
};
