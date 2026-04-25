const SECTION_ORDER = [
  'identity_header',
  'ratings_quality',
  'target_projection',
  'capital_structure',
  'annual_rates',
  'quarterly_tables',
  'annual_financials',
  'institutional_decisions',
  'narrative',
];

const SLOT_CONFIG = {
  headerMetrics: [
    ['mkt.price', 'recent_price', 'price'],
    ['val.pe', 'snapshot.pe', 'pe_ratio', 'pe'],
    ['val.relative_pe', 'snapshot.relative_pe', 'relative_pe'],
    ['val.dividend_yield', 'snapshot.dividend_yield', 'dividend_yield', 'yield'],
    ['mkt.market_cap', 'market_cap'],
  ],
  ratingMetrics: [
    ['rating.timeliness', 'timeliness'],
    ['rating.safety', 'safety'],
    ['rating.technical', 'technical'],
    ['rating.beta', 'beta'],
  ],
  qualityMetrics: [
    ['quality.financial_strength', 'financial_strength'],
    ['quality.stock_price_stability', 'quality.price_stability', 'price_stability'],
    ['quality.price_growth_persistence', 'price_growth_persistence'],
    ['quality.earnings_predictability', 'earnings_predictability'],
  ],
  targetMetrics: [
    ['target_18m_low', 'target.low', 'target_low'],
    ['target_18m_high', 'target.high', 'target_high'],
    ['target_18m_mid', 'target_18m_midpoint', 'target.midpoint', 'target_midpoint'],
    ['target_18m_upside_pct', 'target.upside_pct', 'upside_pct'],
    ['projection_high_price', 'projection.high_price'],
    ['projection_low_price', 'projection.low_price'],
    ['projection_annual_total_return_pct', 'projection.annual_total_return_pct'],
  ],
};

const TABLE_ROW_ORDER = [
  'sales',
  'revenue',
  'operating_margin',
  'operating_income',
  'net_profit_margin',
  'net_income',
  'eps',
  'cash_flow',
  'dividends',
  'book_value',
  'return_on_equity',
  'return_on_total_capital',
  'common_shares',
  'shares_outstanding',
  'debt',
];

const ANNUAL_FINANCIAL_ROW_LABELS = {
  'per_share.sales': 'Sales / Share',
  'per_share.revenues': 'Revenues / Share',
  'per_share.cash_flow': 'Cash Flow / Share',
  'per_share.capital_spending': 'Capital Spending / Share',
  'per_share.eps': 'Earnings / Share',
  'per_share.dividends_declared': 'Dividends Declared / Share',
  'per_share.book_value': 'Book Value / Share',
  'equity.shares_outstanding': 'Common Shares Outstanding',
  'is.sales': 'Sales ($M)',
  'is.revenues': 'Revenues ($M)',
  'is.depreciation': 'Depreciation ($M)',
  'is.operating_margin': 'Operating Margin',
  'is.net_income': 'Net Profit ($M)',
  'is.income_tax_rate': 'Income Tax Rate',
  'is.net_profit_margin': 'Net Profit Margin',
  'bs.working_capital': 'Working Capital ($M)',
  'bs.long_term_debt': 'Long-Term Debt ($M)',
  'bs.total_equity': 'Shareholders Equity ($M)',
  'bs.total_assets': 'Total Assets ($M)',
  'bs.return_on_total_capital': 'Return on Total Capital',
  'bs.return_on_equity': 'Return on Shareholders Equity',
  'bs.retained_to_common_equity': 'Retained to Common Equity',
  'bs.dividends_to_net_profit': 'All Dividends to Net Profit',
  'val.price_to_book': 'Price to Book Value',
  'val.avg_pe': 'Avg Annual P/E Ratio',
  'val.relative_pe': 'Relative P/E Ratio',
  'val.avg_dividend_yield': 'Avg Annual Dividend Yield',
};

const ANNUAL_FINANCIAL_ROW_ORDER = [
  'per_share.sales',
  'per_share.revenues',
  'per_share.cash_flow',
  'per_share.capital_spending',
  'per_share.eps',
  'per_share.dividends_declared',
  'per_share.book_value',
  'equity.shares_outstanding',
  'is.sales',
  'is.revenues',
  'is.depreciation',
  'is.operating_margin',
  'is.net_income',
  'is.income_tax_rate',
  'is.net_profit_margin',
  'bs.working_capital',
  'bs.long_term_debt',
  'bs.total_equity',
  'bs.total_assets',
  'bs.return_on_total_capital',
  'bs.return_on_equity',
  'bs.retained_to_common_equity',
  'bs.dividends_to_net_profit',
  'val.price_to_book',
  'val.avg_pe',
  'val.relative_pe',
  'val.avg_dividend_yield',
];

const SUMMARY_ORDER = [
  'recent_price',
  'pe_ratio',
  'pe_trailing',
  'pe_median',
  'relative_pe_ratio',
  'dividend_yield',
];

const SUMMARY_LABELS = {
  recent_price: 'Recent Price',
  pe_ratio: 'P/E Ratio',
  pe_trailing: 'P/E Trailing',
  pe_median: 'P/E Median',
  relative_pe_ratio: 'Relative P/E Ratio',
  dividend_yield: "Div'd Yld",
};

const RATING_ORDER = [
  {
    key: 'timeliness',
    label: 'TIMELINESS',
    metricCandidates: ['rating.timeliness', 'timeliness'],
    eventMappingId: 'rating.timeliness.event',
  },
  {
    key: 'safety',
    label: 'SAFETY',
    metricCandidates: ['rating.safety', 'safety'],
    eventMappingId: 'rating.safety.event',
  },
  {
    key: 'technical',
    label: 'TECHNICAL',
    metricCandidates: ['rating.technical', 'technical'],
    eventMappingId: 'rating.technical.event',
  },
  {
    key: 'beta',
    label: 'BETA',
    metricCandidates: ['risk.beta', 'rating.beta', 'beta'],
    eventMappingId: null,
  },
];

const QUALITY_ORDER = [
  {
    key: 'financial_strength',
    label: 'Financial Strength',
    metricCandidates: ['quality.financial_strength', 'financial_strength'],
  },
  {
    key: 'price_stability',
    label: 'Price Stability',
    metricCandidates: ['quality.stock_price_stability', 'quality.price_stability', 'price_stability'],
  },
  {
    key: 'price_growth_persistence',
    label: 'Price Growth Persistence',
    metricCandidates: ['quality.price_growth_persistence', 'price_growth_persistence'],
  },
  {
    key: 'earnings_predictability',
    label: 'Earnings Predictability',
    metricCandidates: ['quality.earnings_predictability', 'earnings_predictability'],
  },
];

const NARRATIVE_CARD_ORDER = [
  {
    key: 'business_narrative',
    title: 'BUSINESS NARRATIVE',
    mappingId: 'company.business_description.as_of',
  },
  {
    key: 'analyst_comment',
    title: 'ANALYST COMMENT',
    mappingId: 'analyst.commentary.as_of',
  },
];

