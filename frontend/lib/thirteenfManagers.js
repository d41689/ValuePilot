const VALUE_STYLES = ['value_deep', 'value_concentrated', 'quality_compounder'];

function titleizeCode(value) {
  return String(value ?? 'unknown')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function normalizeManager(item) {
  const value = item && typeof item === 'object' ? item : {};
  const latest = value.latest_filing && typeof value.latest_filing === 'object'
    ? value.latest_filing
    : null;
  return {
    id: Number(value.id),
    displayName: value.display_name ?? value.canonical_name ?? 'Unknown manager',
    canonicalName: value.canonical_name ?? value.display_name ?? 'Unknown manager',
    cik: value.cik ?? null,
    managerType: value.manager_type ?? 'unknown',
    stylePrimary: value.style_primary ?? 'unknown',
    capitalStructure: value.capital_structure ?? 'unknown',
    marketCapFocus: value.market_cap_focus ?? null,
    geoFocus: value.geo_focus ?? null,
    historicalTurnover: value.historical_turnover ?? null,
    ideologyTags: Array.isArray(value.ideology_tags) ? value.ideology_tags : [],
    classificationRationale: value.classification_rationale ?? null,
    isFeatured: Boolean(value.is_featured),
    latestFiling: latest
      ? {
          quarter: latest.quarter ?? null,
          quarterEndDate: latest.quarter_end_date ?? null,
          formType: latest.form_type ?? null,
          status: latest.status ?? 'unavailable',
          acceptedAt: latest.accepted_at ?? null,
        }
      : null,
  };
}

function normalizeManagers(items) {
  return (Array.isArray(items) ? items : [])
    .map(normalizeManager)
    .filter((item) => Number.isFinite(item.id));
}

function managerMatchesScope(manager, scope) {
  if (scope === 'all') return true;
  if (VALUE_STYLES.includes(manager.stylePrimary)) return true;
  return scope === 'value_plus_activist' && manager.stylePrimary === 'activist';
}

function filterManagers(managers, filters = {}) {
  const scope = filters.scope ?? 'value';
  const style = filters.style ?? 'all';
  const search = String(filters.search ?? '').trim().toLowerCase();
  return (Array.isArray(managers) ? managers : [])
    .filter((manager) => managerMatchesScope(manager, scope))
    .filter((manager) => style === 'all' || manager.stylePrimary === style)
    .filter((manager) => {
      if (!search) return true;
      return [manager.displayName, manager.canonicalName, manager.cik, ...manager.ideologyTags]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(search));
    })
    .sort((left, right) => {
      const leftLatest = left.latestFiling?.quarter ?? '';
      const rightLatest = right.latestFiling?.quarter ?? '';
      return (
        Number(right.isFeatured) - Number(left.isFeatured) ||
        rightLatest.localeCompare(leftLatest) ||
        left.displayName.localeCompare(right.displayName)
      );
    });
}

function normalizeQuarters(items) {
  return (Array.isArray(items) ? items : []).map((item) => ({
    quarter: item?.quarter ?? null,
    quarterEndDate: item?.quarter_end_date ?? null,
    status: item?.status ?? 'unavailable',
    filing: item?.filing ?? null,
    caveats: Array.isArray(item?.caveats) ? item.caveats : [],
  }));
}

