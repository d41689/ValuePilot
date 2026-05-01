/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildDocumentReviewSections,
  buildDocumentReviewReportModel,
  findDocumentReviewItemByFactId,
  buildDocumentReviewSummary,
  buildDocumentReviewRatings,
  buildDocumentReviewQuality,
  buildDocumentReviewTargetRange,
  buildDocumentReviewProjections,
  buildDocumentReviewTotalReturn,
  buildDocumentReviewInstitutionalDecisions,
  buildDocumentReviewAnnualFinancials,
  buildDocumentReviewAnnualRates,
  buildDocumentReviewQuarterlyTable,
  buildDocumentReviewNarrativeCards,
  buildDocumentReviewCapitalStructure,
  buildDocumentReviewCurrentPosition,
  formatDocumentReviewValue,
  formatDocumentReviewMeta,
} = require('./documentReview');

test('buildDocumentReviewSections preserves Value Line module order and formats items', () => {
  const sections = buildDocumentReviewSections([
    {
      key: 'quarterly_tables',
      label: 'Quarterly Tables',
      items: [
        {
          metric_key: 'eps.basic',
          label: 'EPS',
          display_value: null,
          value_numeric: 1.25,
          unit: 'USD',
          period_type: 'Q',
          period_end_date: '2026-03-31',
          source_type: 'parsed',
          is_current: true,
          editable: true,
          lineage_available: true,
          lineage: {
            page_number: 1,
            original_text_snippet: 'EPS 1.25',
          },
        },
      ],
    },
    {
      key: 'ratings_quality',
      label: 'Ratings & Quality',
      items: [
        {
          metric_key: 'rating.timeliness',
          label: 'Timeliness',
          display_value: '2',
          value_numeric: 2,
          unit: 'rank',
          period_type: 'AS_OF',
          as_of_date: '2026-01-02',
          source_type: 'manual',
          is_current: true,
          editable: true,
          lineage_available: false,
          lineage: null,
        },
      ],
    },
  ]);

  assert.deepEqual(
    sections.map((section) => section.key),
    ['ratings_quality', 'quarterly_tables']
  );

  assert.equal(sections[0].items[0].valueLabel, '2');
  assert.equal(sections[0].items[0].meta, 'AS_OF · 1/2/2026 · manual · Current');
  assert.equal(sections[0].items[0].evidenceLabel, 'No lineage');

  assert.equal(sections[1].items[0].valueLabel, '1.25 USD');
  assert.equal(sections[1].items[0].meta, 'Q · 3/31/2026 · parsed · Current');
  assert.equal(sections[1].items[0].evidenceLabel, 'p.1');
});

test('formatDocumentReviewValue prefers display value and falls back to numeric with unit', () => {
  assert.equal(formatDocumentReviewValue({ display_value: '$68.11', value_numeric: 68.11 }), '$68.11');
  assert.equal(formatDocumentReviewValue({ value_numeric: 0.052, unit: 'ratio' }), '0.052 ratio');
  assert.equal(formatDocumentReviewValue({ value_text: 'B++' }), 'B++');
  assert.equal(formatDocumentReviewValue({}), 'Not available');
});

test('formatDocumentReviewMeta handles missing dates and non-current facts', () => {
  assert.equal(
    formatDocumentReviewMeta({
      period_type: 'FY',
      period_end_date: '2026-12-31',
      source_type: 'parsed',
      is_current: false,
    }),
    'FY · 12/31/2026 · parsed · Historical'
  );
  assert.equal(
    formatDocumentReviewMeta({
      source_type: 'manual',
      is_current: true,
    }),
    'manual · Current'
  );
});

