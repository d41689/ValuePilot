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
    ['snapshot.pe', 'pe_ratio', 'pe'],
    ['snapshot.relative_pe', 'relative_pe'],
    ['snapshot.dividend_yield', 'dividend_yield', 'yield'],
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
    ['quality.price_stability', 'price_stability'],
    ['quality.price_growth_persistence', 'price_growth_persistence'],
    ['quality.earnings_predictability', 'earnings_predictability'],
  ],
  targetMetrics: [
    ['target_18m_low', 'target.low', 'target_low'],
    ['target_18m_high', 'target.high', 'target_high'],
    ['target_18m_midpoint', 'target.midpoint', 'target_midpoint'],
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
    slotGroups.map((candidates) => {
      const item = pickFirstMatchingItem(sections, candidates, displayedFactIds);
      if (!item) {
        return null;
      }
      displayedFactIds.add(item.fact_id);
      return item;
    }).filter(Boolean);

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

module.exports = {
  SECTION_ORDER,
  buildDocumentReviewSections,
  buildDocumentReviewReportModel,
  findDocumentReviewItemByFactId,
  formatDocumentReviewValue,
  formatDocumentReviewMeta,
  formatDocumentReviewEvidenceLabel,
};
