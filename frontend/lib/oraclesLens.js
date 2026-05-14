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

function formatStoredPercent(value, digits = 1) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '—';
  }
  return `${value.toFixed(digits)}%`;
}

function formatCurrency(value, digits = 0) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '—';
  }
  return `$${formatNumber(value, digits)}`;
}

function titleizeCode(value) {
  const label = String(value ?? 'unknown').toLowerCase().replaceAll('_', ' ');
  return `${label.slice(0, 1).toUpperCase()}${label.slice(1)}`;
}

function changeStatusLabel(value) {
  const labels = {
    new_position: 'New position',
    increased: 'Increased',
    reduced: 'Reduced',
    exited_position: 'Exited',
    unchanged: 'Unchanged',
    cusip_changed: 'Identifier changed',
    no_prior_data: 'No prior data',
    unavailable: 'Unavailable',
  };
  return labels[value] ?? titleizeCode(value);
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
  if (filters.sort) {
    params.set('sort', filters.sort);
  }
  // MVP4-07a: default to the persisted MVP4-03/04/05/06 score path
  // unless the caller explicitly opts out with usePersistedScores=false
  // (kept available for one release as a debug escape hatch in case
  // the canonical scores diverge from the legacy in-memory formula).
  if (filters.usePersistedScores !== false) {
    params.set('use_persisted_scores', 'true');
  }
  return params.toString();
}

