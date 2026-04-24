/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildDocumentReviewSections,
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
