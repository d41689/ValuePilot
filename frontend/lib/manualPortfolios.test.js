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

test('portfolio list says manual, avoids broker claims, and exposes explicit creation', () => {
  const page = source('app', '(dashboard)', 'portfolios', 'page.tsx');
  assert.match(page, /\/portfolios/);
  assert.match(page, /Manual portfolios/);
  assert.match(page, /not broker-synchronized/i);
  assert.match(page, /No manual portfolios/);
});

test('portfolio workspace exposes events, case links, currency limitations, and versioned writes', () => {
  const page = source('app', '(dashboard)', 'portfolios', '[id]', 'page.tsx');
  assert.match(page, /expected_version/);
  assert.match(page, /price_currency_unavailable/);
  assert.match(page, /currency_mismatch/);
  assert.match(page, /cross-currency total/i);
  assert.match(page, /Decision journal/);
  assert.match(page, /Research case/);
  assert.match(page, /Review calendar/);
  assert.match(page, /Current evidence comparison/);
  assert.match(page, /overdue/);
  assert.match(page, /not an execution record/i);
});

test('primary navigation includes manual portfolios', () => {
  const shell = source('components', 'layout', 'AppShell.tsx');
  assert.match(shell, /Manual Portfolios/);
  assert.match(shell, /\/portfolios/);
});