function normalizePosition(item) {
  const stock = item?.stock && typeof item.stock === 'object' ? item.stock : {};
  const weight = item?.portfolio_weight_pct && typeof item.portfolio_weight_pct === 'object'
    ? item.portfolio_weight_pct
    : {};
  const market = item?.market_context && typeof item.market_context === 'object'
    ? item.market_context
    : null;
  return {
    id: Number(item?.id),
    positionRank: Number(item?.position_rank) || null,
    stockId: typeof stock.id === 'number' ? stock.id : null,
    ticker: stock.ticker ?? null,
    companyName: stock.company_name ?? item?.issuer_name ?? 'Unknown security',
    issuerName: item?.issuer_name ?? stock.company_name ?? 'Unknown security',
    titleOfClass: item?.title_of_class ?? null,
    valueUsd: typeof item?.value_usd === 'number' ? item.value_usd : null,
    shares: typeof item?.ssh_prnamt === 'number' ? item.ssh_prnamt : null,
    shareType: item?.ssh_prnamt_type ?? null,
    putCall: item?.put_call ?? null,
    weightPct: typeof weight.value === 'number' ? weight.value : null,
    weightUnavailableReason: weight.unavailable_reason ?? null,
    holdingStreakQuarters:
      typeof item?.holding_streak_quarters === 'number' ? item.holding_streak_quarters : null,
    constituentRowCount: Number(item?.constituent_row_count) || 1,
    cusips: Array.isArray(item?.cusips) ? item.cusips : item?.cusip ? [item.cusip] : [],
    mappingStatus: item?.cusip_mapping_status ?? 'unknown',
    impliedReportPrice:
      typeof item?.implied_report_price === 'number' ? item.implied_report_price : null,
    marketContext: market
      ? {
          status: market.status ?? 'unavailable',
          reasonCode: market.reason_code ?? null,
          latestPrice: typeof market.latest_price === 'number' ? market.latest_price : null,
          latestPriceDate: market.latest_price_date ?? null,
          changeSinceReportPct:
            typeof market.change_since_report_pct === 'number'
              ? market.change_since_report_pct
              : null,
          week52Low: typeof market.week_52_low === 'number' ? market.week_52_low : null,
          week52High: typeof market.week_52_high === 'number' ? market.week_52_high : null,
          source: market.source ?? null,
          currency: market.currency ?? null,
          freshnessState: market.freshness_state ?? 'unknown_freshness',
          sourceAuthorizationState: market.source_authorization_state ?? 'unavailable',
        }
      : null,
  };
}

function normalizeManagerHoldings(payload) {
  const data = payload && typeof payload === 'object' ? payload : {};
  const summary = data.summary && typeof data.summary === 'object' ? data.summary : {};
  return {
    status: data.status ?? 'unavailable',
    reason: data.reason ?? null,
    quarter: data.quarter ?? null,
    quarterEndDate: data.quarter_end_date ?? null,
    filing: data.filing ?? null,
    caveats: Array.isArray(data.caveats) ? data.caveats : [],
    summary: {
      commonPositionCount: Number(summary.common_position_count) || 0,
      reportedCommonValueUsd:
        typeof summary.reported_common_value_usd === 'number'
          ? summary.reported_common_value_usd
          : null,
    },
    commonHoldings: (Array.isArray(data.common_holdings) ? data.common_holdings : []).map(normalizePosition),
    options: (Array.isArray(data.options) ? data.options : []).map(normalizePosition),
  };
}

function normalizeManagerChangeItem(item) {
    const stock = item?.stock && typeof item.stock === 'object' ? item.stock : {};
    const currentWeight = typeof item?.current_portfolio_weight_pct === 'number'
      ? item.current_portfolio_weight_pct
      : null;
    const previousWeight = typeof item?.previous_portfolio_weight_pct === 'number'
      ? item.previous_portfolio_weight_pct
      : null;
    const changeStatus = item?.change_status ?? 'unavailable';
    const currentValue = typeof item?.current_value_usd === 'number' ? item.current_value_usd : null;
    const previousValue = typeof item?.previous_value_usd === 'number' ? item.previous_value_usd : null;
    const currentShares = typeof item?.current_shares === 'number' ? item.current_shares : null;
    const previousShares = typeof item?.previous_shares === 'number' ? item.previous_shares : null;
    const explicitValueDelta = typeof item?.value_delta_usd === 'number' ? item.value_delta_usd : null;
    const explicitShareDelta = typeof item?.share_delta === 'number' ? item.share_delta : null;
    const normalized = {
      id: Number(item?.id),
      reportQuarter: item?.report_quarter ?? null,
      quarterEndDate: item?.quarter_end_date ?? null,
      previousReportQuarter: item?.previous_report_quarter ?? null,
      ticker: stock.ticker ?? null,
      companyName: stock.company_name ?? 'Unresolved security',
      stockId: typeof stock.id === 'number' ? stock.id : null,
      changeStatus,
      confidenceLevel: item?.confidence_level ?? 'unavailable',
      isPrimarySignalEligible: Boolean(item?.is_primary_signal_eligible),
      caveatCodes: Array.isArray(item?.caveat_codes) ? item.caveat_codes : [],
      unavailableReason: item?.unavailable_reason ?? null,
      currentValueUsd: currentValue,
      previousValueUsd: previousValue,
      valueDeltaUsd:
        explicitValueDelta ??
        (changeStatus === 'new_position' ? currentValue : null) ??
        (changeStatus === 'exited_position' && previousValue !== null ? -previousValue : null),
      currentShares,
      previousShares,
      shareDelta:
        explicitShareDelta ??
        (changeStatus === 'new_position' ? currentShares : null) ??
        (changeStatus === 'exited_position' && previousShares !== null ? -previousShares : null),
      shareChangePct: typeof item?.share_change_pct === 'number' ? item.share_change_pct : null,
      currentWeightPct: currentWeight,
      previousWeightPct: previousWeight,
      weightDeltaPct:
        currentWeight !== null && previousWeight !== null
          ? currentWeight - previousWeight
          : null,
    };
    if (
      normalized.changeStatus === 'exited_position' &&
      normalized.previousWeightPct !== null
    ) {
      normalized.portfolioImpactPct = Math.abs(normalized.previousWeightPct);
    } else if (
      normalized.changeStatus === 'new_position' &&
      normalized.currentWeightPct !== null
    ) {
      normalized.portfolioImpactPct = Math.abs(normalized.currentWeightPct);
    } else if (
      normalized.shareDelta !== null &&
      normalized.currentShares &&
      normalized.currentWeightPct !== null
    ) {
      normalized.portfolioImpactPct = Math.abs(
        (normalized.shareDelta / normalized.currentShares) * normalized.currentWeightPct,
      );
    } else {
      normalized.portfolioImpactPct = null;
    }
    return normalized;
}