const TARGET_RANGE_ORDER = [
  {
    key: 'low',
    label: 'Low',
    metricCandidates: ['target.price_18m.low', 'target_18m_low', 'target.low', 'target_low'],
  },
  {
    key: 'high',
    label: 'High',
    metricCandidates: ['target.price_18m.high', 'target_18m_high', 'target.high', 'target_high'],
  },
  {
    key: 'midpoint',
    label: 'Midpoint',
    metricCandidates: [
      'target.price_18m.mid',
      'target_18m_mid',
      'target_18m_midpoint',
      'target.midpoint',
      'target_midpoint',
    ],
  },
  {
    key: 'percent_to_mid',
    label: '% to Mid',
    metricCandidates: [
      'target.price_18m.upside',
      'target_18m_upside_pct',
      'target.upside_pct',
      'target_18m_percent_to_mid',
      'upside_pct',
    ],
  },
];

const PROJECTION_COLUMNS = [
  { key: 'price', label: 'Price' },
  { key: 'gain', label: 'Gain' },
  { key: 'annual_total_return', label: "Ann'l Total Return" },
];

const PROJECTION_ROWS = [
  {
    key: 'high',
    label: 'High',
    cells: {
      price: [
        'proj.long_term.high_price',
        'long_term_projection_high_price',
        'projection_high_price',
        'projection.high_price',
      ],
      gain: [
        'proj.long_term.high_price_gain',
        'long_term_projection_high_price_gain_pct',
        'projection_high_price_gain_pct',
        'projection_price_gain_pct.high',
      ],
      annual_total_return: [
        'proj.long_term.high_total_return',
        'long_term_projection_high_total_return_pct',
        'projection_high_total_return_pct',
        'projection_high_annual_total_return_pct',
      ],
    },
  },
  {
    key: 'low',
    label: 'Low',
    cells: {
      price: [
        'proj.long_term.low_price',
        'long_term_projection_low_price',
        'projection_low_price',
        'projection.low_price',
      ],
      gain: [
        'proj.long_term.low_price_gain',
        'long_term_projection_low_price_gain_pct',
        'projection_low_price_gain_pct',
        'projection_price_gain_pct.low',
      ],
      annual_total_return: [
        'proj.long_term.low_total_return',
        'long_term_projection_low_total_return_pct',
        'projection_low_total_return_pct',
        'projection_low_annual_total_return_pct',
      ],
    },
  },
];

const INSTITUTIONAL_DECISION_ROWS = [
  {
    key: 'to_buy',
    label: 'to Buy',
    metricCandidates: [
      'ownership.institutional.to_buy',
      'institutional_to_buy',
      'institutional.to_buy',
    ],
  },
  {
    key: 'to_sell',
    label: 'to Sell',
    metricCandidates: [
      'ownership.institutional.to_sell',
      'institutional_to_sell',
      'institutional.to_sell',
    ],
  },
  {
    key: 'holdings',
    label: "Hld's(000)",
    metricCandidates: [
      'ownership.institutional.holdings',
      'institutional_holding_shares_k',
      'holdings_thousand_shares',
      'holds_000',
    ],
  },
];

const CURRENT_POSITION_ROWS = [
  {
    key: 'cash_assets',
    label: 'Cash Assets',
    section: 'assets',
    sourcePath: ['assets', 'cash_assets'],
  },
  {
    key: 'receivables',
    label: 'Receivables',
    section: 'assets',
    sourcePath: ['assets', 'receivables'],
  },
  {
    key: 'inventory',
    label: 'Inventory',
    section: 'assets',
    sourcePaths: [
      ['assets', 'inventory_lifo'],
      ['assets', 'inventory_fifo'],
      ['assets', 'inventory_avg_cost'],
    ],
  },
  {
    key: 'other_current_assets',
    label: 'Other Current Assets',
    section: 'assets',
    sourcePath: ['assets', 'other_current_assets'],
  },
  {
    key: 'total_current_assets',
    label: 'Total Current Assets',
    section: 'assets',
    sourcePath: ['assets', 'total_current_assets'],
  },
  {
    key: 'accounts_payable',
    label: 'Accounts Payable',
    section: 'liabilities',
    sourcePath: ['liabilities', 'accounts_payable'],
  },
  {
    key: 'debt_due',
    label: 'Debt Due',
    section: 'liabilities',
    sourcePath: ['liabilities', 'debt_due'],
  },
  {
    key: 'other_current_liabilities',
    label: 'Other Current Liabilities',
    section: 'liabilities',
    sourcePath: ['liabilities', 'other_current_liabilities'],
  },
  {
    key: 'total_current_liabilities',
    label: 'Total Current Liabilities',
    section: 'liabilities',
    sourcePath: ['liabilities', 'total_current_liabilities'],
  },
];

const ANNUAL_RATES_ORDER = [
  'sales',
  'revenues',
  'premium_income',
  'cash_flow',
  'investment_income',
  'earnings',
  'dividends',
  'book_value',
];

const QUARTERLY_COLUMN_KEYS = ['Q1', 'Q2', 'Q3', 'Q4'];

const CAPITAL_STRUCTURE_ORDER = [
  {
    key: 'as_of',
    label: 'As Of',
    rawPath: ['as_of'],
    metricCandidates: [],
  },
  {
    key: 'total_debt',
    label: 'Total Debt',
    rawPath: ['total_debt'],
    metricCandidates: ['cap.total_debt', 'total_debt'],
  },
  {
    key: 'debt_due_in_5y',
    label: 'Debt Due in 5 Yrs',
    rawPath: ['debt_due_in_5_years'],
    metricCandidates: ['cap.debt_due_in_5y', 'debt_due_in_5_years'],
  },
  {
    key: 'long_term_debt',
    label: 'LT Debt',
    rawPath: ['lt_debt'],
    metricCandidates: ['cap.long_term_debt', 'lt_debt', 'long_term_debt'],
  },
  {
    key: 'long_term_interest',
    label: 'LT Interest',
    rawPath: ['lt_interest'],
    metricCandidates: ['cap.long_term_interest', 'lt_interest'],
  },
  {
    key: 'lt_interest_percent_of_capital',
    label: 'LT Interest % of Capital',
    rawPath: ['lt_interest_percent_of_capital'],
    metricCandidates: [
      'cap.lt_interest_percent_of_capital',
      'cap.lt_interest_pct_of_capital',
      'debt_percent_of_capital',
      'lt_interest_percent_of_capital',
    ],
  },
  {
    key: 'leases_uncapitalized',
    label: 'Leases Uncapitalized',
    rawPath: ['leases_uncapitalized'],
    metricCandidates: ['leases_uncapitalized_annual_rentals', 'leases_uncapitalized'],
  },
  {
    key: 'pension_assets',
    label: 'Pension Assets',
    rawPath: ['pension_assets'],
    metricCandidates: ['pension_assets'],
  },
  {
    key: 'pension_obligations',
    label: 'Pension Obligations',
    rawPath: ['obligations_other'],
    metricCandidates: ['pension_obligations', 'obligations_other'],
  },
  {
    key: 'pension_plan',
    label: 'Pension Plan',
    rawPath: ['pension_plan'],
    metricCandidates: [],
  },
  {
    key: 'preferred_stock',
    label: 'Preferred Stock',
    rawPath: ['preferred_stock'],
    metricCandidates: ['cap.preferred_stock', 'preferred_stock'],
  },
  {
    key: 'preferred_dividend',
    label: 'Preferred Dividend',
    rawPath: ['preferred_dividend'],
    metricCandidates: ['cap.preferred_dividend', 'preferred_dividend'],
  },
  {
    key: 'shares_outstanding',
    label: 'Shares Outstanding',
    rawPath: ['common_stock', 'shares_outstanding'],
    metricCandidates: [
      'equity.shares_outstanding',
      'common_stock_shares_outstanding',
      'shares_outstanding',
    ],
  },
  {
    key: 'common_stock_as_of',
    label: 'Common Stock As Of',
    rawPath: ['common_stock', 'as_of'],
    metricCandidates: [],
  },
  {
    key: 'market_cap',
    label: 'Market Cap',
    rawPath: ['market_cap'],
    metricCandidates: ['mkt.market_cap', 'market_cap'],
  },
  {
    key: 'market_cap_category',
    label: 'Market Cap Category',
    rawPath: ['market_cap', 'market_cap_category'],
    metricCandidates: [],
  },
];