test('buildDocumentReviewReportModel maps grouped facts into report regions and tables', () => {
  const report = buildDocumentReviewReportModel([
    {
      key: 'identity_header',
      label: 'Identity & Header',
      items: [
        {
          fact_id: 1,
          metric_key: 'mkt.price',
          label: 'Price',
          display_value: '$68.11',
          value_numeric: 68.11,
          unit: 'USD',
          period_type: 'AS_OF',
          as_of_date: '2026-01-02',
          source_type: 'parsed',
          is_current: true,
          editable: true,
          lineage_available: true,
          lineage: { page_number: 1, original_text_snippet: 'Recent price $68.11' },
        },
        {
          fact_id: 2,
          metric_key: 'snapshot.pe',
          label: 'P/E Ratio',
          display_value: '18.4',
          value_numeric: 18.4,
          unit: 'ratio',
          period_type: 'AS_OF',
          as_of_date: '2026-01-02',
          source_type: 'parsed',
          is_current: true,
          editable: true,
          lineage_available: true,
          lineage: { page_number: 1, original_text_snippet: 'P/E Ratio 18.4' },
        },
      ],
    },
    {
      key: 'ratings_quality',
      label: 'Ratings & Quality',
      items: [
        {
          fact_id: 3,
          metric_key: 'rating.timeliness',
          label: 'Timeliness',
          display_value: '2',
          value_numeric: 2,
          unit: 'rank',
          period_type: 'AS_OF',
          as_of_date: '2026-01-02',
          source_type: 'parsed',
          is_current: true,
          editable: true,
          lineage_available: true,
          lineage: { page_number: 1, original_text_snippet: 'Timeliness 2' },
        },
        {
          fact_id: 4,
          metric_key: 'rating.safety',
          label: 'Safety',
          display_value: '1',
          value_numeric: 1,
          unit: 'rank',
          period_type: 'AS_OF',
          as_of_date: '2026-01-02',
          source_type: 'parsed',
          is_current: true,
          editable: true,
          lineage_available: true,
          lineage: { page_number: 1, original_text_snippet: 'Safety 1' },
        },
        {
          fact_id: 5,
          metric_key: 'quality.financial_strength',
          label: 'Financial Strength',
          display_value: 'A',
          value_text: 'A',
          unit: null,
          period_type: 'AS_OF',
          as_of_date: '2026-01-02',
          source_type: 'parsed',
          is_current: true,
          editable: true,
          lineage_available: true,
          lineage: { page_number: 1, original_text_snippet: 'Financial Strength A' },
        },
      ],
    },
    {
      key: 'target_projection',
      label: 'Target & Projection',
      items: [
        {
          fact_id: 6,
          metric_key: 'target_18m_low',
          label: 'Target Low',
          display_value: '$74',
          value_numeric: 74,
          unit: 'USD',
          period_type: 'AS_OF',
          as_of_date: '2026-01-02',
          source_type: 'parsed',
          is_current: true,
          editable: true,
          lineage_available: true,
          lineage: { page_number: 1, original_text_snippet: 'Low 74' },
        },
        {
          fact_id: 7,
          metric_key: 'target_18m_high',
          label: 'Target High',
          display_value: '$92',
          value_numeric: 92,
          unit: 'USD',
          period_type: 'AS_OF',
          as_of_date: '2026-01-02',
          source_type: 'parsed',
          is_current: true,
          editable: true,
          lineage_available: true,
          lineage: { page_number: 1, original_text_snippet: 'High 92' },
        },
      ],
    },
    {
      key: 'annual_financials',
      label: 'Annual Financials',
      items: [
        {
          fact_id: 8,
          metric_key: 'is.sales',
          label: 'Sales',
          display_value: '3500',
          value_numeric: 3500,
          unit: 'USD',
          period_type: 'FY',
          period_end_date: '2024-12-31',
          source_type: 'parsed',
          is_current: true,
          editable: true,
          lineage_available: true,
          lineage: { page_number: 1, original_text_snippet: 'Sales 3500' },
        },
        {
          fact_id: 9,
          metric_key: 'is.sales',
          label: 'Sales',
          display_value: '3700',
          value_numeric: 3700,
          unit: 'USD',
          period_type: 'FY',
          period_end_date: '2025-12-31',
          source_type: 'parsed',
          is_current: true,
          editable: true,
          lineage_available: true,
          lineage: { page_number: 1, original_text_snippet: 'Sales 3700' },
        },
        {
          fact_id: 10,
          metric_key: 'eps.normalized',
          label: 'EPS',
          display_value: '3.10',
          value_numeric: 3.1,
          unit: 'USD',
          period_type: 'FY',
          period_end_date: '2024-12-31',
          source_type: 'parsed',
          is_current: true,
          editable: true,
          lineage_available: true,
          lineage: { page_number: 1, original_text_snippet: 'EPS 3.10' },
        },
      ],
    },
    {
      key: 'quarterly_tables',
      label: 'Quarterly Tables',
      items: [
        {
          fact_id: 11,
          metric_key: 'eps.normalized',
          label: 'EPS',
          display_value: '0.74',
          value_numeric: 0.74,
          unit: 'USD',
          period_type: 'Q',
          period_end_date: '2025-09-30',
          source_type: 'parsed',
          is_current: true,
          editable: true,
          lineage_available: true,
          lineage: { page_number: 1, original_text_snippet: 'EPS 0.74' },
        },
      ],
    },
    {
      key: 'narrative',
      label: 'Narrative',
      items: [
        {
          fact_id: 12,
          metric_key: 'business.description',
          label: 'Business',
          display_value: 'Water heaters and boilers.',
          value_text: 'Water heaters and boilers.',
          period_type: 'AS_OF',
          as_of_date: '2026-01-02',
          source_type: 'parsed',
          is_current: true,
          editable: true,
          lineage_available: true,
          lineage: { page_number: 1, original_text_snippet: 'Business description' },
        },
      ],
    },
  ]);

  assert.deepEqual(
    report.headerMetrics.map((item) => item.label),
    ['Price', 'P/E Ratio']
  );
  assert.deepEqual(
    report.ratingMetrics.map((item) => item.label),
    ['Timeliness', 'Safety']
  );
  assert.deepEqual(
    report.qualityMetrics.map((item) => item.label),
    ['Financial Strength']
  );
  assert.deepEqual(
    report.targetMetrics.map((item) => item.label),
    ['Target Low', 'Target High']
  );
  assert.deepEqual(report.annualTable.columns.map((column) => column.label), ['2024', '2025']);
  assert.equal(report.annualTable.rows[0].label, 'Sales');
  assert.equal(report.annualTable.rows[0].cells[1].valueLabel, '3700');
  assert.equal(report.quarterlyTable.columns[0].label, 'Q3 2025');
  assert.equal(report.narrativeItems[0].valueLabel, 'Water heaters and boilers.');
  assert.ok(report.displayedFactIds.has(1));
  assert.ok(report.displayedFactIds.has(12));
});

