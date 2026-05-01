/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  formatDynamicFScoreValue,
  normalizeDynamicFScoreCard,
  visibleFallbackFormulas,
} = require('./dynamicFScoreCard');

test('normalizeDynamicFScoreCard maps API card data for the current ticker', () => {
  const card = normalizeDynamicFScoreCard({
    years: [2022, 2023, 2024, 2025, 2026],
    rows: [
      {
        category: '盈利',
        check: 'ROA > 0',
        metric_key: 'score.piotroski.roa_positive',
        formula: 'returns.roa[Y] > 0',
        formula_details: {
          standard_definition: 'ROA is positive.',
          standard_formula: 'returns.roa[Y] > 0',
          fallback_formulas: ['is.net_income[Y] > 0'],
          used_formula: 'is.net_income[Y] > 0',
          used_values: [
            {
              metric_key: 'is.net_income',
              value_numeric: 80,
              period_end_date: '2022-12-31',
              fact_nature: 'actual',
            },
            {
              metric_key: 'is.net_income',
              value_numeric: 100,
              period_end_date: '2026-12-31',
              fact_nature: 'actual',
            },
          ],
        },
        scores: [1, 1, 1, 1, 1],
        score_fact_natures: ['actual', 'actual', 'actual', 'actual', 'estimate'],
        status: '✅',
        status_tone: 'success',
        comment: '最近 5 年全部通过，盈利底盘稳健。',
      },
      {
        category: '总计',
        check: 'F-Score',
        metric_key: 'score.piotroski.total',
        formula: '9 项 Piotroski 指标得分加总',
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
    formula: 'returns.roa[Y] > 0',
    formulaDetails: {
      standardDefinition: 'ROA is positive.',
      standardFormula: 'returns.roa[Y] > 0',
      fallbackFormulas: ['is.net_income[Y] > 0'],
      usedFormula: 'is.net_income[Y] > 0',
      usedValues: [
        {
          metricKey: 'is.net_income',
          valueNumeric: 80,
          periodEndDate: '2022-12-31',
          factNature: 'actual',
        },
        {
          metricKey: 'is.net_income',
          valueNumeric: 100,
          periodEndDate: '2026-12-31',
          factNature: 'actual',
        },
      ],
    },
    scores: [1, 1, 1, 1, 1],
    scoreFactNatures: ['actual', 'actual', 'actual', 'actual', 'estimate'],
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

test('visibleFallbackFormulas removes the used formula from fallback display', () => {
  assert.deepEqual(
    visibleFallbackFormulas({
      usedFormula: 'returns.total_capital[Y] > returns.total_capital[Y-1]',
      fallbackFormulas: [
        'returns.total_capital[Y] > returns.total_capital[Y-1]',
        'returns.total_capital[Y] > returns.total_capital[Y-1]',
        'returns.roa[Y] > returns.roa[Y-1]',
      ],
    }),
    ['returns.roa[Y] > returns.roa[Y-1]']
  );
});
