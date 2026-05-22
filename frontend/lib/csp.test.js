/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const { buildContentSecurityPolicy } = require('./csp');

/** Parse a CSP string into { directiveName: valueString }. */
function parseCsp(policy) {
  const map = {};
  for (const part of policy.split(';')) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    const [name, ...rest] = trimmed.split(/\s+/);
    map[name] = rest.join(' ');
  }
  return map;
}

test('buildContentSecurityPolicy returns a non-empty policy string', () => {
  const policy = buildContentSecurityPolicy({ isDev: false });
  assert.equal(typeof policy, 'string');
  assert.ok(policy.length > 0);
});

test('production policy locks the non-script-source directives down', () => {
  const csp = parseCsp(buildContentSecurityPolicy({ isDev: false }));
  assert.equal(csp['default-src'], "'self'");
  assert.equal(csp['object-src'], "'none'");
  assert.equal(csp['base-uri'], "'self'");
  assert.equal(csp['form-action'], "'self'");
  assert.equal(csp['frame-ancestors'], "'self'");
  assert.equal(csp['font-src'], "'self'");
  assert.equal(csp['style-src'], "'self' 'unsafe-inline'");
  assert.equal(csp['img-src'], "'self' data: blob:");
});

test('production script-src allows inline but not eval', () => {
  const csp = parseCsp(buildContentSecurityPolicy({ isDev: false }));
  assert.ok(csp['script-src'].includes("'self'"));
  assert.ok(csp['script-src'].includes("'unsafe-inline'"));
  // 'unsafe-eval' is a dev-only allowance — React Refresh needs it, prod must not.
  assert.ok(!csp['script-src'].includes("'unsafe-eval'"));
});

test('production policy upgrades insecure requests and keeps connect-src same-origin', () => {
  const policy = buildContentSecurityPolicy({ isDev: false });
  const csp = parseCsp(policy);
  assert.ok('upgrade-insecure-requests' in csp);
  assert.equal(csp['connect-src'], "'self'");
});

test('development policy adds the HMR allowances and drops the prod-only upgrade', () => {
  const csp = parseCsp(buildContentSecurityPolicy({ isDev: true }));
  // React Refresh / HMR uses eval and a websocket in dev.
  assert.ok(csp['script-src'].includes("'unsafe-eval'"));
  assert.ok(csp['connect-src'].includes('ws:'));
  // upgrade-insecure-requests would break the plaintext-HTTP local dev server.
  assert.ok(!('upgrade-insecure-requests' in csp));
});

test('buildContentSecurityPolicy defaults to the production policy', () => {
  assert.equal(buildContentSecurityPolicy(), buildContentSecurityPolicy({ isDev: false }));
});