test('findDocumentReviewItemByFactId finds selected items from the report model', () => {
  const report = buildDocumentReviewReportModel([
    {
      key: 'identity_header',
      label: 'Identity & Header',
      items: [
        {
          fact_id: 21,
          metric_key: 'mkt.price',
          label: 'Price',
          display_value: '$70',
          value_numeric: 70,
          unit: 'USD',
          period_type: 'AS_OF',
          as_of_date: '2026-01-02',
          source_type: 'manual',
          is_current: true,
          editable: true,
          lineage_available: false,
          lineage: null,
        },
      ],
    },
  ]);

  const item = findDocumentReviewItemByFactId(report, 21);
  assert.equal(item.label, 'Price');
  assert.equal(item.meta, 'AS_OF · 1/2/2026 · manual · Current');
  assert.equal(findDocumentReviewItemByFactId(report, 999), null);
});

test('buildDocumentReviewSummary preserves metric order and formats fallback values', () => {
  const metrics = buildDocumentReviewSummary({
    recent_price: {
      metric_key: 'mkt.price',
      label: 'Recent Price',
      display_value: '$68.11',
      value_numeric: 68.11,
      unit: 'USD',
    },
    pe_ratio: {
      metric_key: 'val.pe',
      label: 'P/E Ratio',
      display_value: '18.5',
      value_numeric: 18.5,
      unit: 'ratio',
    },
    pe_trailing: {
      metric_key: 'val.pe_trailing',
      label: 'P/E Trailing',
      display_value: null,
      value_numeric: 17.9,
      unit: 'ratio',
    },
    pe_median: null,
    relative_pe_ratio: {
      metric_key: 'val.relative_pe',
      label: 'Relative P/E Ratio',
      display_value: '0.93',
      value_numeric: 0.93,
      unit: 'ratio',
    },
    dividend_yield: {
      metric_key: 'val.dividend_yield',
      label: "Div'd Yld",
      display_value: null,
      value_numeric: 0.02,
      unit: 'percent',
    },
  });

  assert.deepEqual(
    metrics.map((metric) => metric.key),
    ['recent_price', 'pe_ratio', 'pe_trailing', 'pe_median', 'relative_pe_ratio', 'dividend_yield']
  );
  assert.equal(metrics[0].displayValue, '$68.11');
  assert.equal(metrics[2].displayValue, '17.9');
  assert.equal(metrics[3].displayValue, '—');
  assert.equal(metrics[5].displayValue, '2.0%');
});

test('buildDocumentReviewRatings combines rating facts with rating event evidence', () => {
  const ratings = buildDocumentReviewRatings(
    [
      {
        key: 'ratings_quality',
        label: 'Ratings & Quality',
        items: [
          {
            metric_key: 'rating.timeliness',
            label: 'Timeliness',
            display_value: '4',
            value_numeric: 4,
          },
          {
            metric_key: 'rating.safety',
            label: 'Safety',
            display_value: null,
            value_numeric: 2,
          },
          {
            metric_key: 'rating.technical',
            label: 'Technical',
            display_value: '3',
            value_numeric: 3,
          },
          {
            metric_key: 'risk.beta',
            label: 'Beta',
            display_value: null,
            value_numeric: 0.8,
          },
        ],
      },
    ],
    [
      {
        mapping_id: 'rating.timeliness.event',
        value_text: 'lowered',
        period_end_date: '2025-12-26',
      },
      {
        mapping_id: 'rating.safety.event',
        value_text: 'lowered',
        period_end_date: '2024-01-19',
      },
      {
        mapping_id: 'rating.technical.event',
        value_text: 'lowered',
        period_end_date: '2025-08-22',
      },
    ]
  );

  assert.deepEqual(
    ratings.map((rating) => [rating.key, rating.label, rating.displayValue]),
    [
      ['timeliness', 'TIMELINESS', '4 Lowered 12/26/25'],
      ['safety', 'SAFETY', '2 Lowered 1/19/24'],
      ['technical', 'TECHNICAL', '3 Lowered 8/22/25'],
      ['beta', 'BETA', '0.80'],
    ]
  );
});

