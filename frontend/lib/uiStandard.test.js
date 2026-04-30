/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '..');
const scanRoots = ['app', 'components', 'features'].map((dir) => path.join(repoRoot, dir));
const ignoredSegments = `${path.sep}components${path.sep}ui${path.sep}`;
const primitivePattern = /<(input|select|textarea|button|details|summary|table|thead|tbody|tr|th|td)\b/;

function collectTsxFiles(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  return entries.flatMap((entry) => {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      return collectTsxFiles(fullPath);
    }
    return entry.isFile() && entry.name.endsWith('.tsx') ? [fullPath] : [];
  });
}

test('product frontend code uses shared shadcn/ui controls instead of raw primitives', () => {
  const violations = scanRoots
    .flatMap(collectTsxFiles)
    .filter((filePath) => !filePath.includes(ignoredSegments))
    .filter((filePath) => primitivePattern.test(fs.readFileSync(filePath, 'utf8')))
    .map((filePath) => path.relative(repoRoot, filePath));

  assert.deepEqual(violations, []);
});