function buildDocumentReviewSections(groups) {
  if (!Array.isArray(groups)) {
    return [];
  }
  const order = new Map(SECTION_ORDER.map((key, index) => [key, index]));
  return [...groups]
    .filter((group) => Array.isArray(group.items) && group.items.length > 0)
    .sort((a, b) => (order.get(a.key) ?? 999) - (order.get(b.key) ?? 999))
    .map((group) => ({
      ...group,
      items: group.items.map((item) => ({
        ...item,
        valueLabel: formatDocumentReviewValue(item),
        meta: formatDocumentReviewMeta(item),
        evidenceLabel: formatDocumentReviewEvidenceLabel(item),
      })),
    }));
}

function buildDocumentReviewReportModel(groups) {
  const sections = buildDocumentReviewSections(groups);
  const displayedFactIds = new Set();

  const consumeSlots = (slotGroups) =>
    slotGroups
      .map((candidates) => {
        const item = pickFirstMatchingItem(sections, candidates, displayedFactIds);
        if (!item) {
          return null;
        }
        displayedFactIds.add(item.fact_id);
        return item;
      })
      .filter(Boolean);

  const headerMetrics = consumeSlots(SLOT_CONFIG.headerMetrics);
  const ratingMetrics = consumeSlots(SLOT_CONFIG.ratingMetrics);
  const qualityMetrics = consumeSlots(SLOT_CONFIG.qualityMetrics);
  const targetMetrics = consumeSlots(SLOT_CONFIG.targetMetrics);

  const annualTable = buildReviewTable(
    sections.find((section) => section.key === 'annual_financials'),
    displayedFactIds
  );
  const quarterlyTable = buildReviewTable(
    sections.find((section) => section.key === 'quarterly_tables'),
    displayedFactIds
  );

  const narrativeItems = collectSectionItems(sections, 'narrative', displayedFactIds);
  const institutionalItems = collectSectionItems(
    sections,
    'institutional_decisions',
    displayedFactIds
  );
  const capitalItems = collectSectionItems(sections, 'capital_structure', displayedFactIds);
  const rateItems = collectSectionItems(sections, 'annual_rates', displayedFactIds);
  const leftoverSections = sections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => !displayedFactIds.has(item.fact_id)),
    }))
    .filter(
      (section) =>
        ![
          'annual_financials',
          'quarterly_tables',
          'narrative',
          'institutional_decisions',
          'capital_structure',
          'annual_rates',
        ].includes(section.key) && section.items.length > 0
    );

  return {
    sections,
    headerMetrics,
    ratingMetrics,
    qualityMetrics,
    targetMetrics,
    annualTable,
    quarterlyTable,
    narrativeItems,
    institutionalItems,
    capitalItems,
    rateItems,
    leftoverSections,
    displayedFactIds,
  };
}

function findDocumentReviewItemByFactId(report, factId) {
  if (!report || !Array.isArray(report.sections)) {
    return null;
  }
  for (const section of report.sections) {
    const found = Array.isArray(section.items)
      ? section.items.find((item) => item.fact_id === factId)
      : null;
    if (found) {
      return found;
    }
  }
  return null;
}

function buildDocumentReviewSummary(summary) {
  if (!summary || typeof summary !== 'object') {
    return [];
  }
  return SUMMARY_ORDER.map((key) => {
    const metric = summary[key];
    const safeMetric = metric && typeof metric === 'object' ? metric : {};
    return {
      ...safeMetric,
      key,
      label: safeMetric.label || SUMMARY_LABELS[key] || key,
      displayValue: formatDocumentReviewSummaryValue(safeMetric),
    };
  });
}

function buildDocumentReviewRatings(groups, evidence) {
  const sections = buildDocumentReviewSections(groups);
  const evidenceByMappingId = new Map(
    Array.isArray(evidence)
      ? evidence
          .filter((item) => item && typeof item === 'object' && item.mapping_id)
          .map((item) => [item.mapping_id, item])
      : []
  );

  return RATING_ORDER.map((config) => {
    const fact = pickFirstMatchingItem(sections, config.metricCandidates, new Set());
    const event = config.eventMappingId ? evidenceByMappingId.get(config.eventMappingId) : null;
    const value = formatDocumentReviewRatingValue(config.key, fact);
    const eventLabel = formatRatingEventLabel(event);
    return {
      key: config.key,
      label: config.label,
      displayValue: [value, eventLabel].filter(Boolean).join(' ') || '—',
    };
  });
}

function buildDocumentReviewQuality(groups) {
  const sections = buildDocumentReviewSections(groups);
  return QUALITY_ORDER.map((config) => {
    const fact = pickFirstMatchingItem(sections, config.metricCandidates, new Set());
    return {
      key: config.key,
      label: config.label,
      displayValue: formatDocumentReviewQualityValue(fact),
    };
  });
}

function buildDocumentReviewNarrativeCards(evidence) {
  const evidenceItems = Array.isArray(evidence) ? evidence : [];
  const cards = [];
  for (const config of NARRATIVE_CARD_ORDER) {
    const item = evidenceItems.find((entry) => entry?.mapping_id === config.mappingId);
    const body = item?.value_text ? String(item.value_text).trim() : '';
    if (!body) {
      continue;
    }
    const asOf = formatShortDate(item.period_end_date);
    cards.push({
      key: config.key,
      title: config.title,
      body,
      meta: asOf ? `As of ${asOf}` : null,
    });
  }
  return cards;
}

function buildDocumentReviewTargetRange(groups) {
  const sections = buildDocumentReviewSections(groups);

  return TARGET_RANGE_ORDER.map((config) => {
    const fact = pickFirstMatchingItem(sections, config.metricCandidates, new Set());
    return {
      key: config.key,
      label: config.label,
      displayValue: formatDocumentReviewTargetRangeValue(config.key, fact),
    };
  });
}

