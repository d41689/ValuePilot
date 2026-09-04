/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const managers = require('./thirteenfManagers');

test('value scope excludes growth, macro, activist, and passive noise by default', () => {
  const rows = managers.normalizeManagers([
    { id: 1, display_name: 'Berkshire', style_primary: 'value_concentrated' },
    { id: 2, display_name: 'Fundsmith', style_primary: 'quality_compounder' },
    { id: 3, display_name: 'Tiger', style_primary: 'growth_long_short' },
    { id: 4, display_name: 'Pershing', style_primary: 'activist' },
    { id: 5, display_name: 'Bridgewater', style_primary: 'multi_strategy_macro' },
  ]);

  assert.deepEqual(
    managers.filterManagers(rows, { scope: 'value' }).map((item) => item.id),
    [1, 2],
  );
  assert.deepEqual(
    managers.filterManagers(rows, { scope: 'value_plus_activist' }).map((item) => item.id),
    [1, 2, 4],
  );
  assert.equal(managers.filterManagers(rows, { scope: 'all' }).length, 5);
});

test('manager filters search curated ideology tags and style', () => {
  const rows = managers.normalizeManagers([
    {
      id: 1,
      display_name: 'Li Lu - Himalaya',
      style_primary: 'value_concentrated',
      ideology_tags: ['munger_endorsed', 'concentrated'],
    },
    { id: 2, display_name: 'Tweedy Browne', style_primary: 'value_deep' },
  ]);

  assert.deepEqual(
    managers.filterManagers(rows, { scope: 'value', search: 'munger' }).map((item) => item.id),
    [1],
  );
  assert.deepEqual(
    managers.filterManagers(rows, { scope: 'value', style: 'value_deep' }).map((item) => item.id),
    [2],
  );
});

test('position normalizer preserves computed weight and constituent-row evidence', () => {
  const result = managers.normalizeManagerHoldings({
    status: 'available',
    common_holdings: [
      {
        id: 9,
        position_rank: 1,
        stock: { id: 3, ticker: 'GOOG', company_name: 'Alphabet' },
        value_usd: 200000,
        ssh_prnamt: 1000,
        portfolio_weight_pct: { value: 12.345678, unavailable_reason: null },
        constituent_row_count: 2,
        cusips: ['02079K107', '02079K305'],
      },
    ],
  });

  assert.equal(result.commonHoldings[0].weightPct, 12.345678);
  assert.equal(result.commonHoldings[0].constituentRowCount, 2);
  assert.deepEqual(result.commonHoldings[0].cusips, ['02079K107', '02079K305']);
});

test('holdings normalizer preserves portfolio summary and explicitly dated local market context', () => {
  const result = managers.normalizeManagerHoldings({
    status: 'available',
    summary: { common_position_count: 1, reported_common_value_usd: 1000000 },
    quarter: '2026-Q1',
    quarter_end_date: '2026-03-31',
    common_holdings: [
      {
        id: 9,
        stock: { id: 3, ticker: 'AAPL', company_name: 'Apple' },
        implied_report_price: 100,
        market_context: {
          status: 'available',
          reason_code: null,
          latest_price: 120,
          latest_price_date: '2026-06-30',
          change_since_report_pct: 20,
          week_52_low: 70,
          week_52_high: 125,
          source: 'yfinance',
          currency: 'USD',
          freshness_state: 'fresh',
          source_authorization_state: 'authorized',
        },
      },
    ],
  });

  assert.equal(result.quarter, '2026-Q1');
  assert.equal(result.quarterEndDate, '2026-03-31');
  assert.equal(result.summary.commonPositionCount, 1);
  assert.equal(result.summary.reportedCommonValueUsd, 1000000);
  assert.equal(result.commonHoldings[0].impliedReportPrice, 100);
  assert.equal(result.commonHoldings[0].marketContext.latestPrice, 120);
  assert.equal(result.commonHoldings[0].marketContext.latestPriceDate, '2026-06-30');
  assert.equal(result.commonHoldings[0].marketContext.status, 'available');
  assert.equal(result.commonHoldings[0].marketContext.currency, 'USD');
  assert.equal(result.commonHoldings[0].marketContext.freshnessState, 'fresh');
  assert.equal(result.commonHoldings[0].marketContext.sourceAuthorizationState, 'authorized');
});

