/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const { ReadinessWarnings, warningText, warningKey } = require('./readinessWarnings');

// The bug this guards: the Oracle's Lens page rendered structured readiness
// warnings (`{ code, message }`) as if they were strings, so React threw
// "Objects are not valid as a React child" and the whole page unmounted. A
// normalizer-only test would stay green through that regression; this renders
// the actual boundary, so reverting to `{warning}` / `key={warning}` fails here.

const WARNINGS = [
  { code: 'CONFIDENTIAL_TREATMENT', message: 'Latest usable data includes confidential treatment caveats.' },
  { code: 'PARTIAL_COVERAGE', message: 'Latest usable data includes combination or partial coverage filings.' },
];

test('renders structured {code,message} warnings as text without throwing', () => {
  const html = renderToStaticMarkup(React.createElement(ReadinessWarnings, { warnings: WARNINGS }));

  // Both messages appear as text — the exact crash was a THROW here, so reaching
  // this assertion at all means the object-child regression did not reappear.
  assert.match(html, /confidential treatment caveats/);
  assert.match(html, /combination or partial coverage filings/);
  // And the object was never stringified into the output.
  assert.doesNotMatch(html, /\[object Object\]/);
});

test('rendering a raw object child would throw — proving the test can fail', () => {
  // Pin the failure mode itself: if the component ever renders the object
  // directly, renderToStaticMarkup throws exactly as the page did.
  assert.throws(
    () => renderToStaticMarkup(React.createElement('div', null, WARNINGS[0])),
    /Objects are not valid as a React child/,
  );
});

test('tolerates a legacy bare string', () => {
  const html = renderToStaticMarkup(
    React.createElement(ReadinessWarnings, { warnings: ['legacy warning text'] }),
  );
  assert.match(html, /legacy warning text/);
});

test('caps at the limit and never renders an empty/undefined input as a child', () => {
  assert.equal(
    renderToStaticMarkup(React.createElement(ReadinessWarnings, { warnings: undefined })),
    '<div class="space-y-1"></div>',
  );
  const html = renderToStaticMarkup(
    React.createElement(ReadinessWarnings, {
      warnings: WARNINGS.concat(WARNINGS),
      limit: 2,
    }),
  );
  // 2 of 4 rendered.
  assert.equal((html.match(/<div>/g) || []).length, 2);
});

test('keys are unique strings, not [object Object]', () => {
  const keys = WARNINGS.map((w, i) => warningKey(w, i));
  assert.deepEqual(keys, ['CONFIDENTIAL_TREATMENT', 'PARTIAL_COVERAGE']);
  assert.equal(new Set(keys).size, keys.length);
  // A codeless legacy entry falls back to its index rather than colliding.
  assert.equal(warningKey('bare', 0), 0);
  assert.equal(warningText({ code: 'X', message: 'm' }), 'm');
  assert.equal(warningText('bare'), 'bare');
});