test('buildDocumentReviewQuality maps fact-backed quality metrics in requested order', () => {
  const quality = buildDocumentReviewQuality([
    {
      key: 'ratings_quality',
      label: 'Ratings & Quality',
      items: [
        {
          metric_key: 'quality.stock_price_stability',
          label: 'Stock Price Stability',
          value_numeric: 80,
          unit: 'score',
        },
        {
          metric_key: 'quality.financial_strength',
          label: 'Financial Strength',
          display_value: 'A',
          value_text: 'A',
          unit: null,
        },
        {
          metric_key: 'quality.price_growth_persistence',
          label: 'Price Growth Persistence',
          value_numeric: 70,
          unit: 'score',
        },
        {
          metric_key: 'quality.earnings_predictability',
          label: 'Earnings Predictability',
          value_numeric: 85,
          unit: 'score',
        },
      ],
    },
  ]);

  assert.deepEqual(quality, [
    { key: 'financial_strength', label: 'Financial Strength', displayValue: 'A' },
    { key: 'price_stability', label: 'Price Stability', displayValue: '80' },
    { key: 'price_growth_persistence', label: 'Price Growth Persistence', displayValue: '70' },
    { key: 'earnings_predictability', label: 'Earnings Predictability', displayValue: '85' },
  ]);
});

test('buildDocumentReviewTargetRange maps 18-month target facts in requested order', () => {
  const targetRange = buildDocumentReviewTargetRange([
    {
      key: 'target_projection',
      label: 'Target & Projection',
      items: [
        {
          metric_key: 'target_18m_high',
          label: '18-Month High',
          display_value: '$92',
          value_numeric: 92,
          unit: 'USD',
        },
        {
          metric_key: 'target_18m_upside_pct',
          label: '% to Mid',
          display_value: '0.22',
          value_numeric: 0.22,
          unit: 'percent',
        },
        {
          metric_key: 'target_18m_mid',
          label: '18-Month Midpoint',
          display_value: '$83',
          value_numeric: 83,
          unit: 'USD',
        },
        {
          metric_key: 'target_18m_low',
          label: '18-Month Low',
          display_value: '$74',
          value_numeric: 74,
          unit: 'USD',
        },
      ],
    },
  ]);

  assert.deepEqual(
    targetRange.map((metric) => [metric.key, metric.label, metric.displayValue]),
    [
      ['low', 'Low', '$74'],
      ['high', 'High', '$92'],
      ['midpoint', 'Midpoint', '$83'],
      ['percent_to_mid', '% to Mid', '22.0%'],
    ]
  );
});

test('buildDocumentReviewProjections maps high and low scenarios into a table', () => {
  const projections = buildDocumentReviewProjections([
    {
      key: 'target_projection',
      label: 'Target & Projection',
      items: [
        {
          metric_key: 'long_term_projection_low_total_return_pct',
          label: 'Low Annual Total Return',
          display_value: '-8%',
          value_numeric: -0.08,
          unit: 'ratio',
        },
        {
          metric_key: 'long_term_projection_high_price',
          label: 'High Price',
          display_value: '405',
          value_numeric: 405,
          unit: 'USD',
        },
        {
          metric_key: 'long_term_projection_high_price_gain_pct',
          label: 'High Price Gain',
          display_value: '+90%',
          value_numeric: 0.9,
          unit: 'ratio',
        },
        {
          metric_key: 'long_term_projection_low_price_gain_pct',
          label: 'Low Price Gain',
          display_value: '-18%',
          value_numeric: -0.18,
          unit: 'ratio',
        },
        {
          metric_key: 'long_term_projection_high_total_return_pct',
          label: 'High Annual Total Return',
          display_value: '0.18',
          value_numeric: 0.18,
          unit: 'ratio',
        },
        {
          metric_key: 'long_term_projection_low_price',
          label: 'Low Price',
          display_value: null,
          value_numeric: 300,
          unit: 'USD',
        },
      ],
    },
  ]);

  assert.deepEqual(
    projections.columns.map((column) => [column.key, column.label]),
    [
      ['price', 'Price'],
      ['gain', 'Gain'],
      ['annual_total_return', "Ann'l Total Return"],
    ]
  );
  assert.deepEqual(
    projections.rows.map((row) => [
      row.key,
      row.label,
      row.cells.map((cell) => cell.displayValue),
    ]),
    [
      ['high', 'High', ['405', '90%', '18.0%']],
      ['low', 'Low', ['300', '-18%', '-8%']],
    ]
  );
});

