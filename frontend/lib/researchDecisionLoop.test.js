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

test('home is an explainable Research Inbox and retains ticker search', () => {
  const page = source('app', '(dashboard)', 'home', 'page.tsx');
  assert.match(page, /Research Inbox/);
  assert.match(page, /TickerSearchBox/);
  assert.match(page, /\/research\/inbox\/regenerate/);
  assert.match(page, /\/research\/inbox/);
  assert.match(page, /matched_rule/);
  assert.match(page, /reason/);
  assert.match(page, /Snooze 7 days/);
  assert.match(page, /Dismiss/);
  assert.match(page, /No open research actions/);
  assert.match(page, /Unable to load your Research Inbox/);
});

test('Research Cases list exposes lifecycle, overdue state, and stable API filters', () => {
  const page = source('app', '(dashboard)', 'research', 'cases', 'page.tsx');
  assert.match(page, /\/research\/cases/);
  assert.match(page, /head_revision_number/);
  assert.match(page, /next_review_on/);
  assert.match(page, /Overdue/);
  assert.match(page, /All lifecycle states/);
  assert.match(page, /No research cases match/);
});

test('case workspace separates current evidence from recorded revisions and supports explicit save', () => {
  const page = source('app', '(dashboard)', 'research', 'cases', '[id]', 'page.tsx');
  assert.match(page, /\/workspace/);
  assert.match(page, /\/revisions/);
  assert.match(page, /expected_head_revision_number/);
  assert.match(page, /decision_action/);
  assert.match(page, /Record review decision/);
  assert.match(page, /Record decision/);
  assert.match(page, /Independent thesis/);
  assert.match(page, /Disconfirming view/);
  assert.match(page, /User intrinsic value/);
  assert.match(page, /System valuation reference/);
  assert.match(page, /13F is delayed/);
  assert.match(page, /Revision history/);
  assert.match(page, /beforeunload/);
  assert.match(page, /source_unavailable/);
  assert.match(page, /Last user value — under review/);
  assert.match(page, /Piotroski quality history/);
  assert.match(page, /Review original evidence/);
  assert.match(page, /Latest reported changes/);
  assert.match(page, /holding streak/);
});

test('discovery surfaces use one canonical create-or-open case control', () => {
  const button = source('components', 'research', 'OpenResearchCaseButton.tsx');
  assert.match(button, /\/research\/cases/);
  assert.match(button, /origin_type/);
  assert.match(button, /source_version/);

  const watchlist = source('app', '(dashboard)', 'watchlist', 'page.tsx');
  const lens = source('app', '(dashboard)', '13f', 'oracles-lens', 'page.tsx');
  const inbox = source('app', '(dashboard)', 'home', 'page.tsx');
  const screener = source('app', '(dashboard)', 'screener', 'page.tsx');
  const stockSummary = source('app', '(dashboard)', 'stocks', '[ticker]', 'summary', 'page.tsx');
  const managerHolding = source('components', 'thirteenf', 'ManagerResearchWorkbench.tsx');
  assert.match(watchlist, /OpenResearchCaseButton/);
  assert.match(lens, /OpenResearchCaseButton/);
  assert.match(inbox, /OpenResearchCaseButton/);
  assert.match(screener, /OpenResearchCaseButton/);
  assert.match(stockSummary, /OpenResearchCaseButton/);
  assert.match(managerHolding, /OpenResearchCaseButton/);
});

test('primary navigation names Research Inbox and Research Cases', () => {
  const shell = source('components', 'layout', 'AppShell.tsx');
  assert.match(shell, /Research Inbox/);
  assert.match(shell, /Research Cases/);
  assert.match(shell, /\/research\/cases/);
});

test('privacy settings exposes a deliberately confirmed account-erasure flow', () => {
  const page = source('app', '(dashboard)', 'settings', 'privacy', 'page.tsx');
  const shell = source('components', 'layout', 'AppShell.tsx');
  assert.match(shell, /Privacy & account/);
  assert.match(shell, /\/settings\/privacy/);
  assert.match(page, /ERASE MY ACCOUNT/);
  assert.match(page, /\/users\/me\/erase/);
  assert.match(page, /authSession\.clearAuthSession/);
  assert.match(page, /cannot be undone/i);
  assert.match(page, /shared financial lineage/i);
});
