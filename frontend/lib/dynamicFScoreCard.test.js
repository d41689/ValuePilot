/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  formatDynamicFScoreValue,
  normalizeDynamicFScoreCard,
} = require('./dynamicFScoreCard');

test('normalizeDynamicFScoreCard maps API card data for the current ticker', () => {
  const card = normalizeDynamicFScoreCard({
    years: [2022, 2023, 2024, 2025, 2026],
    rows: [
      {
        category: '盈利',
        check: 'ROA > 0',
        metric_key: 'score.piotroski.roa_positive',
        scores: [1, 1, 1, 1, 1],
        status: '✅',
        status_tone: 'success',
        comment: '最近 5 年全部通过，盈利底盘稳健。',
      },
      {
        category: '总计',
        check: 'F-Score',
        metric_key: 'score.piotroski.total',
        scores: [7, 7, 8, 7, 7],
        status: '--',
        status_tone: 'secondary',
        comment: '最新 F-Score 为 7，基本面维持强壮。',
      },
    ],
  });

  assert.deepEqual(card.years, ['2022', '2023', '2024', '2025', '2026']);
  assert.deepEqual(card.rows[0], {
    category: '盈利',
    check: 'ROA > 0',
    metricKey: 'score.piotroski.roa_positive',
    scores: [1, 1, 1, 1, 1],
    status: '✅',
    statusTone: 'success',
    comment: '最近 5 年全部通过，盈利底盘稳健。',
  });
});

test('normalizeDynamicFScoreCard returns empty rows for missing ticker facts', () => {
  assert.deepEqual(normalizeDynamicFScoreCard(null), { years: [], rows: [] });
  assert.deepEqual(normalizeDynamicFScoreCard({ years: [], rows: [] }), { years: [], rows: [] });
});

test('formatDynamicFScoreValue keeps score cells compact', () => {
  assert.equal(formatDynamicFScoreValue(1), '1');
  assert.equal(formatDynamicFScoreValue(7.5), '7.5');
  assert.equal(formatDynamicFScoreValue(null), '—');
});
