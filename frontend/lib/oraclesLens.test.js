/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildOracleLensQueryParams,
  confidenceTone,
  groupCautionFlags,
  missingDataReasons,
  normalizeOracleLensRows,
  normalizeQualityOverlay,
  normalizeValuationReference,
  primaryCautionFlags,
  radarBubbles,
  suggestedResearchSteps,
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
      quality_overlay: {
        piotroski_total: 8,
        return_on_total_capital: 0.24,
        return_on_equity: 0.31,
        net_profit_margin: 0.22,
        debt_to_capital: 0.18,
        owner_earnings_yield: 0.052,
        latest_price: 100,
        coverage: {
          value_line: true,
          price: true,
          owner_earnings: true,
          available_metrics: 6,
          expected_metrics: 6,
        },
        unavailable_reasons: [],
        provenance: {
          primary_source_document_id: 2655,
          source_document_ids: [2655],
          facts: [
            {
              label: 'return_on_total_capital',
              metric_key: 'bs.return_on_total_capital',
              source_document_id: 2655,
              source_type: 'parsed',
              period_type: 'FY',
              period_end_date: '2031-12-31',
            },
          ],
        },
      },
      holder_price_estimate_low: 92,
      holder_price_estimate_high: 118,
      current_price: 100,
      current_price_date: '2031-12-31',
      price_context: 'historical_snapshot',
      valuation_reference: 150,
      valuation_reference_label: 'Value Line 18-month target midpoint',
      valuation_reference_type: 'analyst_target_reference',
      valuation_reference_confidence: 'medium',
      discount_to_reference: 0.333333,
      valuation_state: {
        below_holder_estimate: false,
        below_selected_valuation_reference: true,
      },
      valuation_unavailable_reasons: [],
    },
  ]);

  assert.equal(rows[0].signalScoreLabel, '3.12');
  assert.equal(rows[0].confidenceTone, 'warning');
  assert.equal(rows[0].convictionLabel, '78/100');
  assert.equal(rows[0].rawHoldersLabel, '4');
  assert.equal(rows[0].aggregateWeightLabel, '8.1%');
  assert.equal(rows[0].unknownCoverageLabel, '75% typed');
  assert.equal(rows[0].quality.piotroskiLabel, '8');
  assert.equal(rows[0].quality.returnOnCapitalLabel, '24%');
  assert.equal(rows[0].quality.ownerEarningsYieldLabel, '5.2%');
  assert.equal(rows[0].quality.qualityCoverageLabel, '6/6 facts');
  assert.equal(rows[0].quality.primarySourceDocumentId, 2655);
  assert.deepEqual(rows[0].quality.sourceDocumentIds, [2655]);
  assert.equal(rows[0].quality.provenanceFacts[0].metric_key, 'bs.return_on_total_capital');
  assert.equal(rows[0].valuation.holderRangeLabel, '$92.00–$118.00');
  assert.equal(rows[0].valuation.currentPriceLabel, '$100.00');
  assert.equal(rows[0].valuation.currentPriceDateLabel, '2031-12-31');
  assert.equal(rows[0].valuation.priceContextLabel, 'Historical snapshot');
  assert.equal(rows[0].valuation.referenceLabel, '$150.00');
  assert.equal(rows[0].valuation.discountLabel, '33.3%');
  assert.equal(rows[0].valuation.referenceSourceLabel, 'Value Line 18-month target midpoint');
  assert.equal(rows[0].valuation.belowSelectedReference, true);
  assert.deepEqual(rows[0].reasonChips, [
    '3 high-signal managers hold this stock',
    '2 holders rank it as a top 10 position',
  ]);
});

test('buildOracleLensQueryParams serializes V1 dashboard filters', () => {
  assert.equal(
    buildOracleLensQueryParams({
      period: '2031-Q4',
      minHolders: 5,
      minSignalScore: 2.5,
      superinvestorOnly: false,
      sort: 'conviction',
    }),
    'period=2031-Q4&min_holders=5&superinvestor_only=false&min_signal_score=2.5&sort=conviction'
  );
});