function uniquePeriodOptions(periods) {
  if (!Array.isArray(periods)) {
    return [];
  }
  const seenLabels = new Set();
  const options = [];
  for (const period of periods) {
    if (!period || typeof period !== 'object') {
      continue;
    }
    const label = typeof period.label === 'string' ? period.label : '';
    if (!label || seenLabels.has(label)) {
      continue;
    }
    seenLabels.add(label);
    options.push({
      ...period,
      key: label,
      label,
    });
  }
  return options;
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
  const provenance = quality.provenance && typeof quality.provenance === 'object'
    ? quality.provenance
    : {};
  const sourceDocumentIds = Array.isArray(provenance.source_document_ids)
    ? provenance.source_document_ids.filter((id) => typeof id === 'number')
    : [];
  const provenanceFacts = Array.isArray(provenance.facts) ? provenance.facts : [];

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
    primarySourceDocumentId:
      typeof provenance.primary_source_document_id === 'number'
        ? provenance.primary_source_document_id
        : null,
    sourceDocumentIds,
    provenanceFacts,
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

function missingDataReasons(row) {
  const result = [];
  const seenLabels = new Set();
  for (const [source, reasons] of [
    ['quality', row?.quality?.unavailableReasons ?? []],
    ['valuation', row?.valuation?.unavailableReasons ?? []],
  ]) {
    for (const reason of reasons) {
      if (seenLabels.has(reason)) {
        continue;
      }
      seenLabels.add(reason);
      result.push({ key: `${source}:${reason}`, label: reason });
    }
  }
  return result;
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

// MVP5-04: friendly labels for caveat / exclusion rule_codes so the
// drilldown surfaces human-readable strings instead of UPPER_SNAKE
// rule_code identifiers. The raw code stays accessible via a
// <details> element for operator debugging — the goal is investor
// comprehension, not hiding the codes outright. Unmapped codes fall
// back to the raw string so an unknown caveat doesn't blank-render.
const DEMOTION_REASON_LABELS = {
  PARTIAL_COVERAGE: 'Partial filing coverage',
  NT_QUARTER_STREAK_BREAK: 'NT filing broke holding streak',
  PRE_2023_PRE_HISTORY_UNAVAILABLE: 'Pre-2023 history not available',
  AMENDMENTS_PENDING: 'Amendment not yet ingested',
  AMENDMENT_FAILED: 'Amendment ingestion failed',
  HISTORICAL_BACKFILL_NEEDS_VALIDATION: 'Historical data needs validation',
  CONFIDENTIAL_TREATMENT: 'Confidential treatment requested',
  stale_until_recompute: 'Score is stale — recompute needed',
};

// MVP5-04: friendly labels for the MVP5-02 amendment-exclusion
// reason codes so the drilldown can render
// "Holders excluded: amendment not yet ingested" instead of
// "AMENDMENT_PENDING_EXCLUDED".
const EXCLUSION_REASON_LABELS = {
  AMENDMENT_PENDING_EXCLUDED: 'Amendment not yet ingested',
  AMENDMENT_FAILED_EXCLUDED: 'Amendment ingestion failed',
};

function labelForDemotionReason(code) {
  return DEMOTION_REASON_LABELS[code] ?? code;
}

function labelForExclusionReason(code) {
  return EXCLUSION_REASON_LABELS[code] ?? code;
}

function humanizeTier(tier) {
  if (typeof tier !== 'string' || !tier) {
    return null;
  }
  return tier.replaceAll('_', ' ');
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
    // MVP4-07a: surface MVP4-03b's per-item score_source and
    // MVP4-05 / MVP4-01 P2#4's confidence_demotion_reasons so the
    // ranking table can render a "persisted" badge and the drilldown
    // can render "score_confidence is medium because PARTIAL_COVERAGE".
    const rawDemotionReasons = Array.isArray(explanation.confidence_demotion_reasons)
      ? explanation.confidence_demotion_reasons
      : [];
    const confidenceDemotionReasons = rawDemotionReasons
      .filter((entry) => entry && typeof entry === 'object' && typeof entry.code === 'string')
      .map((entry) => ({
        code: entry.code,
        // MVP5-04: friendly investor-facing label resolved via the
        // canonical map. Unmapped codes fall back to the raw code.
        label: labelForDemotionReason(entry.code),
        demotedTo: typeof entry.demoted_to === 'string' ? entry.demoted_to : null,
        // MVP5-04: humanized "medium_confidence" → "medium confidence"
        // so the drilldown copy doesn't leak SQL-shaped vocabulary.
        demotedToLabel: humanizeTier(
          typeof entry.demoted_to === 'string' ? entry.demoted_to : null,
        ),
      }));
    // MVP5-04: surface MVP5-02 ``excluded_holders`` so the drilldown
    // can render "Holders excluded from score" with friendly reason
    // tags. Defensive normalize: drop entries missing the required
    // string fields.
    const rawExcludedHolders = Array.isArray(explanation.excluded_holders)
      ? explanation.excluded_holders
      : [];
    const excludedHolders = rawExcludedHolders
      .filter(
        (entry) =>
          entry
          && typeof entry === 'object'
          && typeof entry.manager_id === 'number'
          && typeof entry.exclusion_reason === 'string',
      )
      .map((entry) => ({
        managerId: entry.manager_id,
        managerCanonicalName:
          typeof entry.manager_canonical_name === 'string'
            ? entry.manager_canonical_name
            : '',
        exclusionReason: entry.exclusion_reason,
        exclusionReasonLabel: labelForExclusionReason(entry.exclusion_reason),
      }));
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
      scoreSource: typeof item.score_source === 'string' ? item.score_source : null,
      confidenceDemotionReasons,
      excludedHolders,
    };
  });
}