function normalizeManagerChanges(payload) {
  const data = payload && typeof payload === 'object' ? payload : {};
  const items = (Array.isArray(data.items) ? data.items : []).map(normalizeManagerChangeItem);
  items.sort((left, right) => {
    const leftMagnitude = Math.abs(left.weightDeltaPct ?? left.valueDeltaUsd ?? 0);
    const rightMagnitude = Math.abs(right.weightDeltaPct ?? right.valueDeltaUsd ?? 0);
    return rightMagnitude - leftMagnitude || String(left.ticker ?? '').localeCompare(String(right.ticker ?? ''));
  });
  return {
    status: data.status ?? 'unavailable',
    reason: data.reason ?? null,
    items,
  };
}

function normalizeManagerHistory(payload) {
  const data = payload && typeof payload === 'object' ? payload : {};
  return {
    status: data.status ?? 'unavailable',
    reason: data.reason ?? null,
    quarters: (Array.isArray(data.quarters) ? data.quarters : []).map((item) => {
      const concentration = item?.concentration && typeof item.concentration === 'object'
        ? item.concentration
        : {};
      return {
        quarter: item?.quarter ?? null,
        quarterEndDate: item?.quarter_end_date ?? null,
        status: item?.status ?? 'unavailable',
        filing: item?.filing ?? null,
        caveats: Array.isArray(item?.caveats) ? item.caveats : [],
        reportedCommonValueUsd:
          typeof item?.reported_common_value_usd === 'number'
            ? item.reported_common_value_usd
            : null,
        commonPositionCount:
          typeof item?.common_position_count === 'number' ? item.common_position_count : null,
        optionPositionCount: Number(item?.option_position_count) || 0,
        concentration: {
          top1Pct: typeof concentration.top_1_pct === 'number' ? concentration.top_1_pct : null,
          top5Pct: typeof concentration.top_5_pct === 'number' ? concentration.top_5_pct : null,
          top10Pct: typeof concentration.top_10_pct === 'number' ? concentration.top_10_pct : null,
        },
        topHoldings: (Array.isArray(item?.top_holdings) ? item.top_holdings : []).map(normalizePosition),
      };
    }),
    activity: (Array.isArray(data.activity) ? data.activity : []).map(normalizeManagerChangeItem),
  };
}

