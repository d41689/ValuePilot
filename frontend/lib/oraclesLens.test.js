/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  confidenceTone,
  normalizeOracleLensRows,
  primaryCautionFlags,
} = require('./oraclesLens');

test('normalizeOracleLensRows emphasizes signal score with explanations', () => {
  const rows = normalizeOracleLensRows([
    {
      stock_id: 10,
      ticker: 'LENS',
      company_name: 'Lens Corp',
      signal_weighted_consensus_score: 3.1234,
      score_confidence: 'medium',
      conviction_score: 78,
      consensus_count: 4,
      aggregate_weight: 0.081,
      adders_count: 2,
      reducers_count: 1,
      median_holding_streak_quarters: 6,
      manager_signal_summary: {
        manager_signal_quality_coverage: 0.75,
      },
      score_explanation: {
        primary_reasons: [
          '3 high-signal managers hold this stock',
          '2 holders rank it as a top 10 position',
          'Median holding streak is 6 quarters',
        ],
        negative_reasons: ['1 of 4 holders has unknown manager type'],
      },
      caution_flags: [
        {
          key: 'old_period_selected',
          group: 'timing',
          severity: 'info',
          label: 'Selected period is old',
        },
      ],
    },
  ]);

  assert.equal(rows[0].signalScoreLabel, '3.12');
  assert.equal(rows[0].confidenceTone, 'warning');
  assert.equal(rows[0].convictionLabel, '78/100');
  assert.equal(rows[0].rawHoldersLabel, '4');
  assert.equal(rows[0].aggregateWeightLabel, '8.1%');
  assert.equal(rows[0].unknownCoverageLabel, '75% typed');
  assert.deepEqual(rows[0].reasonChips, [
    '3 high-signal managers hold this stock',
    '2 holders rank it as a top 10 position',
  ]);
});

test('primaryCautionFlags prioritizes severe grouped flags for the main table', () => {
  const flags = primaryCautionFlags([
    { key: 'old_period_selected', group: 'timing', severity: 'info' },
    { key: 'low_conviction', group: 'conviction', severity: 'warning' },
    { key: 'low_signal_quality', group: 'signal_quality', severity: 'warning' },
  ]);

  assert.deepEqual(
    flags.map((flag) => flag.key),
    ['low_signal_quality', 'low_conviction']
  );
});

test('confidenceTone maps confidence to badge variants', () => {
  assert.equal(confidenceTone('high'), 'success');
  assert.equal(confidenceTone('medium'), 'warning');
  assert.equal(confidenceTone('low'), 'secondary');
});