test('changes sort by absolute portfolio-weight move before value fallback', () => {
  const result = managers.normalizeManagerChanges({
    status: 'available',
    items: [
      {
        id: 1,
        stock: { ticker: 'AAA' },
        current_portfolio_weight_pct: 3,
        previous_portfolio_weight_pct: 2,
        value_delta_usd: 9000000,
      },
      {
        id: 2,
        stock: { ticker: 'BBB' },
        current_portfolio_weight_pct: 8,
        previous_portfolio_weight_pct: 2,
        value_delta_usd: 1,
      },
    ],
  });

  assert.deepEqual(result.items.map((item) => item.ticker), ['BBB', 'AAA']);
  assert.equal(result.items[0].weightDeltaPct, 6);
});

test('new and exited positions derive intuitive display deltas from one-sided evidence', () => {
  const result = managers.normalizeManagerChanges({
    status: 'available',
    items: [
      {
        id: 1,
        change_status: 'new_position',
        current_value_usd: 500,
        current_shares: 10,
      },
      {
        id: 2,
        change_status: 'exited_position',
        previous_value_usd: 700,
        previous_shares: 25,
      },
    ],
  });

  const byId = Object.fromEntries(result.items.map((item) => [item.id, item]));
  assert.equal(byId[1].valueDeltaUsd, 500);
  assert.equal(byId[1].shareDelta, 10);
  assert.equal(byId[2].valueDeltaUsd, -700);
  assert.equal(byId[2].shareDelta, -25);
});

test('manager history normalizer groups quarters and derives Dataroma-style portfolio impact', () => {
  const result = managers.normalizeManagerHistory({
    status: 'available',
    quarters: [
      {
        quarter: '2026-Q1',
        quarter_end_date: '2026-03-31',
        reported_common_value_usd: 400000,
        common_position_count: 2,
        concentration: { top_1_pct: 75, top_5_pct: 100, top_10_pct: 100 },
        top_holdings: [
          {
            id: 1,
            stock: { id: 1, ticker: 'AAA', company_name: 'Alpha' },
            portfolio_weight_pct: { value: 75 },
          },
        ],
      },
    ],
    activity: [
      {
        id: 4,
        report_quarter: '2026-Q1',
        stock: { id: 1, ticker: 'AAA', company_name: 'Alpha' },
        change_status: 'increased',
        current_shares: 200,
        share_delta: 100,
        share_change_pct: 1,
        current_portfolio_weight_pct: 30,
        is_primary_signal_eligible: true,
      },
      {
        id: 5,
        report_quarter: '2026-Q1',
        stock: { id: 2, ticker: 'EXIT', company_name: 'Exit' },
        change_status: 'exited_position',
        previous_shares: 50,
        share_delta: -50,
        previous_portfolio_weight_pct: 4,
        is_primary_signal_eligible: true,
      },
    ],
  });

  assert.equal(result.quarters[0].topHoldings[0].ticker, 'AAA');
  assert.equal(result.activity[0].reportQuarter, '2026-Q1');
  assert.equal(result.activity[0].portfolioImpactPct, 15);
  assert.equal(result.activity[1].portfolioImpactPct, 4);
  assert.deepEqual(
    managers.filterManagerActivity(result.activity, 'buys').map((item) => item.ticker),
    ['AAA'],
  );
  assert.deepEqual(
    managers.filterManagerActivity(result.activity, 'sells').map((item) => item.ticker),
    ['EXIT'],
  );
  assert.equal(managers.activityLabel(result.activity[0]), 'Add 100.00%');
  assert.equal(managers.activityLabel(result.activity[1]), 'Sell 100.00%');
});

test('manager activity sorting follows investor workflow: adds, buys, trims, exits', () => {
  const rows = [
    { id: 1, changeStatus: 'exited_position', shareChangePct: -1, portfolioImpactPct: 3 },
    { id: 2, changeStatus: 'increased', shareChangePct: 0.25, portfolioImpactPct: 2 },
    { id: 3, changeStatus: 'reduced', shareChangePct: -0.8, portfolioImpactPct: 1 },
    { id: 4, changeStatus: 'new_position', shareChangePct: null, portfolioImpactPct: 5 },
    { id: 5, changeStatus: 'increased', shareChangePct: 2, portfolioImpactPct: 1 },
    { id: 6, changeStatus: 'reduced', shareChangePct: -0.1, portfolioImpactPct: 4 },
  ];

  assert.deepEqual(
    managers.sortManagerActivity(rows, 'activity').map((item) => item.id),
    [5, 2, 4, 6, 3, 1],
  );
});

