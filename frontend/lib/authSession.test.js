/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const { clearAuthSession } = require('./authSession');

test('clearAuthSession removes ValuePilot auth tokens and expires auth cookies', () => {
  const removed = [];
  const storage = {
    removeItem(key) {
      removed.push(key);
    },
  };
  const cookieWrites = [];
  const cookieTarget = {};
  Object.defineProperty(cookieTarget, 'cookie', {
    get() {
      return cookieWrites.join('; ');
    },
    set(value) {
      cookieWrites.push(value);
    },
  });

  clearAuthSession(storage, cookieTarget);

  assert.deepEqual(removed, ['vp_access_token', 'vp_refresh_token']);
  assert.deepEqual(cookieWrites, [
    'vp_access_token=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT',
    'vp_access_token=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax',
    'vp_role=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT',
    'vp_role=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax',
  ]);
});
