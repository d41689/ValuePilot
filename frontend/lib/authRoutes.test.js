/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const { AUTH_PUBLIC_PATHS, isPublicAuthPath } = require('./authRoutes');

test('AUTH_PUBLIC_PATHS includes login and register', () => {
  assert.deepEqual(AUTH_PUBLIC_PATHS, ['/login', '/register']);
});

test('isPublicAuthPath returns true for auth public routes only', () => {
  assert.equal(isPublicAuthPath('/login'), true);
  assert.equal(isPublicAuthPath('/register'), true);
  assert.equal(isPublicAuthPath('/home'), false);
  assert.equal(isPublicAuthPath('/register/extra'), false);
});
