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
  resolveAuthRedirect,
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

test('resolveAuthRedirect redirects unauthenticated and non-admin admin routes', () => {
  assert.equal(resolveAuthRedirect('/admin/13f', { token: null, role: null }), '/login');
  assert.equal(resolveAuthRedirect('/home', { token: null, role: undefined }), '/login');
  assert.equal(resolveAuthRedirect('/admin/13f', { token: 'token', role: 'user' }), '/home');
  assert.equal(resolveAuthRedirect('/admin/13f', { token: 'token', role: undefined }), '/home');
  assert.equal(resolveAuthRedirect('/admin/13f', { token: 'token', role: 'admin' }), null);
  assert.equal(resolveAuthRedirect('/login', { token: 'token', role: 'admin' }), '/home');
  assert.equal(resolveAuthRedirect('/login', { token: null, role: null }), null);
});
