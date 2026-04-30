/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildAppToastPayload,
  normalizeAppToastType,
  showAppToast,
} = require('./appToast');

test('normalizeAppToastType accepts known semantic toast types', () => {
  assert.equal(normalizeAppToastType('success'), 'success');
  assert.equal(normalizeAppToastType('error'), 'error');
  assert.equal(normalizeAppToastType('warning'), 'warning');
  assert.equal(normalizeAppToastType('info'), 'info');
});

test('normalizeAppToastType falls back to info for unknown values', () => {
  assert.equal(normalizeAppToastType('destructive'), 'info');
  assert.equal(normalizeAppToastType(null), 'info');
  assert.equal(normalizeAppToastType(undefined), 'info');
});

test('buildAppToastPayload maps app type to toast metadata', () => {
  assert.deepEqual(
    buildAppToastPayload({
      type: 'success',
      title: 'Saved',
      description: 'Changes were saved.',
    }),
    {
      appType: 'success',
      title: 'Saved',
      description: 'Changes were saved.',
      variant: 'default',
    }
  );

  assert.deepEqual(
    buildAppToastPayload({
      type: 'error',
      title: 'Failed',
      description: 'Unable to save.',
    }),
    {
      appType: 'error',
      title: 'Failed',
      description: 'Unable to save.',
      variant: 'destructive',
    }
  );
});

test('showAppToast calls the provided toast function with standardized payload', () => {
  const calls = [];
  const result = showAppToast((payload) => {
    calls.push(payload);
    return { id: '1' };
  }, {
    type: 'warning',
    title: 'Partial update',
  });

  assert.deepEqual(result, { id: '1' });
  assert.deepEqual(calls, [
    {
      appType: 'warning',
      title: 'Partial update',
      description: undefined,
      variant: 'default',
    },
  ]);
});