test('manager position history keeps quarter evidence and normalizes its activity row', () => {
  const result = managers.normalizeManagerPositionHistory({
    status: 'available',
    manager: { id: 8, display_name: 'Patient Manager' },
    stock: { id: 3, ticker: 'LONG', company_name: 'Long Co' },
    items: [
      {
        quarter: '2026-Q1',
        quarter_end_date: '2026-03-31',
        shares: 1500,
        portfolio_weight_pct: 15,
        implied_report_price: 100,
        reported_value_usd: 150000,
        activity: {
          id: 9,
          report_quarter: '2026-Q1',
          change_status: 'increased',
          current_shares: 1500,
          share_delta: 500,
          share_change_pct: 0.5,
          current_portfolio_weight_pct: 15,
        },
      },
    ],
  });

  assert.equal(result.manager.displayName, 'Patient Manager');
  assert.equal(result.stock.ticker, 'LONG');
  assert.equal(result.items[0].portfolioWeightPct, 15);
  assert.equal(result.items[0].activity.portfolioImpactPct, 5);
  assert.equal(managers.activityLabel(result.items[0].activity), 'Add 50.00%');
});

test('new-buy clusters keep excluded evidence but rank only scored value buyers', () => {
  const result = managers.normalizeNewBuyClusters({
    quarter: '2026-Q1',
    filing_window_open: true,
    coverage: { reported_manager_count: 18, tracked_manager_count: 24 },
    items: [
      {
        stock: { id: 7, ticker: 'GOOG', company_name: 'Alphabet' },
        cluster_size: 2,
        visible_buyer_count: 3,
        quality_weighted_cluster_score: 2,
        has_excluded_evidence: true,
        buyers: [
          {
            manager: { id: 1, display_name: 'Berkshire', style_primary: 'value_concentrated' },
            portfolio_weight_pct: 4.5,
            included_in_score: true,
          },
          {
            manager: { id: 2, display_name: 'Caveated', style_primary: 'value_deep' },
            included_in_score: false,
            score_exclusion_reasons: ['PENDING_AMENDMENT'],
          },
        ],
      },
    ],
  });

  assert.equal(result.quarter, '2026-Q1');
  assert.equal(result.filingWindowOpen, true);
  assert.equal(result.items[0].stock.ticker, 'GOOG');
  assert.equal(result.items[0].buyers[0].manager.displayName, 'Berkshire');
  assert.equal(result.items[0].buyers[1].includedInScore, false);
  assert.deepEqual(result.items[0].buyers[1].scoreExclusionReasons, ['PENDING_AMENDMENT']);
});

test('filing-season surface normalizes coverage and day-by-day manager reports', () => {
  const result = managers.normalizeFilingSeason({
    digest_date: '2026-05-17',
    season: {
      in_season: true,
      quarter: '2026-Q1',
      deadline_date: '2026-05-15',
      days_since_deadline: 2,
    },
    coverage: { reported_manager_count: 12, tracked_manager_count: 24 },
    digests: [
      {
        digest_date: '2026-05-17',
        items: [
          {
            manager: { id: 4, display_name: 'Patient Value', style_primary: 'value_deep' },
            holdings_count: 44,
            caveats: [{ code: 'CONFIDENTIAL_TREATMENT', message: 'Partial disclosure' }],
            top_new_positions: [
              {
                stock: { id: 8, ticker: 'NEW', company_name: 'New Co' },
                portfolio_weight_pct: 3.25,
                included_in_score: true,
              },
            ],
          },
        ],
      },
    ],
  });

  assert.equal(result.inSeason, true);
  assert.equal(result.coverage.reportedManagerCount, 12);
  assert.equal(result.digests[0].items[0].manager.displayName, 'Patient Value');
  assert.equal(result.digests[0].items[0].topNewPositions[0].stock.ticker, 'NEW');
});

test('investor-facing frontend never links directly to SEC', () => {
  const roots = ['app', 'components', 'features'];
  const directSecUrl = 'https://www.sec.gov';
  const offenders = [];
  const visit = (target) => {
    for (const entry of fs.readdirSync(target, { withFileTypes: true })) {
      const fullPath = path.join(target, entry.name);
      if (entry.isDirectory()) visit(fullPath);
      if (entry.isFile() && /\.(js|jsx|ts|tsx)$/.test(entry.name)) {
        if (fs.readFileSync(fullPath, 'utf8').includes(directSecUrl)) {
          offenders.push(path.relative(process.cwd(), fullPath));
        }
      }
    }
  };
  for (const root of roots) visit(path.join(process.cwd(), root));
  assert.deepEqual(offenders, []);
});
