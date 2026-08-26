/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(
  path.join(process.cwd(), 'components/layout/AppShell.tsx'),
  'utf8',
);

test('dashboard shell reserves the full viewport for content on small screens', () => {
  assert.match(source, /md:hidden/);
  assert.match(source, /hidden[^"']*md:flex/);
  assert.match(source, /p-4[^"']*md:p-6/);
});