test('radarBubbles maps candidate rows to compact visual signals', () => {
  const bubbles = radarBubbles([
    {
      stockId: 1,
      ticker: 'BIG',
      companyName: 'Big Weight',
      aggregateWeightLabel: '12.0%',
      addReduceLabel: '3 add / 0 reduce',
    },
    {
      stockId: 2,
      ticker: 'SMALL',
      companyName: 'Small Weight',
      aggregateWeightLabel: '1.0%',
      addReduceLabel: '0 add / 2 reduce',
    },
  ]);

  assert.equal(bubbles[0].sizeClass, 'h-24 w-24');
  assert.equal(bubbles[0].toneClass.includes('emerald'), true);
  assert.equal(bubbles[1].sizeClass, 'h-14 w-14');
  assert.equal(bubbles[1].toneClass.includes('amber'), true);
});

test('normalizeValuationReference keeps missing reference explicit', () => {
  const valuation = normalizeValuationReference({
    current_price: 100,
    valuation_reference_type: 'missing',
    valuation_reference_confidence: 'unavailable',
    valuation_unavailable_reasons: ['missing valuation reference'],
  });

  assert.equal(valuation.currentPriceLabel, '$100.00');
  assert.equal(valuation.referenceLabel, '—');
  assert.equal(valuation.referenceSourceLabel, 'Missing valuation reference');
  assert.equal(valuation.discountLabel, '—');
  assert.equal(valuation.referenceConfidence, 'unavailable');
  assert.deepEqual(valuation.unavailableReasons, ['missing valuation reference']);
});

test('groupCautionFlags preserves all flags for drilldown', () => {
  const groups = groupCautionFlags([
    { key: 'old_period_selected', group: 'timing', severity: 'info' },
    { key: 'low_conviction', group: 'conviction', severity: 'warning' },
    { key: 'low_signal_quality', group: 'signal_quality', severity: 'warning' },
  ]);

  assert.deepEqual(groups.map((group) => group.group), ['signal_quality', 'conviction', 'timing']);
  assert.deepEqual(groups.map((group) => group.flags.length), [1, 1, 1]);
});

test('suggestedResearchSteps adapts to missing data', () => {
  const steps = suggestedResearchSteps({
    quality: {
      hasValueLineQuality: false,
      unavailableReasons: ['missing Value Line facts'],
    },
    valuation: {
      unavailableReasons: ['missing valuation reference'],
    },
  });

  assert.deepEqual(steps.slice(0, 2), [
    'Locate or upload the latest Value Line report for this company.',
    'Add or verify a valuation reference before interpreting discount-to-reference.',
  ]);
});

test('missingDataReasons dedupes overlapping quality and valuation reasons', () => {
  const reasons = missingDataReasons({
    quality: {
      unavailableReasons: ['missing price', 'missing Value Line facts'],
    },
    valuation: {
      unavailableReasons: ['missing price', 'missing valuation reference'],
    },
  });

  assert.deepEqual(reasons, [
    { key: 'quality:missing price', label: 'missing price' },
    { key: 'quality:missing Value Line facts', label: 'missing Value Line facts' },
    { key: 'valuation:missing valuation reference', label: 'missing valuation reference' },
  ]);
});

test('normalizeQualityOverlay exposes missing data as explicit product state', () => {
  const quality = normalizeQualityOverlay({
    coverage: {
      value_line: false,
      price: false,
      owner_earnings: false,
      available_metrics: 0,
      expected_metrics: 6,
    },
    unavailable_reasons: ['missing Value Line facts', 'missing price'],
  });

  assert.equal(quality.piotroskiLabel, '—');
  assert.equal(quality.latestPriceLabel, '—');
  assert.equal(quality.qualityCoverageLabel, '0/6 facts');
  assert.equal(quality.hasValueLineQuality, false);
  assert.equal(quality.primarySourceDocumentId, null);
  assert.deepEqual(quality.sourceDocumentIds, []);
  assert.deepEqual(quality.provenanceFacts, []);
  assert.deepEqual(quality.unavailableReasons, ['missing Value Line facts', 'missing price']);
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
