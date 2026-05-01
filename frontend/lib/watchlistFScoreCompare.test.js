/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  normalizeFScoreComparePayload,
  scoreTone,
} = require('./watchlistFScoreCompare');

test('normalizeFScoreComparePayload aligns score cells to the payload years', () => {
  const model = normalizeFScoreComparePayload({
    watchlist: { id: 7, name: 'Quality' },
    years: [2022, 2023, 2024, 2025],
    rows: [
      {
        stock_id: 10,
        ticker: 'ASML',
        exchange: 'NASDAQ',
        company_name: 'ASML Holding',
        scores: [
          {
            fiscal_year: 2022,
            score: 7,
            display_score: '7',
            fact_nature: 'actual',
            status: 'calculated',
          },
          {
            fiscal_year: 2025,
            score: 6,
            display_score: '6',
            fact_nature: 'estimate',
            status: 'calculated',
          },
        ],
      },
    ],
  });

  assert.deepEqual(model.years, [2022, 2023, 2024, 2025]);
  assert.equal(model.rows[0].ticker, 'ASML');
  assert.deepEqual(
    model.rows[0].scores.map((cell) => [
      cell.fiscalYear,
      cell.displayScore,
      cell.factNature,
      cell.tone,
    ]),
    [
      [2022, '7', 'actual', 'strong'],
      [2023, '—', null, 'missing'],
      [2024, '—', null, 'missing'],
      [2025, '6', 'estimate', 'mixed'],
    ]
  );
});

test('scoreTone buckets F-Score totals for comparison scanning', () => {
  assert.equal(scoreTone(8), 'strong');
  assert.equal(scoreTone(4), 'mixed');
  assert.equal(scoreTone(3), 'weak');
  assert.equal(scoreTone(null), 'missing');
});
