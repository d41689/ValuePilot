/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  AUTH_SESSION_MAX_AGE_SECONDS,
  clearAuthSession,
  decodeJwtRole,
  persistAuthSession,
  shouldAttemptRefresh,
} = require('./authSession');

function makeJwt(payload) {
  const encode = (obj) => Buffer.from(JSON.stringify(obj)).toString('base64url');
  return `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode(payload)}.signature`;
}

function makeStorage() {
  const removed = [];
  const set = {};
  return {
    removed,
    set,
    removeItem(key) {
      removed.push(key);
    },
    setItem(key, value) {
      set[key] = value;
    },
  };
}

function makeCookieTarget() {
  const writes = [];
  const target = { writes };
  Object.defineProperty(target, 'cookie', {
    get() {
      return writes.join('; ');
    },
    set(value) {
      writes.push(value);
    },
  });
  return target;
}

test('clearAuthSession removes ValuePilot auth tokens and expires auth cookies', () => {
  const storage = makeStorage();
  const cookieTarget = makeCookieTarget();

  clearAuthSession(storage, cookieTarget);

  assert.deepEqual(storage.removed, ['vp_access_token', 'vp_refresh_token']);
  assert.deepEqual(cookieTarget.writes, [
    'vp_access_token=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax',
    'vp_role=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax',
  ]);
});

test('decodeJwtRole extracts the role claim from an access token', () => {
  assert.equal(decodeJwtRole(makeJwt({ sub: '1', role: 'admin' })), 'admin');
  assert.equal(decodeJwtRole(makeJwt({ sub: '2', role: 'user' })), 'user');
});

test('decodeJwtRole falls back to "user" for tokens without a role or for garbage', () => {
  assert.equal(decodeJwtRole(makeJwt({ sub: '3' })), 'user');
  assert.equal(decodeJwtRole('not-a-jwt'), 'user');
  assert.equal(decodeJwtRole(undefined), 'user');
});

test('persistAuthSession stores both tokens and stamps a one-week rolling cookie', () => {
  const storage = makeStorage();
  const cookieTarget = makeCookieTarget();
  const accessToken = makeJwt({ sub: '7', role: 'admin' });

  persistAuthSession(
    { accessToken, refreshToken: 'refresh-xyz' },
    storage,
    cookieTarget,
    false,
  );

  assert.equal(storage.set.vp_access_token, accessToken);
  assert.equal(storage.set.vp_refresh_token, 'refresh-xyz');

  assert.equal(AUTH_SESSION_MAX_AGE_SECONDS, 7 * 24 * 60 * 60);
  assert.deepEqual(cookieTarget.writes, [
    `vp_access_token=${accessToken}; path=/; max-age=604800; SameSite=Lax`,
    'vp_role=admin; path=/; max-age=604800; SameSite=Lax',
  ]);
});

test('persistAuthSession adds the Secure cookie flag in an HTTPS context', () => {
  const storage = makeStorage();
  const cookieTarget = makeCookieTarget();
  const accessToken = makeJwt({ sub: '8', role: 'user' });

  persistAuthSession(
    { accessToken, refreshToken: 'refresh-abc' },
    storage,
    cookieTarget,
    true,
  );

  assert.deepEqual(cookieTarget.writes, [
    `vp_access_token=${accessToken}; path=/; max-age=604800; SameSite=Lax; Secure`,
    'vp_role=user; path=/; max-age=604800; SameSite=Lax; Secure',
  ]);
});

test('shouldAttemptRefresh is true for a fresh 401 on a non-auth endpoint', () => {
  assert.equal(
    shouldAttemptRefresh({ response: { status: 401 }, config: { url: '/documents' } }),
    true,
  );
});

test('shouldAttemptRefresh is false once a request has already been retried', () => {
  assert.equal(
    shouldAttemptRefresh({
      response: { status: 401 },
      config: { url: '/documents', _retry: true },
    }),
    false,
  );
});

test('shouldAttemptRefresh is false for auth endpoints whose 401 is terminal', () => {
  for (const url of ['/auth/login', '/auth/register', '/auth/refresh']) {
    assert.equal(
      shouldAttemptRefresh({ response: { status: 401 }, config: { url } }),
      false,
      url,
    );
  }
});

test('shouldAttemptRefresh strips query strings but is not fooled by substring paths', () => {
  // A query string on a terminal auth endpoint is still terminal.
  assert.equal(
    shouldAttemptRefresh({
      response: { status: 401 },
      config: { url: '/auth/login?registered=1' },
    }),
    false,
  );
  // A baseURL-prefixed auth path is still matched as a trailing segment.
  assert.equal(
    shouldAttemptRefresh({
      response: { status: 401 },
      config: { url: '/api/v1/auth/refresh' },
    }),
    false,
  );
  // A path that only contains an auth route as a substring stays refreshable.
  assert.equal(
    shouldAttemptRefresh({
      response: { status: 401 },
      config: { url: '/auth/login-history' },
    }),
    true,
  );
});

test('shouldAttemptRefresh is false for non-401 errors and network failures', () => {
  assert.equal(
    shouldAttemptRefresh({ response: { status: 500 }, config: { url: '/documents' } }),
    false,
  );
  assert.equal(shouldAttemptRefresh({ config: { url: '/documents' } }), false);
  assert.equal(shouldAttemptRefresh(undefined), false);
});
