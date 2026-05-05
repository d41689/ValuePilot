function formatNumber(value, digits = 2) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '—';
  }
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatScore(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '—';
  }
  return value.toLocaleString('en-US', {
    maximumFractionDigits: 2,
  });
}

function formatPercent(value, digits = 1) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '—';
  }
  return `${(value * 100).toFixed(digits)}%`;
}

function confidenceTone(confidence) {
  if (confidence === 'high') {
    return 'success';
  }
  if (confidence === 'medium') {
    return 'warning';
  }
  return 'secondary';
}

function cautionTone(flag) {
  if (!flag || typeof flag !== 'object') {
    return 'secondary';
  }
  if (flag.severity === 'warning') {
    return 'warning';
  }
  if (flag.severity === 'danger') {
    return 'danger';
  }
  return 'secondary';
}

const CAUTION_GROUP_ORDER = {
  signal_quality: 0,
  conviction: 1,
  data_coverage: 2,
  timing: 3,
  crowding: 4,
};

const CAUTION_SEVERITY_ORDER = {
  danger: 0,
  warning: 1,
  info: 2,
};

function primaryCautionFlags(flags, limit = 2) {
  if (!Array.isArray(flags)) {
    return [];
  }
  return [...flags]
    .sort((a, b) => {
      const severityDelta =
        (CAUTION_SEVERITY_ORDER[a?.severity] ?? 9) -
        (CAUTION_SEVERITY_ORDER[b?.severity] ?? 9);
      if (severityDelta !== 0) {
        return severityDelta;
      }
      return (CAUTION_GROUP_ORDER[a?.group] ?? 9) - (CAUTION_GROUP_ORDER[b?.group] ?? 9);
    })
    .slice(0, limit);
}

function normalizeOracleLensRows(items) {
  if (!Array.isArray(items)) {
    return [];
  }
  return items.map((item) => {
    const explanation = item?.score_explanation && typeof item.score_explanation === 'object'
      ? item.score_explanation
      : {};
    const managerSignalSummary =
      item?.manager_signal_summary && typeof item.manager_signal_summary === 'object'
        ? item.manager_signal_summary
        : {};
    return {
      stockId: item.stock_id,
      ticker: item.ticker ?? '—',
      companyName: item.company_name ?? '—',
      signalScoreLabel: formatScore(item.signal_weighted_consensus_score),
      confidence: item.score_confidence ?? 'low',
      confidenceTone: confidenceTone(item.score_confidence),
      convictionLabel: typeof item.conviction_score === 'number' ? `${item.conviction_score}/100` : '—',
      rawHoldersLabel: formatNumber(item.consensus_count, 0),
      aggregateWeightLabel: formatPercent(item.aggregate_weight),
      addReduceLabel: `${item.adders_count ?? 0} add / ${item.reducers_count ?? 0} reduce`,
      holdingStreakLabel:
        typeof item.median_holding_streak_quarters === 'number'
          ? `${item.median_holding_streak_quarters}Q median`
          : '—',
      reasonChips: Array.isArray(explanation.primary_reasons)
        ? explanation.primary_reasons.slice(0, 2)
        : [],
      negativeReasons: Array.isArray(explanation.negative_reasons)
        ? explanation.negative_reasons
        : [],
      unknownCoverageLabel:
        typeof managerSignalSummary.manager_signal_quality_coverage === 'number'
          ? `${formatPercent(managerSignalSummary.manager_signal_quality_coverage, 0)} typed`
          : '—',
      topHolders: Array.isArray(item.top_holders) ? item.top_holders : [],
      cautionFlags: primaryCautionFlags(item.caution_flags),
    };
  });
}

module.exports = {
  cautionTone,
  confidenceTone,
  formatNumber,
  formatPercent,
  formatScore,
  normalizeOracleLensRows,
  primaryCautionFlags,
};
