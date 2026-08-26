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

test('development and production Next artifacts use isolated directories', () => {
  const nextConfig = source('next.config.js');

  assert.match(nextConfig, /NODE_ENV === 'development'/);
  assert.match(nextConfig, /distDir:\s*isDev\s*\?\s*'\.next-dev'\s*:\s*'\.next'/);
});