function normalizeManagerPositionHistory(payload) {
  const data = payload && typeof payload === 'object' ? payload : {};
  const stock = data.stock && typeof data.stock === 'object' ? data.stock : {};
  return {
    status: data.status ?? 'unavailable',
    reason: data.reason ?? null,
    manager: normalizeManager(data.manager),
    stock: {
      id: Number(stock.id),
      ticker: stock.ticker ?? null,
      companyName: stock.company_name ?? 'Unknown security',
      exchange: stock.exchange ?? null,
    },
    items: (Array.isArray(data.items) ? data.items : []).map((item) => ({
      quarter: item?.quarter ?? null,
      quarterEndDate: item?.quarter_end_date ?? null,
      shares: typeof item?.shares === 'number' ? item.shares : null,
      portfolioWeightPct:
        typeof item?.portfolio_weight_pct === 'number' ? item.portfolio_weight_pct : null,
      reportedValueUsd:
        typeof item?.reported_value_usd === 'number' ? item.reported_value_usd : null,
      impliedReportPrice:
        typeof item?.implied_report_price === 'number' ? item.implied_report_price : null,
      activity: item?.activity ? normalizeManagerChangeItem(item.activity) : null,
      caveats: Array.isArray(item?.caveats) ? item.caveats : [],
    })),
  };
}

function filterManagerActivity(items, view) {
  const rows = Array.isArray(items) ? items : [];
  if (view === 'buys') {
    return rows.filter((item) => ['new_position', 'increased'].includes(item.changeStatus));
  }
  if (view === 'sells') {
    return rows.filter((item) => ['reduced', 'exited_position'].includes(item.changeStatus));
  }
  return rows.filter((item) =>
    ['new_position', 'increased', 'reduced', 'exited_position'].includes(item.changeStatus),
  );
}

function sortManagerActivity(items, view = 'activity') {
  const order = {
    increased: 0,
    new_position: 1,
    reduced: 2,
    exited_position: 3,
  };
  return [...(Array.isArray(items) ? items : [])].sort((left, right) => {
    const leftOrder = order[left.changeStatus] ?? 9;
    const rightOrder = order[right.changeStatus] ?? 9;
    if (leftOrder !== rightOrder) return leftOrder - rightOrder;
    const leftChange = Math.abs(left.shareChangePct ?? 0);
    const rightChange = Math.abs(right.shareChangePct ?? 0);
    const direction = left.changeStatus === 'reduced' || view === 'sells' ? 1 : -1;
    return (
      direction * (leftChange - rightChange) ||
      (right.portfolioImpactPct ?? 0) - (left.portfolioImpactPct ?? 0) ||
      String(left.ticker ?? '').localeCompare(String(right.ticker ?? ''))
    );
  });
}

function activityLabel(item) {
  const status = item?.changeStatus;
  if (status === 'new_position') return 'Buy';
  if (status === 'exited_position') return 'Sell 100.00%';
  const percentage = typeof item?.shareChangePct === 'number'
    ? `${Math.abs(item.shareChangePct * 100).toFixed(2)}%`
    : null;
  if (status === 'increased') return percentage ? `Add ${percentage}` : 'Add';
  if (status === 'reduced') return percentage ? `Reduce ${percentage}` : 'Reduce';
  return actionLabel(status);
}

function normalizeNewBuyClusters(payload) {
  const data = payload && typeof payload === 'object' ? payload : {};
  const coverage = data.coverage && typeof data.coverage === 'object' ? data.coverage : {};
  return {
    quarter: data.quarter ?? null,
    managerScope: data.manager_scope ?? 'value',
    filingWindowOpen: Boolean(data.filing_window_open),
    officialFilingDeadline: data.official_filing_deadline ?? null,
    periods: Array.isArray(data.periods) ? data.periods : [],
    coverage: {
      reportedManagerCount: Number(coverage.reported_manager_count) || 0,
      trackedManagerCount: Number(coverage.tracked_manager_count) || 0,
    },
    items: (Array.isArray(data.items) ? data.items : []).map((item) => ({
      stock: {
        id: Number(item?.stock?.id),
        ticker: item?.stock?.ticker ?? '—',
        companyName: item?.stock?.company_name ?? 'Unknown company',
        exchange: item?.stock?.exchange ?? null,
      },
      clusterSize: Number(item?.cluster_size) || 0,
      visibleBuyerCount: Number(item?.visible_buyer_count) || 0,
      qualityWeightedClusterScore: Number(item?.quality_weighted_cluster_score) || 0,
      hasExcludedEvidence: Boolean(item?.has_excluded_evidence),
      buyers: (Array.isArray(item?.buyers) ? item.buyers : []).map((buyer) => ({
        manager: normalizeManager(buyer?.manager),
        currentValueUsd:
          typeof buyer?.current_value_usd === 'number' ? buyer.current_value_usd : null,
        currentShares:
          typeof buyer?.current_shares === 'number' ? buyer.current_shares : null,
        portfolioWeightPct:
          typeof buyer?.portfolio_weight_pct === 'number' ? buyer.portfolio_weight_pct : null,
        confidenceLevel: buyer?.confidence_level ?? 'unavailable',
        caveatCodes: Array.isArray(buyer?.caveat_codes) ? buyer.caveat_codes : [],
        includedInScore: Boolean(buyer?.included_in_score),
        scoreExclusionReasons: Array.isArray(buyer?.score_exclusion_reasons)
          ? buyer.score_exclusion_reasons
          : [],
        managerSignalWeight:
          typeof buyer?.manager_signal_weight === 'number' ? buyer.manager_signal_weight : null,
      })),
    })),
  };
}

