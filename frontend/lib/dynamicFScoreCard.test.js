/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  dynamicFScoreYears,
  dynamicFScoreRows,
  getDynamicFScoreTotalRow,
} = require('./dynamicFScoreCard');

test('dynamic F-Score card model contains requested five-year table', () => {
  assert.deepEqual(dynamicFScoreYears, ['2022', '2023', '2024', '2025', '2026']);
  assert.equal(dynamicFScoreRows.length, 5);

  assert.deepEqual(dynamicFScoreRows[0], {
    category: '盈利',
    check: 'ROA > 0',
    scores: [1, 1, 1, 1, 1],
    status: '✅',
    statusTone: 'success',
    comment: '底盘极其稳健。',
  });

  assert.deepEqual(dynamicFScoreRows[1], {
    category: '',
    check: 'CFO>ROA',
    scores: [1, 1, 0, 0, 0],
    status: '❌',
    statusTone: 'danger',
    comment: '警惕：利润调节风险。',
  });

  assert.deepEqual(getDynamicFScoreTotalRow(), {
    category: '总计',
    check: 'F-Score',
    scores: [7, 7, 8, 7, 7],
    status: '--',
    statusTone: 'secondary',
    comment: '结论：基本面维持强壮。',
  });
});