function buildDocumentReviewProjections(groups) {
  const sections = buildDocumentReviewSections(groups);

  return {
    columns: PROJECTION_COLUMNS,
    rows: PROJECTION_ROWS.map((row) => ({
      key: row.key,
      label: row.label,
      cells: PROJECTION_COLUMNS.map((column) => {
        const fact = pickFirstStrictMatchingItem(sections, row.cells[column.key]);
        return {
          key: column.key,
          label: column.label,
          displayValue: formatDocumentReviewProjectionValue(column.key, fact),
        };
      }),
    })),
  };
}

function buildDocumentReviewInstitutionalDecisions(groups) {
  const sections = buildDocumentReviewSections(groups);
  const rowItems = INSTITUTIONAL_DECISION_ROWS.map((row) => ({
    ...row,
    items: findAllStrictMatchingItems(sections, row.metricCandidates),
  }));
  const columnMap = new Map();

  for (const row of rowItems) {
    for (const item of row.items) {
      const key = item.period_end_date || item.as_of_date || item.period;
      if (!key || columnMap.has(key)) {
        continue;
      }
      columnMap.set(key, {
        key,
        label: formatInstitutionalDecisionColumnLabel(item),
        sortKey: item.period_end_date || item.as_of_date || key,
      });
    }
  }

  const columns = [...columnMap.values()].sort((a, b) => a.sortKey.localeCompare(b.sortKey));

  return {
    columns,
    rows: rowItems.map((row) => ({
      key: row.key,
      label: row.label,
      cells: columns.map((column) => {
        const item = row.items.find(
          (entry) => (entry.period_end_date || entry.as_of_date || entry.period) === column.key
        );
        return {
          key: column.key,
          label: column.label,
          displayValue: formatInstitutionalDecisionValue(row.key, item),
        };
      }),
    })),
  };
}

/**
 * @param {Array<{ key: string, label: string, items: Array<object> }>} groups
 * @param {Record<string, unknown> | null} annualFinancials
 */
function buildDocumentReviewAnnualFinancials(groups, annualFinancials = null) {
  const rawTable = buildAnnualFinancialsFromBlock(annualFinancials);
  if (rawTable.columns.length > 0 && rawTable.rows.length > 0) {
    return rawTable;
  }

  const sections = buildDocumentReviewSections(groups);
  const section = sections.find((entry) => entry.key === 'annual_financials');
  const items = Array.isArray(section?.items) ? section.items : [];
  const columnMap = new Map();
  const rowMap = new Map();

  for (const item of items) {
    if (!item || (item.period_type && item.period_type !== 'FY')) {
      continue;
    }
    const columnKey = item.period_end_date || item.as_of_date || item.period;
    const rowKey = item.metric_key || item.label;
    if (!columnKey || !rowKey) {
      continue;
    }
    if (!columnMap.has(columnKey)) {
      columnMap.set(columnKey, {
        key: columnKey,
        label: formatTableColumnLabel(item),
        sortKey: columnSortKey(item, columnKey),
      });
    }
    if (!rowMap.has(rowKey)) {
      rowMap.set(rowKey, {
        key: rowKey,
        label: formatAnnualFinancialRowLabel(item),
        sortKey: annualFinancialRowSortKey(item),
        cells: new Map(),
      });
    }
    rowMap.get(rowKey).cells.set(columnKey, item);
  }

  const columns = [...columnMap.values()].sort((a, b) => a.sortKey.localeCompare(b.sortKey));
  const rows = [...rowMap.values()]
    .sort((a, b) => {
      const orderDelta = a.sortKey - b.sortKey;
      return orderDelta !== 0 ? orderDelta : a.label.localeCompare(b.label);
    })
    .map((row) => ({
      key: row.key,
      label: row.label,
      cells: columns.map((column) => {
        const item = row.cells.get(column.key);
        return {
          key: column.key,
          label: column.label,
          displayValue: formatAnnualFinancialValue(item),
          isEstimate: false,
        };
      }),
    }));

  return { columns, rows };
}

function buildAnnualFinancialsFromBlock(annualFinancials) {
  const block =
    annualFinancials && typeof annualFinancials === 'object' && !Array.isArray(annualFinancials)
      ? annualFinancials
      : null;
  const meta = block && typeof block.meta === 'object' && !Array.isArray(block.meta) ? block.meta : {};
  const yearKeys = annualFinancialYearKeys(block, meta);
  const columns = yearKeys.map((key) => ({
    key,
    label: formatAnnualFinancialColumnLabel(key, meta),
    isEstimate: isAnnualFinancialEstimateColumn(key, meta),
  }));
  const rowMap = new Map();

  for (const [groupKey, groupValue] of Object.entries(block || {})) {
    if (groupKey === 'meta' || groupKey === 'per_unit' || !groupValue || typeof groupValue !== 'object') {
      continue;
    }
    for (const [seriesKey, series] of Object.entries(groupValue)) {
      if (!series || typeof series !== 'object' || Array.isArray(series)) {
        continue;
      }
      const metricKey = annualFinancialMetricKey(groupKey, seriesKey);
      if (!metricKey) {
        continue;
      }
      const decimalPlaces = annualFinancialSeriesDecimalPlaces(series, columns);
      const row = {
        key: metricKey,
        label: ANNUAL_FINANCIAL_ROW_LABELS[metricKey] || humanizeMetricKey(seriesKey),
        sortKey: annualFinancialMetricSortKey(metricKey),
        cells: columns.map((column) => ({
          key: column.key,
          label: column.label,
          displayValue: formatAnnualFinancialRawValue(series[column.key], decimalPlaces),
          isEstimate: column.isEstimate,
        })),
      };
      if (row.cells.some((cell) => cell.displayValue !== '—')) {
        rowMap.set(metricKey, row);
      }
    }
  }

  const rows = [...rowMap.values()]
    .sort((a, b) => {
      const orderDelta = a.sortKey - b.sortKey;
      return orderDelta !== 0 ? orderDelta : a.label.localeCompare(b.label);
    })
    .map((row) => ({
      key: row.key,
      label: row.label,
      cells: row.cells,
    }));

  return { columns, rows };
}

/**
 * @param {Record<string, unknown> | null} annualRates
 */