function normalizeStockHolderAggregation(payload) {
  const data = payload && typeof payload === 'object' ? payload : {};
  const topHolders = Array.isArray(data.top_holders) ? data.top_holders : [];
  const recentChanges = Array.isArray(data.recent_changes) ? data.recent_changes : [];
  const dataCaveats = Array.isArray(data.data_caveats) ? data.data_caveats : [];
  const reason = data.reason && typeof data.reason === 'object' ? data.reason : {};

  return {
    status: data.status ?? 'unavailable',
    isUnavailable: data.status === 'unavailable',
    hasCaveats:
      data.status === 'available_with_caveat' ||
      (typeof data.attribution_caveat_count === 'number' && data.attribution_caveat_count > 0) ||
      dataCaveats.length > 0,
    stockId: typeof data.stock_id === 'number' ? data.stock_id : null,
    ticker: data.ticker ?? '—',
    exchange: data.exchange ?? '—',
    companyName: data.company_name ?? '—',
    asOfQuarter: data.as_of_quarter ?? null,
    asOfQuarterLabel: data.as_of_quarter ?? '—',
    directHolderCountLabel: formatNumber(data.direct_holder_count, 0),
    valueManagerDirectCountLabel: formatNumber(data.value_manager_direct_count, 0),
    featuredHolderCountLabel: formatNumber(data.featured_holder_count, 0),
    attributionCaveatCountLabel: formatNumber(data.attribution_caveat_count, 0),
    reasonCode: reason.code ?? null,
    reasonMessage: reason.message ?? null,
    topHolders: topHolders.map((item, index) => {
      const manager = item?.manager && typeof item.manager === 'object' ? item.manager : {};
      return {
        key: `${item?.holding_id ?? manager.id ?? 'holder'}:${index}`,
        holdingId: typeof item?.holding_id === 'number' ? item.holding_id : null,
        managerId: typeof manager.id === 'number' ? manager.id : null,
        managerName: manager.display_name ?? manager.canonical_name ?? 'Unknown manager',
        managerType: manager.manager_type ?? 'unknown',
        isFeatured: Boolean(manager.is_featured),
        valueLabel: formatCurrency(item?.value_usd, 0),
        sharesLabel: formatNumber(item?.ssh_prnamt, 0),
        portfolioWeightLabel: formatStoredPercent(item?.portfolio_weight_pct, 1),
        attributionStatus: item?.confidence?.attribution_status ?? 'unknown',
        cusipMappingStatus: item?.confidence?.cusip_mapping_status ?? 'unknown',
        accessionNumber: item?.accession_number ?? null,
      };
    }),
    recentChanges: recentChanges.map((item, index) => {
      const manager = item?.manager && typeof item.manager === 'object' ? item.manager : {};
      return {
        key: `${manager.id ?? 'manager'}:${item?.change_status ?? 'change'}:${index}`,
        managerId: typeof manager.id === 'number' ? manager.id : null,
        managerName: manager.display_name ?? manager.canonical_name ?? 'Unknown manager',
        managerType: manager.manager_type ?? 'unknown',
        isFeatured: Boolean(manager.is_featured),
        changeStatus: item?.change_status ?? 'unavailable',
        changeStatusLabel: changeStatusLabel(item?.change_status),
        confidenceLevel: item?.confidence_level ?? 'unavailable',
        currentValueLabel: formatCurrency(item?.current_value_usd, 0),
        previousValueLabel: formatCurrency(item?.previous_value_usd, 0),
        currentSharesLabel: formatNumber(item?.current_shares, 0),
        previousSharesLabel: formatNumber(item?.previous_shares, 0),
        shareDeltaLabel: formatNumber(item?.share_delta, 0),
        caveatCodes: Array.isArray(item?.caveat_codes) ? item.caveat_codes : [],
      };
    }),
    dataCaveats: dataCaveats.map((item, index) => ({
      key: `${item?.code ?? 'caveat'}:${index}`,
      code: item?.code ?? 'UNKNOWN',
      label: titleizeCode(item?.code),
      message: item?.message ?? '',
    })),
  };
}

module.exports = {
  buildOracleLensQueryParams,
  cautionTone,
  confidenceTone,
  DEMOTION_REASON_LABELS,
  EXCLUSION_REASON_LABELS,
  formatNumber,
  formatPercent,
  formatScore,
  groupCautionFlags,
  humanizeTier,
  labelForDemotionReason,
  labelForExclusionReason,
  missingDataReasons,
  normalizeOracleLensRows,
  normalizeQualityOverlay,
  normalizeStockHolderAggregation,
  normalizeValuationReference,
  primaryCautionFlags,
  radarBubbles,
  suggestedResearchSteps,
  uniquePeriodOptions,
};