function normalizeFilingSeason(payload) {
  const data = payload && typeof payload === 'object' ? payload : {};
  const season = data.season && typeof data.season === 'object' ? data.season : {};
  const coverage = data.coverage && typeof data.coverage === 'object' ? data.coverage : {};
  const normalizeDigestItem = (item) => ({
    manager: normalizeManager(item?.manager),
    quarter: item?.quarter ?? null,
    filingDate: item?.filing_date ?? null,
    acceptedAt: item?.accepted_at ?? null,
    holdingsCount: Number(item?.holdings_count) || 0,
    filingStatus: item?.filing_status ?? 'unavailable',
    caveats: Array.isArray(item?.caveats) ? item.caveats : [],
    topNewPositions: (Array.isArray(item?.top_new_positions) ? item.top_new_positions : []).map(
      (position) => ({
        stock: {
          id: Number(position?.stock?.id),
          ticker: position?.stock?.ticker ?? '—',
          companyName: position?.stock?.company_name ?? 'Unknown company',
        },
        currentValueUsd:
          typeof position?.current_value_usd === 'number' ? position.current_value_usd : null,
        portfolioWeightPct:
          typeof position?.portfolio_weight_pct === 'number'
            ? position.portfolio_weight_pct
            : null,
        confidenceLevel: position?.confidence_level ?? 'unavailable',
        includedInScore: Boolean(position?.included_in_score),
        caveatCodes: Array.isArray(position?.caveat_codes) ? position.caveat_codes : [],
      }),
    ),
  });
  return {
    digestDate: data.digest_date ?? null,
    inSeason: Boolean(season.in_season),
    quarter: season.quarter ?? null,
    deadlineDate: season.deadline_date ?? null,
    daysSinceDeadline:
      typeof season.days_since_deadline === 'number' ? season.days_since_deadline : null,
    coverage: {
      reportedManagerCount: Number(coverage.reported_manager_count) || 0,
      trackedManagerCount: Number(coverage.tracked_manager_count) || 0,
    },
    digests: (Array.isArray(data.digests) ? data.digests : []).map((digest) => ({
      digestDate: digest?.digest_date ?? null,
      items: (Array.isArray(digest?.items) ? digest.items : []).map(normalizeDigestItem),
    })),
  };
}

function formatCurrency(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    notation: Math.abs(value) >= 1_000_000 ? 'compact' : 'standard',
    maximumFractionDigits: Math.abs(value) >= 1_000_000 ? 2 : 0,
  }).format(value);
}

function formatPercentPoints(value, digits = 2) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return `${value.toFixed(digits)}%`;
}

function formatInteger(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value);
}

function actionLabel(value) {
  const labels = {
    new_position: 'New position',
    increased: 'Increased',
    reduced: 'Reduced',
    exited_position: 'Exited',
    unchanged: 'Unchanged',
    no_prior_data: 'No prior data',
    unresolvable: 'Unresolvable',
    cusip_changed: 'CUSIP changed',
  };
  return labels[value] ?? titleizeCode(value);
}

module.exports = {
  VALUE_STYLES,
  actionLabel,
  activityLabel,
  filterManagers,
  filterManagerActivity,
  formatCurrency,
  formatInteger,
  formatPercentPoints,
  managerMatchesScope,
  normalizeManagerChanges,
  normalizeManagerHistory,
  normalizeManagerHoldings,
  normalizeManagerPositionHistory,
  normalizeManagers,
  normalizeFilingSeason,
  normalizeNewBuyClusters,
  normalizeQuarters,
  sortManagerActivity,
  titleizeCode,
};
