/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildVisibleDocumentCompareSections,
  formatDocumentCompareMeta,
} = require('./documentCompare');

test('buildVisibleDocumentCompareSections removes empty sections and formats metadata', () => {
  const sections = buildVisibleDocumentCompareSections([
    {
      fact_nature: 'actual',
      title: 'Actual',
      items: [
        {
          label: 'FICO · is.net_income',
          period_type: 'FY',
          period_end_date: '2024-12-31',
          left_value: '100',
          right_value: '120',
        },
      ],
    },
    {
      fact_nature: 'opinion',
      title: 'Opinion',
      items: [],
    },
  ]);

  assert.deepEqual(sections, [
    {
      id: 'actual',
      title: 'Actual',
      items: [
        {
          label: 'FICO · is.net_income',
          period_type: 'FY',
          period_end_date: '2024-12-31',
          left_value: '100',
          right_value: '120',
          meta: 'FY · 12/31/2024',
        },
      ],
    },
  ]);
});

test('formatDocumentCompareMeta tolerates missing input', () => {
  assert.equal(formatDocumentCompareMeta(null), null);
});