function buildDocumentReviewAnnualRates(annualRates = null) {
  const block =
    annualRates && typeof annualRates === 'object' && !Array.isArray(annualRates)
      ? annualRates
      : null;
  const metrics = Array.isArray(block?.metrics) ? block.metrics : [];
  const estimatedPeriods = firstAnnualRateEstimatePeriods(metrics);
  const columns = [
    { key: 'past_10y_cagr_pct', label: 'Past 10Y', isEstimate: false },
    { key: 'past_5y_cagr_pct', label: 'Past 5Y', isEstimate: false },
    {
      key: 'estimated_cagr_pct',
      label: estimatedPeriods
        ? `Est. ${estimatedPeriods.from_period} to ${estimatedPeriods.to_period}`
        : 'Estimated',
      isEstimate: true,
    },
  ];

  const rows = metrics
    .filter((metric) => metric && typeof metric === 'object' && !Array.isArray(metric))
    .map((metric) => {
      const key = String(metric.metric_key || metric.display_name || '');
      return {
        key,
        label: metric.display_name ? String(metric.display_name) : humanizeMetricKey(key),
        sortKey: annualRateSortKey(key),
        cells: columns.map((column) => ({
          key: column.key,
          label: column.label,
          displayValue:
            column.key === 'estimated_cagr_pct'
              ? formatAnnualRatePercent(metric.estimated_cagr_pct?.value)
              : formatAnnualRatePercent(metric[column.key]),
          isEstimate: column.isEstimate,
        })),
      };
    })
    .filter((row) => row.key && row.cells.some((cell) => cell.displayValue !== '—'))
    .sort((a, b) => {
      const orderDelta = a.sortKey - b.sortKey;
      return orderDelta !== 0 ? orderDelta : a.label.localeCompare(b.label);
    })
    .map(({ sortKey: _sortKey, ...row }) => row);

  return {
    unit: typeof block?.unit === 'string' ? block.unit : null,
    columns,
    rows,
  };
}

/**
 * @param {Record<string, unknown> | null} quarterlyBlock
 */
function buildDocumentReviewQuarterlyTable(quarterlyBlock = null) {
  const block =
    quarterlyBlock && typeof quarterlyBlock === 'object' && !Array.isArray(quarterlyBlock)
      ? quarterlyBlock
      : null;
  const years = Array.isArray(block?.by_year) ? block.by_year : [];
  const quarterLabels = Array.isArray(block?.quarter_month_order)
    ? block.quarter_month_order
    : QUARTERLY_COLUMN_KEYS;
  const columns = [
    ...QUARTERLY_COLUMN_KEYS.map((key, index) => ({
      key,
      label: String(quarterLabels[index] || key),
    })),
    { key: 'full_year', label: 'Year' },
  ];

  return {
    unit: typeof block?.unit === 'string' ? block.unit : null,
    columns,
    rows: years
      .filter((year) => year && typeof year === 'object' && !Array.isArray(year))
      .map((year) => {
        const rowKey = String(year.calendar_year || '');
        return {
          key: rowKey,
          label: rowKey || '—',
          cells: columns.map((column) => {
            const valueSource =
              column.key === 'full_year' ? year.full_year : year.quarters?.[column.key];
            return {
              key: column.key,
              label: column.label,
              displayValue: formatQuarterlyValue(valueSource?.value),
              isEstimate: valueSource?.fact_nature === 'estimate',
            };
          }),
        };
      })
      .filter((row) => row.key && row.cells.some((cell) => cell.displayValue !== '—')),
  };
}

/**
 * @param {Record<string, unknown> | null} currentPosition
 */
function buildDocumentReviewCurrentPosition(currentPosition = null) {
  const block =
    currentPosition && typeof currentPosition === 'object' && !Array.isArray(currentPosition)
      ? currentPosition
      : null;
  const periods = Array.isArray(block?.periods) ? block.periods : [];
  const columns = periods.map((period, index) => ({
    key: String(period?.period_end_date || period?.label || index),
    label: String(period?.label || period?.period_end_date || `Period ${index + 1}`),
  }));

  return {
    unit: typeof block?.unit === 'string' ? block.unit : null,
    columns,
    rows: CURRENT_POSITION_ROWS.map((row) => ({
      key: row.key,
      label: row.label,
      section: row.section,
      cells: periods.map((period, index) => {
        const rawValue = readFirstPath(period, row.sourcePaths || [row.sourcePath]);
        return {
          key: columns[index]?.key || String(index),
          label: columns[index]?.label || `Period ${index + 1}`,
          displayValue: rawValue.exists ? formatCurrentPositionValue(rawValue.value) : '—',
          sourceExists: rawValue.exists,
        };
      }),
    })).filter((row) => row.cells.some((cell) => cell.sourceExists)),
  };
}

/**
 * @param {Array<{ key: string, label: string, items: Array<object> }>} groups
 * @param {Record<string, unknown> | null} capitalStructure
 */
function buildDocumentReviewCapitalStructure(groups, capitalStructure = null) {
  const sections = buildDocumentReviewSections(groups);
  const metrics = [];
  const rawBlock =
    capitalStructure && typeof capitalStructure === 'object' && !Array.isArray(capitalStructure)
      ? capitalStructure
      : null;

  for (const config of CAPITAL_STRUCTURE_ORDER) {
    const fact = pickFirstStrictMatchingItem(sections, config.metricCandidates || []);
    const rawValue = rawBlock && config.rawPath ? readPath(rawBlock, config.rawPath) : null;
    if (!fact && !rawValue?.exists) {
      continue;
    }
    metrics.push({
      key: config.key,
      label: config.label,
      displayValue: fact
        ? formatCapitalStructureValue(config.key, fact)
        : formatRawCapitalStructureValue(config.key, rawValue.value),
    });
  }

  return metrics;
}

function formatDocumentReviewValue(item) {
  if (!item || typeof item !== 'object') {
    return 'Not available';
  }
  if (item.display_value !== null && item.display_value !== undefined && item.display_value !== '') {
    return String(item.display_value);
  }
  if (item.value_numeric !== null && item.value_numeric !== undefined) {
    return [formatNumber(item.value_numeric), item.unit].filter(Boolean).join(' ');
  }
  if (item.value_text !== null && item.value_text !== undefined && item.value_text !== '') {
    return String(item.value_text);
  }
  return 'Not available';
}

function formatDocumentReviewMeta(item) {
  if (!item || typeof item !== 'object') {
    return null;
  }
  const parts = [];
  if (item.period_type) {
    parts.push(item.period_type);
  }
  const dateLabel = formatDateOnly(item.period_end_date || item.as_of_date);
  if (dateLabel) {
    parts.push(dateLabel);
  }
  if (item.source_type) {
    parts.push(item.source_type);
  }
  parts.push(item.is_current ? 'Current' : 'Historical');
  return parts.join(' · ') || null;
}

function formatDocumentReviewEvidenceLabel(item) {
  const pageNumber = item && item.lineage ? item.lineage.page_number : null;
  return typeof pageNumber === 'number' ? `p.${pageNumber}` : 'No lineage';
}

function pickFirstMatchingItem(sections, candidates, displayedFactIds) {
  for (const candidate of candidates) {
    const normalizedCandidate = String(candidate).toLowerCase();
    for (const section of sections) {
      for (const item of section.items) {
        if (displayedFactIds.has(item.fact_id)) {
          continue;
        }
        const metricKey = String(item.metric_key || '').toLowerCase();
        const label = String(item.label || '').toLowerCase();
        if (
          metricKey === normalizedCandidate ||
          metricKey.endsWith(`.${normalizedCandidate}`) ||
          metricKey.includes(normalizedCandidate) ||
          label.includes(normalizedCandidate.replaceAll('_', ' '))
        ) {
          return item;
        }
      }
    }
  }
  return null;
}

