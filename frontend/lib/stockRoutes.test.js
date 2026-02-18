/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const { buildStockRoute, normalizeTicker } = require('./stockRoutes');

test('normalizeTicker trims and uppercases', () => {
  assert.equal(normalizeTicker('  axs  '), 'AXS');
  assert.equal(normalizeTicker('empa.to'), 'EMPA.TO');
});

test('buildStockRoute builds summary route', () => {
  assert.equal(buildStockRoute('axs', 'summary'), '/stocks/AXS/summary');
});

test('buildStockRoute builds dcf route', () => {
  assert.equal(buildStockRoute('axs', 'dcf'), '/stocks/AXS/dcf');
});
