/* eslint-disable @typescript-eslint/no-require-imports */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '..');

function source(...parts) {
  const file = path.join(root, ...parts);
  assert.equal(fs.existsSync(file), true, `${file} must exist`);
  return fs.readFileSync(file, 'utf8');
}

test('stock summary separates canonical current price from dated report reference', () => {
  const page = source('app', '(dashboard)', 'stocks', '[ticker]', 'summary', 'page.tsx');
  const card = source('components', 'StockSummaryCard.tsx');

  assert.match(page, /current_price/);
  assert.match(page, /report_price_reference/);
  assert.match(card, /Canonical EOD price/);
  assert.match(card, /Report price reference/);
  assert.match(card, /reason_code/);
  assert.doesNotMatch(card, />现价</);
});

test('DCF uses only eligible canonical value for margin of safety', () => {
  const page = source('app', '(dashboard)', 'stocks', '[ticker]', 'dcf', 'page.tsx');

  assert.match(page, /current_price/);
  assert.match(page, /currentPrice\.value/);
  assert.match(page, /Manual scenario price/);
  assert.match(page, /canonical current price remains unavailable/);
  assert.match(page, /resolveSafeMarginState/);
  assert.match(page, /valuationCurrencyState/);
  assert.match(page, /valuation_currency: valuationCurrencyState\.currency/);
  assert.match(page, /input_manifest: selectedBasedOnPayload\?\.input_manifest/);
  assert.match(page, /input_manifest_token: selectedBasedOnPayload\?\.input_manifest_token/);
  assert.match(page, /hasSelectedInputManifest/);
  assert.match(page, /valuationCurrencyState\.currency !== 'USD'/);
  assert.doesNotMatch(page, /currentPrice\.currency !== 'USD'/);
  assert.doesNotMatch(page, /`\$ \$\{formatMoney/);
  assert.doesNotMatch(page, /best-effort refresh; keep existing price/);
});

test('watchlist renders the full canonical contract and typed comparison blocker', () => {
  const page = source('app', '(dashboard)', 'watchlist', 'page.tsx');
  const contract = source('lib', 'currentPrice.ts');

  assert.match(page, /current_price/);
  assert.match(contract, /freshness_state/);
  assert.match(page, /reason_code/);
  assert.match(page, /expected_session_date/);
  assert.match(page, /source_authorization_state/);
  assert.match(page, /Margin unavailable/);
  assert.match(page, /delta_today_state/);
  assert.match(page, /formatIsoCurrencyAmount/);
});

test('research case uses the same canonical current-price wire contract', () => {
  const page = source('app', '(dashboard)', 'research', 'cases', '[id]', 'page.tsx');

  assert.match(page, /current_price/);
  assert.match(page, /current_price\.status !== 'available'/);
  assert.match(page, /current_price\.value/);
  assert.match(page, /source_authorization_state/);
  assert.match(page, /money\(workspace\.current_price\.value, workspace\.current_price\.currency\)/);
  assert.match(page, /formatIsoCurrencyAmount\(value, currency, 2\)/);
  assert.doesNotMatch(page, /money\(workspace\.current_price\.value\)/);
});
