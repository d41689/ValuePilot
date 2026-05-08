/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  AUTH_ADMIN_PREFIXES,
  AUTH_PROTECTED_PREFIXES,
  AUTH_PUBLIC_PATHS,
  isAdminAuthPath,
  isProtectedAuthPath,
  isPublicAuthPath,
} = require('./authRoutes');

test('AUTH_PUBLIC_PATHS includes login and register', () => {
  assert.deepEqual(AUTH_PUBLIC_PATHS, ['/login', '/register']);
});

test('isPublicAuthPath returns true for auth public routes only', () => {
  assert.equal(isPublicAuthPath('/login'), true);
  assert.equal(isPublicAuthPath('/register'), true);
  assert.equal(isPublicAuthPath('/home'), false);
  assert.equal(isPublicAuthPath('/register/extra'), false);
});

test('auth protected prefixes include the admin operations surface', () => {
  assert.equal(AUTH_PROTECTED_PREFIXES.includes('/admin'), true);
  assert.equal(AUTH_ADMIN_PREFIXES.includes('/admin'), true);
  assert.equal(isProtectedAuthPath('/admin/13f'), true);
  assert.equal(isAdminAuthPath('/admin/13f'), true);
  assert.equal(isProtectedAuthPath('/login'), false);
});
