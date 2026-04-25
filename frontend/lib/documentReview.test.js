/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildDocumentReviewSections,
  buildDocumentReviewReportModel,
  findDocumentReviewItemByFactId,
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
