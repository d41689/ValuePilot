/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const { canUploadDocuments, getDocumentsUploadNotice } = require('./documentsAccess');

test('canUploadDocuments allows admins only', () => {
  assert.equal(canUploadDocuments('admin'), true);
  assert.equal(canUploadDocuments('user'), false);
  assert.equal(canUploadDocuments(null), false);
});

test('getDocumentsUploadNotice returns notice for non-admin users only', () => {
  assert.equal(getDocumentsUploadNotice('admin'), null);
  assert.equal(
    getDocumentsUploadNotice('user'),
    'You are not an admin, so you cannot upload files from this workspace.'
  );
});