test('buildDocumentReviewTotalReturn maps Value Line total return into a table', () => {
  const table = buildDocumentReviewTotalReturn({
    as_of_date: '2025-12-29',
    unit: 'percent',
    source: 'value_line',
    series: [
      { name: 'this_stock', window_years: 1, value_pct: 24.4 },
      { name: 'this_stock', window_years: 3, value_pct: 117.1 },
      { name: 'this_stock', window_years: 5, value_pct: 150.2 },
      { name: 'vl_arithmetic_index', window_years: 1, value_pct: 3.6 },
      { name: 'vl_arithmetic_index', window_years: 3, value_pct: 39.2 },
      { name: 'vl_arithmetic_index', window_years: 5, value_pct: 68.5 },
    ],
  });

  assert.equal(table.unit, 'As of 12/29/25');
  assert.deepEqual(
    table.columns.map((column) => [column.key, column.label]),
    [
      ['1', '1 yr.'],
      ['3', '3 yr.'],
      ['5', '5 yr.'],
    ]
  );
  assert.deepEqual(
    table.rows.map((row) => [
      row.key,
      row.label,
      row.cells.map((cell) => cell.displayValue),
    ]),
    [
      ['this_stock', 'This Stock', ['24.4%', '117.1%', '150.2%']],
      ['vl_arithmetic_index', 'VL Arithmetic Index', ['3.6%', '39.2%', '68.5%']],
    ]
  );
});

test('buildDocumentReviewInstitutionalDecisions maps quarterly ownership facts into a table', () => {
  const institutionalDecisions = buildDocumentReviewInstitutionalDecisions([
    {
      key: 'institutional_decisions',
      label: 'Institutional Decisions',
      items: [
        {
          metric_key: 'ownership.institutional.to_sell',
          label: 'to Sell',
          display_value: null,
          value_numeric: 219,
          unit: 'count',
          period_type: 'Q',
          period_end_date: '2025-06-30',
        },
        {
          metric_key: 'ownership.institutional.holdings',
          label: 'Holdings',
          display_value: null,
          value_numeric: 137519000,
          unit: 'shares',
          period_type: 'Q',
          period_end_date: '2025-03-31',
        },
        {
          metric_key: 'ownership.institutional.to_buy',
          label: 'to Buy',
          display_value: null,
          value_numeric: 267,
          unit: 'count',
          period_type: 'Q',
          period_end_date: '2025-03-31',
        },
        {
          metric_key: 'ownership.institutional.to_sell',
          label: 'to Sell',
          display_value: null,
          value_numeric: 206,
          unit: 'count',
          period_type: 'Q',
          period_end_date: '2025-03-31',
        },
        {
          metric_key: 'ownership.institutional.to_buy',
          label: 'to Buy',
          display_value: null,
          value_numeric: 259,
          unit: 'count',
          period_type: 'Q',
          period_end_date: '2025-06-30',
        },
        {
          metric_key: 'ownership.institutional.holdings',
          label: 'Holdings',
          display_value: null,
          value_numeric: 140247000,
          unit: 'shares',
          period_type: 'Q',
          period_end_date: '2025-06-30',
        },
      ],
    },
  ]);

  assert.deepEqual(
    institutionalDecisions.columns.map((column) => [column.key, column.label]),
    [
      ['2025-03-31', '1Q2025'],
      ['2025-06-30', '2Q2025'],
    ]
  );
  assert.deepEqual(
    institutionalDecisions.rows.map((row) => [
      row.key,
      row.label,
      row.cells.map((cell) => cell.displayValue),
    ]),
    [
      ['to_buy', 'to Buy', ['267', '259']],
      ['to_sell', 'to Sell', ['206', '219']],
      ['holdings', "Hld's(000)", ['137519', '140247']],
    ]
  );
});

