/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildDocumentEvidenceSections,
  formatDocumentEvidencePeriod,
} = require('./documentEvidence');

test('buildDocumentEvidenceSections groups evidence into business, commentary, and ratings', () => {
  const sections = buildDocumentEvidenceSections([
    {
      mapping_id: 'company.business_description.as_of',
      value_text: 'Provides analytics software.',
      period_type: 'AS_OF',
      period_end_date: '2026-01-09',
      page_number: 1,
      original_text_snippet: 'Business: Provides analytics software.',
    },
    {
      mapping_id: 'analyst.commentary.as_of',
      value_text: 'Margins should expand through FY2027.',
      period_type: 'AS_OF',
      period_end_date: '2026-01-09',
      page_number: 1,
      original_text_snippet: 'Commentary: Margins should expand through FY2027.',
    },
    {
      mapping_id: 'rating.timeliness.event',
      value_text: 'raised',
      period_type: 'EVENT',
      period_end_date: '2025-12-19',
      page_number: 1,
      original_text_snippet: 'Timeliness 2 Raised 12/19/25',
      value_json: {
        type: 'raised',
        date: '2025-12-19',
        raw: 'Raised 12/19/25',
      },
    },
    {
      mapping_id: 'rating.technical.event',
      value_text: 'lowered',
      period_type: 'EVENT',
      period_end_date: '2025-11-01',
      page_number: 1,
      original_text_snippet: 'Technical 3 Lowered 11/01/25',
      value_json: {
        type: 'lowered',
        date: '2025-11-01',
        raw: 'Lowered 11/01/25',
      },
    },
  ]);

  assert.deepEqual(
    sections.map((section) => section.id),
    ['business', 'commentary', 'ratings']
  );

  assert.equal(sections[0].items[0].label, 'Business Description');
  assert.equal(sections[0].items[0].value, 'Provides analytics software.');
  assert.equal(sections[0].items[0].meta, 'As of 1/9/2026 · p.1');

  assert.equal(sections[1].items[0].label, 'Analyst Commentary');
  assert.equal(sections[1].items[0].value, 'Margins should expand through FY2027.');

  assert.equal(sections[2].items[0].label, 'Timeliness');
  assert.equal(sections[2].items[0].value, 'Raised');
  assert.equal(sections[2].items[0].meta, 'Event date 12/19/2025 · p.1');
  assert.equal(sections[2].items[0].detail, 'Raised 12/19/25');

  assert.equal(sections[2].items[1].label, 'Technical');
  assert.equal(sections[2].items[1].value, 'Lowered');
});

test('formatDocumentEvidencePeriod handles missing and invalid dates', () => {
  assert.equal(formatDocumentEvidencePeriod('AS_OF', '2026-01-09'), 'As of 1/9/2026');
  assert.equal(formatDocumentEvidencePeriod('EVENT', '2025-12-19'), 'Event date 12/19/2025');
  assert.equal(formatDocumentEvidencePeriod('AS_OF', null), null);
  assert.equal(formatDocumentEvidencePeriod('EVENT', 'not-a-date'), 'Event date not-a-date');
});