function pickFirstStrictMatchingItem(sections, candidates) {
  for (const candidate of candidates) {
    const normalizedCandidate = String(candidate).toLowerCase();
    for (const section of sections) {
      for (const item of section.items) {
        const metricKey = String(item.metric_key || '').toLowerCase();
        if (metricKey === normalizedCandidate || metricKey.endsWith(`.${normalizedCandidate}`)) {
          return item;
        }
      }
    }
  }
  return null;
}

function findAllStrictMatchingItems(sections, candidates) {
  const normalizedCandidates = candidates.map((candidate) => String(candidate).toLowerCase());
  const matches = [];
  for (const section of sections) {
    for (const item of section.items) {
      const metricKey = String(item.metric_key || '').toLowerCase();
      if (
        normalizedCandidates.some(
          (candidate) => metricKey === candidate || metricKey.endsWith(`.${candidate}`)
        )
      ) {
        matches.push(item);
      }
    }
  }
  return matches;
}

function collectSectionItems(sections, key, displayedFactIds) {
  const section = sections.find((entry) => entry.key === key);
  if (!section) {
    return [];
  }
  const items = section.items.filter((item) => !displayedFactIds.has(item.fact_id));
  for (const item of items) {
    displayedFactIds.add(item.fact_id);
  }
  return items;
}

function buildReviewTable(section, displayedFactIds) {
  if (!section || !Array.isArray(section.items) || section.items.length === 0) {
    return { columns: [], rows: [] };
  }

  const columnMap = new Map();
  const rowMap = new Map();

  for (const item of section.items) {
    const columnKey = item.period_end_date || item.as_of_date || item.metric_key;
    if (!columnMap.has(columnKey)) {
      columnMap.set(columnKey, {
        key: columnKey,
        sortKey: columnSortKey(item, columnKey),
        label: formatTableColumnLabel(item),
      });
    }

    const rowKey = item.label || item.metric_key;
    if (!rowMap.has(rowKey)) {
      rowMap.set(rowKey, {
        key: rowKey,
        label: rowKey,
        metric_key: item.metric_key,
        sortKey: rowSortKey(item),
        cells: new Map(),
      });
    }

    rowMap.get(rowKey).cells.set(columnKey, item);
    displayedFactIds.add(item.fact_id);
  }

  const columns = [...columnMap.values()].sort((a, b) => a.sortKey.localeCompare(b.sortKey));
  const rows = [...rowMap.values()]
    .sort((a, b) => {
      const orderDelta = a.sortKey - b.sortKey;
      return orderDelta !== 0 ? orderDelta : a.label.localeCompare(b.label);
    })
    .map((row) => ({
      key: row.key,
      label: row.label,
      metric_key: row.metric_key,
      cells: columns.map((column) => row.cells.get(column.key) || null),
    }));

  return { columns, rows };
}

function rowSortKey(item) {
  const search = `${item.label || ''} ${item.metric_key || ''}`.toLowerCase();
  const index = TABLE_ROW_ORDER.findIndex((token) => search.includes(token));
  return index === -1 ? 999 : index;
}

function annualFinancialRowSortKey(item) {
  const metricKey = String(item.metric_key || '');
  return annualFinancialMetricSortKey(metricKey);
}

function annualFinancialMetricSortKey(metricKey) {
  const index = ANNUAL_FINANCIAL_ROW_ORDER.indexOf(metricKey);
  return index === -1 ? 999 : index;
}

function formatAnnualFinancialRowLabel(item) {
  const metricKey = String(item.metric_key || '');
  if (ANNUAL_FINANCIAL_ROW_LABELS[metricKey]) {
    return ANNUAL_FINANCIAL_ROW_LABELS[metricKey];
  }
  return item.label || metricKey.replaceAll('_', ' ').replaceAll('.', ' ');
}

function annualFinancialYearKeys(block, meta) {
  const keys = [];
  const addKey = (key) => {
    const normalized = String(key);
    if (!keys.includes(normalized)) {
      keys.push(normalized);
    }
  };

  if (Array.isArray(meta?.historical_years)) {
    for (const year of meta.historical_years) {
      addKey(year);
    }
  }

  for (const value of Object.values(block || {})) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      continue;
    }
    for (const series of Object.values(value)) {
      if (!series || typeof series !== 'object' || Array.isArray(series)) {
        continue;
      }
      for (const key of Object.keys(series)) {
        if (/^\d{4}$/.test(key) || key.startsWith('projection_')) {
          addKey(key);
        }
      }
    }
  }

  return keys.sort((a, b) => annualFinancialColumnSortKey(a) - annualFinancialColumnSortKey(b));
}

function annualFinancialColumnSortKey(key) {
  if (/^\d{4}$/.test(key)) {
    return Number(key);
  }
  return 10_000;
}

function formatAnnualFinancialColumnLabel(key, meta) {
  if (key.startsWith('projection_')) {
    return String(meta?.projection_year_range || key.replace('projection_', '').replaceAll('_', '-'));
  }
  return key;
}

function isAnnualFinancialEstimateColumn(key, meta) {
  if (key.startsWith('projection_')) {
    return true;
  }
  if (!Array.isArray(meta?.estimate_years)) {
    return false;
  }
  return meta.estimate_years.map((year) => String(year)).includes(String(key));
}

function annualFinancialMetricKey(groupKey, seriesKey) {
  const maps = {
    per_unit_metrics: {
      sales: 'per_share.sales',
      revenues: 'per_share.revenues',
      cash_flow: 'per_share.cash_flow',
      capital_spending: 'per_share.capital_spending',
      earnings: 'per_share.eps',
      dividends_declared: 'per_share.dividends_declared',
      book_value: 'per_share.book_value',
      common_shares_outstanding_millions: 'equity.shares_outstanding',
      pc_prem_earned: 'per_share.premiums_earned',
      investment_income: 'per_share.investment_income',
      underwriting_income: 'per_share.underwriting_income',
    },
    valuation_metrics: {
      price_to_book_value_pct: 'val.price_to_book',
      avg_annual_pe_ratio: 'val.avg_pe',
      relative_pe_ratio: 'val.relative_pe',
      avg_annual_dividend_yield_pct: 'val.avg_dividend_yield',
    },
    income_statement_usd_millions: {
      sales: 'is.sales',
      revenues: 'is.revenues',
      depreciation: 'is.depreciation',
      operating_margin_pct: 'is.operating_margin',
      net_profit: 'is.net_income',
    },
    income_statement_ratios_pct: {
      income_tax_rate_pct: 'is.income_tax_rate',
      net_profit_margin_pct: 'is.net_profit_margin',
    },
    balance_sheet_and_returns_usd_millions: {
      working_capital: 'bs.working_capital',
      long_term_debt: 'bs.long_term_debt',
      shareholders_equity: 'bs.total_equity',
      total_assets: 'bs.total_assets',
      return_on_total_capital_pct: 'bs.return_on_total_capital',
      return_on_shareholders_equity_pct: 'bs.return_on_equity',
      retained_to_common_equity_pct: 'bs.retained_to_common_equity',
      all_dividends_to_net_profit_pct: 'bs.dividends_to_net_profit',
    },
  };
  return maps[groupKey]?.[seriesKey] || null;
}