test('buildDocumentReviewAnnualFinancials maps annual facts without merging same-label metrics', () => {
  const table = buildDocumentReviewAnnualFinancials(
    [
      {
        key: 'annual_financials',
        label: 'Annual Financials',
        items: [
          {
            metric_key: 'per_share.sales',
            label: 'Sales',
            display_value: '24.50',
            value_numeric: 24.5,
            unit: 'USD_per_share',
            period_type: 'FY',
            period_end_date: '2024-12-31',
          },
        ],
      },
    ],
    {
      meta: {
        historical_years: [2024, 2025, 2026],
        estimate_years: [2025, 2026],
        projection_year_range: '2028-2030',
      },
      per_unit_metrics: {
        sales: {
          2024: 5.79,
          2025: 9.1,
          2026: 12.0,
          projection_2028_2030: 15.6,
        },
        earnings: {
          2024: 3.21,
          2025: 5.35,
          2026: 7.15,
          projection_2028_2030: 10.0,
        },
      },
      valuation_metrics: {
        price_to_book_value_pct: {
          2024: 411.3,
          2025: 500,
          2026: null,
          projection_2028_2030: 200,
        },
        avg_annual_pe_ratio: {
          2024: 38.8,
          2025: 37.3,
          2026: null,
          projection_2028_2030: 35.0,
        },
        avg_annual_dividend_yield_pct: {
          2024: 1.2,
          2025: null,
          2026: null,
          projection_2028_2030: 1.0,
        },
      },
      income_statement_usd_millions: {
        sales: {
          2024: 1113.6,
          2025: 1750.0,
          2026: 2300.0,
          projection_2028_2030: 2960.0,
        },
        operating_margin_pct: {
          2024: 85.5,
          2025: 88.0,
          2026: 86.0,
          projection_2028_2030: 86.0,
        },
      },
      income_statement_ratios_pct: {
        income_tax_rate_pct: {
          2024: 25.5,
          2025: 19.0,
          2026: 18.0,
          projection_2028_2030: 18.0,
        },
        net_profit_margin_pct: {
          2024: 55.5,
          2025: 58.0,
          2026: 59.0,
          projection_2028_2030: 65.0,
        },
      },
      balance_sheet_and_returns_usd_millions: {
        working_capital: {
          2024: 1649.3,
          2025: 500.0,
          2026: 1150.0,
          projection_2028_2030: 2200.0,
        },
        return_on_total_capital_pct: {
          2024: 10.5,
          2025: 15.0,
          2026: 17.0,
          projection_2028_2030: 17.5,
        },
        return_on_shareholders_equity_pct: {
          2024: 10.5,
          2025: 15.0,
          2026: 17.0,
          projection_2028_2030: 17.5,
        },
        retained_to_common_equity_pct: {
          2024: 5.7,
          2025: 11.0,
          2026: 13.0,
          projection_2028_2030: 13.5,
        },
        all_dividends_to_net_profit_pct: {
          2024: 45.0,
          2025: 28.0,
          2026: 22.0,
          projection_2028_2030: 20.0,
        },
      },
    }
  );

  assert.deepEqual(
    table.columns.map((column) => column.label),
    ['2024', '2025', '2026', '2028-2030']
  );
  assert.deepEqual(
    table.rows[0].cells.map((cell) => cell.isEstimate),
    [false, true, true, true]
  );
  assert.deepEqual(
    table.rows.map((row) => [
      row.key,
      row.label,
      row.cells.map((cell) => cell.displayValue),
    ]),
    [
      ['per_share.sales', 'Sales / Share', ['5.79', '9.10', '12.00', '15.60']],
      ['per_share.eps', 'Earnings / Share', ['3.21', '5.35', '7.15', '10.00']],
      ['is.sales', 'Sales ($M)', ['1113.6', '1750.0', '2300.0', '2960.0']],
      ['is.operating_margin', 'Operating Margin', ['85.5%', '88.0%', '86.0%', '86.0%']],
      ['is.income_tax_rate', 'Income Tax Rate', ['25.5%', '19.0%', '18.0%', '18.0%']],
      ['is.net_profit_margin', 'Net Profit Margin', ['55.5%', '58.0%', '59.0%', '65.0%']],
      ['bs.working_capital', 'Working Capital ($M)', ['1649.3', '500.0', '1150.0', '2200.0']],
      ['bs.return_on_total_capital', 'Return on Total Capital', ['10.5%', '15.0%', '17.0%', '17.5%']],
      ['bs.return_on_equity', 'Return on Shareholders Equity', ['10.5%', '15.0%', '17.0%', '17.5%']],
      ['bs.retained_to_common_equity', 'Retained to Common Equity', ['5.7%', '11.0%', '13.0%', '13.5%']],
      ['bs.dividends_to_net_profit', 'All Dividends to Net Profit', ['45%', '28%', '22%', '20%']],
      ['val.price_to_book', 'Price to Book Value', ['411.3%', '500.0%', '—', '200.0%']],
      ['val.avg_pe', 'Avg Annual P/E Ratio', ['38.8', '37.3', '—', '35.0']],
      ['val.avg_dividend_yield', 'Avg Annual Dividend Yield', ['1.2%', '—', '—', '1.0%']],
    ]
  );
});

