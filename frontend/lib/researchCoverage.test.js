/* eslint-disable @typescript-eslint/no-require-imports */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '..');

test('admin coverage queue exposes explainable states and permitted actions', () => {
  const pagePath = path.join(root, 'app', '(dashboard)', 'admin', 'coverage', 'page.tsx');
  assert.equal(fs.existsSync(pagePath), true, 'admin coverage page must exist');
  const source = fs.readFileSync(pagePath, 'utf8');

  assert.match(source, /\/coverage\/admin\/requirements/);
  assert.match(source, /\/coverage\/admin\/evaluate-all/);
  assert.match(source, /matched_rule/);
  assert.match(source, /freshness_policy_version/);
  assert.match(source, /next_action/);
  assert.match(source, /Blocked is not covered/);
  assert.match(source, /Empty coverage queue/);
  assert.match(source, /Unable to load coverage queue/);
});

test('admin navigation includes the coverage operations route', () => {
  const shell = fs.readFileSync(
    path.join(root, 'components', 'layout', 'AppShell.tsx'),
    'utf8',
  );
  assert.match(shell, /Coverage Admin/);
  assert.match(shell, /\/admin\/coverage/);
});
