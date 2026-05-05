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

function buildOracleLensQueryParams(filters = {}) {
  const params = new URLSearchParams();
  if (filters.period) {
    params.set('period', filters.period);
  }
  if (typeof filters.minHolders === 'number' && Number.isFinite(filters.minHolders)) {
    params.set('min_holders', String(filters.minHolders));
  }
  if (typeof filters.superinvestorOnly === 'boolean') {
    params.set('superinvestor_only', String(filters.superinvestorOnly));
  }
  if (typeof filters.minSignalScore === 'number' && Number.isFinite(filters.minSignalScore)) {
    params.set('min_signal_score', String(filters.minSignalScore));
  }
  return params.toString();
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
    currentPriceDateLabel: item?.current_price_date ?? '—',
    priceContext: item?.price_context ?? 'latest',
    priceContextLabel:
      item?.price_context === 'historical_snapshot' ? 'Historical snapshot' : 'Latest local price',
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

function groupCautionFlags(flags) {
  if (!Array.isArray(flags)) {
    return [];
  }
  const grouped = new Map();
  for (const flag of primaryCautionFlags(flags, flags.length)) {
    const groupKey = flag?.group ?? 'other';
    if (!grouped.has(groupKey)) {
      grouped.set(groupKey, []);
    }
    grouped.get(groupKey).push(flag);
  }
  return [...grouped.entries()].map(([group, groupFlags]) => ({
    group,
    label: group.replaceAll('_', ' '),
    flags: groupFlags,
  }));
}

function suggestedResearchSteps(row) {
  const qualityReasons = row?.quality?.unavailableReasons ?? [];
  const valuationReasons = row?.valuation?.unavailableReasons ?? [];
  const steps = [];
  if (!row?.quality?.hasValueLineQuality || qualityReasons.includes('missing Value Line facts')) {
    steps.push('Locate or upload the latest Value Line report for this company.');
  }
  if (valuationReasons.includes('missing valuation reference')) {
    steps.push('Add or verify a valuation reference before interpreting discount-to-reference.');
  }
  steps.push('Review why high-signal managers added, reduced, or held the position.');
  steps.push('Compare current valuation with normalized owner earnings.');
  steps.push('Record a research note, watchlist decision, or rejection reason.');
  return [...new Set(steps)].slice(0, 5);
}

function percentLabelToNumber(label) {
  if (typeof label !== 'string') {
    return 0;
  }
  const value = Number(label.replace('%', ''));
  return Number.isFinite(value) ? value : 0;
}

function radarBubbles(rows, limit = 12) {
  if (!Array.isArray(rows)) {
    return [];
  }
  return rows.slice(0, limit).map((row) => {
    const weightPercent = percentLabelToNumber(row.aggregateWeightLabel);
    const addMatch = String(row.addReduceLabel ?? '').match(/(\d+)\s+add\s+\/\s+(\d+)\s+reduce/);
    const adders = addMatch ? Number(addMatch[1]) : 0;
    const reducers = addMatch ? Number(addMatch[2]) : 0;
    let sizeClass = 'h-14 w-14';
    if (weightPercent >= 10) {
      sizeClass = 'h-24 w-24';
    } else if (weightPercent >= 5) {
      sizeClass = 'h-20 w-20';
    } else if (weightPercent >= 2) {
      sizeClass = 'h-16 w-16';
    }
    let toneClass = 'border-slate-300 bg-slate-50 text-slate-950';
    if (adders > reducers) {
      toneClass = 'border-emerald-300 bg-emerald-50 text-emerald-950';
    } else if (reducers > adders) {
      toneClass = 'border-amber-300 bg-amber-50 text-amber-950';
    }
    return {
      ...row,
      sizeClass,
      toneClass,
      holderActionLabel: row.addReduceLabel,
    };
  });
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
      cautionGroups: groupCautionFlags(item.caution_flags),
    };
  });
}

module.exports = {
  buildOracleLensQueryParams,
  cautionTone,
  confidenceTone,
  formatNumber,
  formatPercent,
  formatScore,
  groupCautionFlags,
  normalizeOracleLensRows,
  normalizeQualityOverlay,
  normalizeValuationReference,
  primaryCautionFlags,
  radarBubbles,
  suggestedResearchSteps,
};