test('buildDocumentReviewCapitalStructure maps the parser capital structure block', () => {
  const capitalMetrics = buildDocumentReviewCapitalStructure(
    [
      {
        key: 'capital_structure',
        label: 'Capital Structure',
        items: [
          {
            metric_key: 'mkt.market_cap',
            label: 'Market Cap',
            display_value: null,
            value_numeric: 40900000000,
            unit: 'USD',
            period_type: 'AS_OF',
            period_end_date: '2025-09-30',
          },
          {
            metric_key: 'equity.shares_outstanding',
            label: 'Shares Outstanding',
            display_value: null,
            value_numeric: 192800000,
            unit: 'shares',
            period_type: 'AS_OF',
            period_end_date: '2025-09-30',
          },
        ],
      },
    ],
    {
      as_of: '2025-09-30',
      total_debt: {
        display: 'None',
        normalized: null,
        unit: 'USD',
      },
      lt_interest_percent_of_capital: null,
      leases_uncapitalized: null,
      pension_plan: {
        defined_benefit: false,
        notes: 'No Defined Benefit Pension Plan',
      },
      common_stock: {
        shares_outstanding: {
          display: '192,800,000',
          normalized: 192800000.0,
          unit: 'shares',
        },
        as_of: '2025-09-30',
      },
      market_cap: {
        display: '$40.9 billion',
        normalized: 40900000000.0,
        unit: 'USD',
        market_cap_category: 'Large Cap',
      },
    }
  );

  assert.deepEqual(
    capitalMetrics.map((metric) => [metric.key, metric.label, metric.displayValue]),
    [
      ['as_of', 'As Of', '2025-09-30'],
      ['total_debt', 'Total Debt', 'None'],
      ['lt_interest_percent_of_capital', 'LT Interest % of Capital', '—'],
      ['leases_uncapitalized', 'Leases Uncapitalized', '—'],
      ['pension_plan', 'Pension Plan', 'No Defined Benefit Pension Plan'],
      ['shares_outstanding', 'Shares Outstanding', '192,800,000'],
      ['common_stock_as_of', 'Common Stock As Of', '2025-09-30'],
      ['market_cap', 'Market Cap', '$40.9B'],
      ['market_cap_category', 'Market Cap Category', 'Large Cap'],
    ]
  );
});

test('buildDocumentReviewAnnualRates maps parser annual rates into a table', () => {
  const table = buildDocumentReviewAnnualRates({
    unit: 'per_share',
    metrics: [
      {
        metric_key: 'sales',
        past_10y_cagr_pct: 9,
        past_5y_cagr_pct: 13.5,
        estimated_cagr_pct: {
          from_period: '2022-2024',
          to_period: '2028-2030',
          value: 7.5,
        },
      },
      {
        metric_key: 'cash_flow',
        display_name: 'Cash Flow',
        past_10y_cagr_pct: 14.5,
        past_5y_cagr_pct: 15.5,
        estimated_cagr_pct: {
          from_period: '2022-2024',
          to_period: '2028-2030',
          value: 11,
        },
      },
    ],
  });

  assert.deepEqual(
    table.columns.map((column) => column.label),
    ['Past 10Y', 'Past 5Y', 'Est. 2022-2024 to 2028-2030']
  );
  assert.deepEqual(
    table.rows.map((row) => [
      row.key,
      row.label,
      row.cells.map((cell) => cell.displayValue),
      row.cells.map((cell) => cell.isEstimate),
    ]),
    [
      ['sales', 'Sales', ['9%', '13.5%', '7.5%'], [false, false, true]],
      ['cash_flow', 'Cash Flow', ['14.5%', '15.5%', '11%'], [false, false, true]],
    ]
  );
});

test('buildDocumentReviewQuarterlyTable maps parser quarterly blocks into rows by year', () => {
  const table = buildDocumentReviewQuarterlyTable({
    unit: 'USD_millions',
    quarter_month_order: ['Mar', 'Jun', 'Sep', 'Dec'],
    by_year: [
      {
        calendar_year: 2024,
        quarters: {
          Q1: { value: 256.8, fact_nature: 'actual' },
          Q2: { value: 260.1, fact_nature: 'actual' },
          Q3: { value: 275.7, fact_nature: 'actual' },
          Q4: { value: 321, fact_nature: 'actual' },
        },
        full_year: { value: 1113.6, fact_nature: 'actual' },
      },
      {
        calendar_year: 2025,
        quarters: {
          Q1: { value: 368.4, fact_nature: 'estimate' },
          Q2: { value: 369.4, fact_nature: 'estimate' },
          Q3: { value: 487.7, fact_nature: 'estimate' },
          Q4: { value: 524.5, fact_nature: 'estimate' },
        },
        full_year: { value: 1750, fact_nature: 'estimate' },
      },
    ],
  });

  assert.equal(table.unit, 'USD_millions');
  assert.deepEqual(
    table.columns.map((column) => column.label),
    ['Mar', 'Jun', 'Sep', 'Dec', 'Year']
  );
  assert.deepEqual(
    table.rows.map((row) => [
      row.key,
      row.label,
      row.cells.map((cell) => cell.displayValue),
      row.cells.map((cell) => cell.isEstimate),
    ]),
    [
      ['2024', '2024', ['256.8', '260.1', '275.7', '321', '1113.6'], [false, false, false, false, false]],
      ['2025', '2025', ['368.4', '369.4', '487.7', '524.5', '1750'], [true, true, true, true, true]],
    ]
  );
});

