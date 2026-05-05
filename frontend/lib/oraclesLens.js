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

function normalizeQualityOverlay(qualityOverlay) {
  const quality = qualityOverlay && typeof qualityOverlay === 'object' ? qualityOverlay : {};
  const coverage = quality.coverage && typeof quality.coverage === 'object' ? quality.coverage : {};
  const unavailableReasons = Array.isArray(quality.unavailable_reasons)
    ? quality.unavailable_reasons
    : [];

  return {
    piotroskiLabel: formatNumber(quality.piotroski_total, 0),
    returnOnCapitalLabel: formatPercent(quality.return_on_total_capital, 0),
    returnOnEquityLabel: formatPercent(quality.return_on_equity, 0),
    netMarginLabel: formatPercent(quality.net_profit_margin, 0),
    debtToCapitalLabel: formatPercent(quality.debt_to_capital, 0),
    ownerEarningsYieldLabel: formatPercent(quality.owner_earnings_yield, 1),
    latestPriceLabel:
      typeof quality.latest_price === 'number' ? `$${formatNumber(quality.latest_price, 2)}` : '—',
    qualityCoverageLabel:
      typeof coverage.available_metrics === 'number' && typeof coverage.expected_metrics === 'number'
        ? `${coverage.available_metrics}/${coverage.expected_metrics} facts`
        : '0/6 facts',
    hasValueLineQuality: Boolean(coverage.value_line),
    hasPrice: Boolean(coverage.price),
    unavailableReasons,
  };
}

function normalizeValuationReference(item) {
  const state = item?.valuation_state && typeof item.valuation_state === 'object'
    ? item.valuation_state
    : {};
  const unavailableReasons = Array.isArray(item?.valuation_unavailable_reasons)
    ? item.valuation_unavailable_reasons
    : [];
  return {
    holderRangeLabel:
      typeof item?.holder_price_estimate_low === 'number' &&
      typeof item?.holder_price_estimate_high === 'number'
        ? `$${formatNumber(item.holder_price_estimate_low, 2)}–$${formatNumber(item.holder_price_estimate_high, 2)}`
        : '—',
    currentPriceLabel: typeof item?.current_price === 'number'
      ? `$${formatNumber(item.current_price, 2)}`
      : '—',
    referenceLabel: typeof item?.valuation_reference === 'number'
      ? `$${formatNumber(item.valuation_reference, 2)}`
      : '—',
    referenceSourceLabel: item?.valuation_reference_label ?? 'Missing valuation reference',
    referenceType: item?.valuation_reference_type ?? 'missing',
    referenceConfidence: item?.valuation_reference_confidence ?? 'unavailable',
    discountLabel: typeof item?.discount_to_reference === 'number'
      ? formatPercent(item.discount_to_reference, 1)
      : '—',
    belowHolderEstimate: Boolean(state.below_holder_estimate),
    belowSelectedReference: Boolean(state.below_selected_valuation_reference),
    unavailableReasons,
  };
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
    const quality = normalizeQualityOverlay(item?.quality_overlay);
    const valuation = normalizeValuationReference(item);
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
      quality,
      valuation,
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
  normalizeQualityOverlay,
  normalizeValuationReference,
  primaryCautionFlags,
};