function humanizeMetricKey(key) {
  return String(key)
    .replace(/_pct$/, '')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function columnSortKey(item, fallbackKey) {
  return String(item.period_end_date || item.as_of_date || fallbackKey || '');
}

function formatTableColumnLabel(item) {
  const iso = item.period_end_date || item.as_of_date;
  if (!iso) {
    return item.period || 'Value';
  }

  const dt = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(dt.getTime())) {
    return iso;
  }

  if (item.period_type === 'Q') {
    return `Q${Math.floor(dt.getUTCMonth() / 3) + 1} ${dt.getUTCFullYear()}`;
  }
  return String(dt.getUTCFullYear());
}

function formatDateOnly(iso) {
  if (!iso || typeof iso !== 'string') {
    return null;
  }
  const dt = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(dt.getTime())) {
    return iso;
  }
  return dt.toLocaleDateString();
}

function formatNumber(value) {
  if (typeof value !== 'number') {
    return String(value);
  }
  return Number.isInteger(value) ? String(value) : String(value);
}

function formatDocumentReviewSummaryValue(metric) {
  if (!metric || typeof metric !== 'object') {
    return '—';
  }
  if (
    metric.display_value !== null &&
    metric.display_value !== undefined &&
    metric.display_value !== ''
  ) {
    return String(metric.display_value);
  }
  if (typeof metric.value_numeric !== 'number') {
    return '—';
  }
  if (metric.unit === 'percent') {
    return `${(metric.value_numeric * 100).toFixed(1)}%`;
  }
  if (metric.unit === 'USD') {
    return `$${metric.value_numeric.toFixed(2)}`;
  }
  return formatNumber(metric.value_numeric);
}

function formatDocumentReviewRatingValue(key, item) {
  if (!item || typeof item !== 'object') {
    return null;
  }
  if (item.display_value !== null && item.display_value !== undefined && item.display_value !== '') {
    return String(item.display_value);
  }
  if (typeof item.value_numeric === 'number') {
    return key === 'beta' ? item.value_numeric.toFixed(2) : formatNumber(item.value_numeric);
  }
  if (item.value_text !== null && item.value_text !== undefined && item.value_text !== '') {
    return String(item.value_text);
  }
  return null;
}

function formatDocumentReviewQualityValue(item) {
  if (!item || typeof item !== 'object') {
    return '—';
  }
  if (item.display_value !== null && item.display_value !== undefined && item.display_value !== '') {
    return String(item.display_value);
  }
  if (typeof item.value_numeric === 'number') {
    return formatNumber(item.value_numeric);
  }
  if (item.value_text !== null && item.value_text !== undefined && item.value_text !== '') {
    return String(item.value_text);
  }
  return '—';
}

function formatDocumentReviewTargetRangeValue(key, item) {
  if (!item || typeof item !== 'object') {
    return '—';
  }
  if (key === 'percent_to_mid') {
    const displayPercent = formatPercentValue(item.display_value);
    if (displayPercent) {
      return displayPercent;
    }
  }
  if (item.display_value !== null && item.display_value !== undefined && item.display_value !== '') {
    return String(item.display_value);
  }
  if (typeof item.value_numeric === 'number') {
    if (key === 'percent_to_mid' || item.unit === 'percent') {
      return formatPercentValue(item.value_numeric) || '—';
    }
    if (item.unit === 'USD') {
      return `$${formatNumber(item.value_numeric)}`;
    }
    return formatNumber(item.value_numeric);
  }
  if (item.value_text !== null && item.value_text !== undefined && item.value_text !== '') {
    return String(item.value_text);
  }
  return '—';
}

function formatDocumentReviewProjectionValue(key, item) {
  if (!item || typeof item !== 'object') {
    return '—';
  }
  if (key === 'gain' || key === 'annual_total_return') {
    const displayPercent = formatProjectionPercentValue(item.display_value);
    if (displayPercent) {
      return displayPercent;
    }
  }
  if (item.display_value !== null && item.display_value !== undefined && item.display_value !== '') {
    return String(item.display_value);
  }
  if (typeof item.value_numeric === 'number') {
    if (key === 'gain' || key === 'annual_total_return' || item.unit === 'percent') {
      return formatProjectionPercentValue(item.value_numeric) || '—';
    }
    return formatNumber(item.value_numeric);
  }
  if (item.value_text !== null && item.value_text !== undefined && item.value_text !== '') {
    return String(item.value_text);
  }
  return '—';
}

function formatProjectionPercentValue(value) {
  const formatted = formatPercentValue(value);
  return formatted ? formatted.replace(/^\+/, '') : null;
}

function formatInstitutionalDecisionColumnLabel(item) {
  const iso = item && (item.period_end_date || item.as_of_date);
  if (iso) {
    const dt = new Date(`${iso}T00:00:00`);
    if (!Number.isNaN(dt.getTime())) {
      return `${Math.floor(dt.getUTCMonth() / 3) + 1}Q${dt.getUTCFullYear()}`;
    }
  }
  return item && item.period ? String(item.period) : 'Value';
}

function formatInstitutionalDecisionValue(key, item) {
  if (!item || typeof item !== 'object') {
    return '—';
  }
  if (key === 'holdings' && typeof item.value_numeric === 'number') {
    if (item.unit === 'shares') {
      return formatNumber(item.value_numeric / 1_000);
    }
    return formatNumber(item.value_numeric);
  }
  if (item.display_value !== null && item.display_value !== undefined && item.display_value !== '') {
    return String(item.display_value);
  }
  if (typeof item.value_numeric === 'number') {
    return formatNumber(item.value_numeric);
  }
  if (item.value_text !== null && item.value_text !== undefined && item.value_text !== '') {
    return String(item.value_text);
  }
  return '—';
}

function formatCapitalStructureValue(key, item) {
  if (!item || typeof item !== 'object') {
    return '—';
  }
  if (item.display_value !== null && item.display_value !== undefined && item.display_value !== '') {
    return String(item.display_value);
  }
  if (typeof item.value_numeric !== 'number') {
    if (item.value_text !== null && item.value_text !== undefined && item.value_text !== '') {
      return String(item.value_text);
    }
    return '—';
  }
  if (item.unit === 'USD') {
    return formatCompactCurrency(item.value_numeric);
  }
  if (item.unit === 'shares' || key === 'shares_outstanding') {
    return formatInteger(item.value_numeric);
  }
  if (item.unit === 'ratio' || key.includes('percent')) {
    return formatPercentValue(item.value_numeric) || '—';
  }
  return formatNumber(item.value_numeric);
}