test('buildDocumentReviewNarrativeCards maps evidence-only narrative fields', () => {
  const cards = buildDocumentReviewNarrativeCards([
    {
      mapping_id: 'company.business_description.as_of',
      value_text: 'Franco-Nevada is a gold-focused royalty and stream company.',
      period_end_date: '2025-12-26',
    },
    {
      mapping_id: 'analyst.commentary.as_of',
      value_text: 'The shares might not appeal to momentum investors.',
      period_end_date: '2025-12-26',
    },
    {
      mapping_id: 'rating.timeliness.event',
      value_text: 'lowered',
      period_end_date: '2025-12-26',
    },
  ]);

  assert.deepEqual(cards, [
    {
      key: 'business_narrative',
      title: 'BUSINESS NARRATIVE',
      body: 'Franco-Nevada is a gold-focused royalty and stream company.',
      meta: 'As of 12/26/25',
    },
    {
      key: 'analyst_comment',
      title: 'ANALYST COMMENT',
      body: 'The shares might not appeal to momentum investors.',
      meta: 'As of 12/26/25',
    },
  ]);
});

test('buildDocumentReviewCurrentPosition maps current position periods into a table', () => {
  const table = buildDocumentReviewCurrentPosition({
    unit: 'USD_millions',
    periods: [
      {
        label: '2023',
        period_end_date: '2023-12-31',
        assets: {
          cash_assets: 363.4,
          receivables: 596.0,
          inventory_lifo: null,
          other_current_assets: 43.5,
          total_current_assets: 1500.3,
        },
        liabilities: {
          accounts_payable: 600.4,
          debt_due: null,
          other_current_liabilities: 334.9,
          total_current_liabilities: 945.3,
        },
      },
      {
        label: '2024',
        period_end_date: '2024-12-31',
        assets: {
          cash_assets: 276.1,
          receivables: 541.4,
          inventory_lifo: null,
          other_current_assets: 43.3,
          total_current_assets: 1392.9,
        },
        liabilities: {
          accounts_payable: 588.7,
          debt_due: null,
          other_current_liabilities: 298.5,
          total_current_liabilities: 897.2,
        },
      },
      {
        label: '9/30/25',
        period_end_date: '2025-09-30',
        assets: {
          cash_assets: 172.8,
          receivables: 589.0,
          inventory_lifo: null,
          other_current_assets: 47.0,
          total_current_assets: 1316.1,
        },
        liabilities: {
          accounts_payable: 521.4,
          debt_due: null,
          other_current_liabilities: 312.1,
          total_current_liabilities: 852.5,
        },
      },
    ],
  });

  assert.deepEqual(
    table.columns.map((column) => column.label),
    ['2023', '2024', '9/30/25']
  );
  assert.deepEqual(
    table.rows.map((row) => [
      row.key,
      row.label,
      row.cells.map((cell) => cell.displayValue),
    ]),
    [
      ['cash_assets', 'Cash Assets', ['363.4', '276.1', '172.8']],
      ['receivables', 'Receivables', ['596.0', '541.4', '589.0']],
      ['inventory', 'Inventory', ['—', '—', '—']],
      ['other_current_assets', 'Other Current Assets', ['43.5', '43.3', '47.0']],
      ['total_current_assets', 'Total Current Assets', ['1500.3', '1392.9', '1316.1']],
      ['accounts_payable', 'Accounts Payable', ['600.4', '588.7', '521.4']],
      ['debt_due', 'Debt Due', ['—', '—', '—']],
      ['other_current_liabilities', 'Other Current Liabilities', ['334.9', '298.5', '312.1']],
      ['total_current_liabilities', 'Total Current Liabilities', ['945.3', '897.2', '852.5']],
    ]
  );
});

test('buildDocumentReviewCurrentPosition keeps keys unique for duplicate period end dates', () => {
  const table = buildDocumentReviewCurrentPosition({
    unit: 'USD_millions',
    periods: [
      {
        label: '2025',
        period_end_date: '2025-12-31',
        assets: { total_current_assets: 705.2 },
        liabilities: { total_current_liabilities: 849.2 },
      },
      {
        label: '12/31/25',
        period_end_date: '2025-12-31',
        assets: { total_current_assets: 698.8 },
        liabilities: { total_current_liabilities: 752.1 },
      },
    ],
  });

  assert.deepEqual(
    table.columns.map((column) => column.label),
    ['2025', '12/31/25']
  );
  assert.equal(new Set(table.columns.map((column) => column.key)).size, table.columns.length);
  for (const row of table.rows) {
    assert.equal(new Set(row.cells.map((cell) => cell.key)).size, row.cells.length);
  }
});