function formatRawCapitalStructureValue(key, value) {
  if (value === null || value === undefined) {
    return '—';
  }
  if (typeof value === 'string' || typeof value === 'number') {
    return String(value);
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }
  if (typeof value !== 'object' || Array.isArray(value)) {
    return '—';
  }

  if (key === 'pension_plan') {
    if (value.notes) {
      return String(value.notes);
    }
    if (typeof value.defined_benefit === 'boolean') {
      return value.defined_benefit ? 'Defined Benefit' : 'No Defined Benefit';
    }
  }

  if (value.display !== null && value.display !== undefined && value.display !== '') {
    return String(value.display);
  }
  if (value.notes) {
    return String(value.notes);
  }
  if (typeof value.normalized === 'number') {
    if (value.unit === 'USD') {
      return formatCompactCurrency(value.normalized);
    }
    if (value.unit === 'shares' || key === 'shares_outstanding') {
      return formatInteger(value.normalized);
    }
    if (value.unit === 'ratio' || key.includes('percent')) {
      return formatPercentValue(value.normalized) || '—';
    }
    return formatNumber(value.normalized);
  }
  return '—';
}

function formatCurrentPositionValue(value) {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  if (typeof value === 'number') {
    return value.toFixed(1);
  }
  return String(value);
}

function formatAnnualFinancialValue(item) {
  if (!item || typeof item !== 'object') {
    return '—';
  }
  if (item.display_value !== null && item.display_value !== undefined && item.display_value !== '') {
    return String(item.display_value);
  }
  if (item.value_text !== null && item.value_text !== undefined && item.value_text !== '') {
    return String(item.value_text);
  }
  if (typeof item.value_numeric === 'number') {
    if (item.unit === 'ratio' || item.unit === 'percent') {
      return formatPercentValue(item.value_numeric) || formatNumber(item.value_numeric);
    }
    return formatNumber(item.value_numeric);
  }
  return '—';
}

function annualFinancialSeriesDecimalPlaces(series, columns) {
  let maxPlaces = 0;
  for (const column of columns) {
    const value = series?.[column.key];
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      continue;
    }
    maxPlaces = Math.max(maxPlaces, inferredDecimalPlaces(value));
  }
  return maxPlaces;
}

function inferredDecimalPlaces(value) {
  const tolerance = 1e-10;
  for (let places = 0; places <= 6; places += 1) {
    if (Math.abs(value - Number(value.toFixed(places))) < tolerance) {
      return places;
    }
  }
  return 6;
}

function formatAnnualFinancialRawValue(value, decimalPlaces = null) {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  if (typeof value === 'number') {
    if (typeof decimalPlaces === 'number' && decimalPlaces > 0) {
      return value.toFixed(decimalPlaces);
    }
    return formatNumber(value);
  }
  return String(value);
}

function firstAnnualRateEstimatePeriods(metrics) {
  for (const metric of metrics) {
    const estimate = metric?.estimated_cagr_pct;
    if (
      estimate &&
      typeof estimate === 'object' &&
      estimate.from_period &&
      estimate.to_period
    ) {
      return {
        from_period: String(estimate.from_period),
        to_period: String(estimate.to_period),
      };
    }
  }
  return null;
}

function annualRateSortKey(key) {
  const index = ANNUAL_RATES_ORDER.indexOf(key);
  return index === -1 ? ANNUAL_RATES_ORDER.length : index;
}

function formatAnnualRatePercent(value) {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return String(value);
  }
  return `${trimTrailingZero(numeric)}%`;
}

function formatQuarterlyValue(value) {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  if (typeof value === 'number') {
    return formatNumber(value);
  }
  return String(value);
}

function formatCompactCurrency(value) {
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) {
    return `$${trimTrailingZero(value / 1_000_000_000)}B`;
  }
  if (abs >= 1_000_000) {
    return `$${trimTrailingZero(value / 1_000_000)}M`;
  }
  return `$${formatInteger(value)}`;
}

function formatInteger(value) {
  return Math.round(value).toLocaleString('en-US');
}

function trimTrailingZero(value) {
  return value.toFixed(1).replace(/\.0$/, '');
}

function readPath(source, path) {
  let current = source;
  for (const segment of path) {
    if (!current || typeof current !== 'object' || !(segment in current)) {
      return { exists: false, value: undefined };
    }
    current = current[segment];
  }
  return { exists: true, value: current };
}

function readFirstPath(source, paths) {
  for (const path of paths) {
    if (!Array.isArray(path)) {
      continue;
    }
    const result = readPath(source, path);
    if (result.exists) {
      return result;
    }
  }
  return { exists: false, value: undefined };
}

function formatPercentValue(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const raw = String(value).trim();
  if (!raw) {
    return null;
  }
  if (raw.includes('%')) {
    return raw;
  }
  const numeric = Number(raw);
  if (!Number.isFinite(numeric)) {
    return null;
  }
  const percent = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return `${percent.toFixed(1)}%`;
}

function formatRatingEventLabel(event) {
  if (!event || typeof event !== 'object' || !event.value_text) {
    return null;
  }
  const eventType = capitalize(String(event.value_text));
  const eventDate = formatShortDate(event.period_end_date);
  return [eventType, eventDate].filter(Boolean).join(' ');
}

function formatShortDate(iso) {
  if (!iso || typeof iso !== 'string') {
    return null;
  }
  const dt = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(dt.getTime())) {
    return iso;
  }
  const month = dt.getUTCMonth() + 1;
  const day = dt.getUTCDate();
  const year = String(dt.getUTCFullYear()).slice(-2);
  return `${month}/${day}/${year}`;
}

function capitalize(value) {
  if (!value) {
    return '';
  }
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
}

module.exports = {
  SECTION_ORDER,
  ANNUAL_FINANCIAL_ROW_LABELS,
  ANNUAL_FINANCIAL_ROW_ORDER,
  SUMMARY_ORDER,
  SUMMARY_LABELS,
  RATING_ORDER,
  QUALITY_ORDER,
  NARRATIVE_CARD_ORDER,
  TARGET_RANGE_ORDER,
  PROJECTION_COLUMNS,
  PROJECTION_ROWS,
  INSTITUTIONAL_DECISION_ROWS,
  CURRENT_POSITION_ROWS,
  ANNUAL_RATES_ORDER,
  QUARTERLY_COLUMN_KEYS,
  CAPITAL_STRUCTURE_ORDER,
  buildDocumentReviewSections,
  buildDocumentReviewReportModel,
  findDocumentReviewItemByFactId,
  buildDocumentReviewSummary,
  buildDocumentReviewRatings,
  buildDocumentReviewQuality,
  buildDocumentReviewNarrativeCards,
  buildDocumentReviewTargetRange,
  buildDocumentReviewProjections,
  buildDocumentReviewInstitutionalDecisions,
  buildDocumentReviewAnnualFinancials,
  buildDocumentReviewAnnualRates,
  buildDocumentReviewQuarterlyTable,
  buildDocumentReviewCurrentPosition,
  buildDocumentReviewCapitalStructure,
  formatDocumentReviewValue,
  formatDocumentReviewMeta,
  formatDocumentReviewEvidenceLabel,
  formatDocumentReviewSummaryValue,
};
