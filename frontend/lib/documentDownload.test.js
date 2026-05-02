/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  canPickDownloadDirectory,
  getDownloadErrorMessage,
  getDocumentDownloadFilename,
  saveBlobToPickedDirectory,
} = require('./documentDownload');

test('getDocumentDownloadFilename preserves pdf names and removes invalid path characters', () => {
  assert.equal(getDocumentDownloadFilename('AOS report.pdf', 42), 'AOS report.pdf');
  assert.equal(getDocumentDownloadFilename('ACME/Q1: report', 42), 'ACME-Q1- report.pdf');
  assert.equal(getDocumentDownloadFilename('', 42), 'document-42.pdf');
});

test('canPickDownloadDirectory detects File System Access API support', () => {
  assert.equal(canPickDownloadDirectory({ showDirectoryPicker: async () => ({}) }), true);
  assert.equal(canPickDownloadDirectory({}), false);
  assert.equal(canPickDownloadDirectory(null), false);
});

test('saveBlobToPickedDirectory writes blob to the selected file', async () => {
  const calls = [];
  const writable = {
    async write(blob) {
      calls.push(['write', blob]);
    },
    async close() {
      calls.push(['close']);
    },
  };
  const win = {
    async showDirectoryPicker(options) {
      calls.push(['showDirectoryPicker', options]);
      return {
        async getFileHandle(fileName, options) {
          calls.push(['getFileHandle', fileName, options]);
          return {
            async createWritable() {
              calls.push(['createWritable']);
              return writable;
            },
          };
        },
      };
    },
  };
  const blob = new Blob(['pdf']);

  await saveBlobToPickedDirectory(win, blob, 'report.pdf');

  assert.deepEqual(calls, [
    ['showDirectoryPicker', { mode: 'readwrite' }],
    ['getFileHandle', 'report.pdf', { create: true }],
    ['createWritable'],
    ['write', blob],
    ['close'],
  ]);
});

test('saveBlobToPickedDirectory fails clearly when folder picker is unavailable', async () => {
  await assert.rejects(
    () => saveBlobToPickedDirectory({}, new Blob(['pdf']), 'report.pdf'),
    /Folder selection is not supported/
  );
});

test('getDownloadErrorMessage parses JSON error blobs from download responses', async () => {
  const error = {
    message: 'Request failed with status code 404',
    response: {
      data: new Blob([JSON.stringify({ detail: 'Stored document file not found' })], {
        type: 'application/json',
      }),
    },
  };

  assert.equal(await getDownloadErrorMessage(error), 'Stored document file not found');
});

test('getDownloadErrorMessage falls back to axios message when no backend detail exists', async () => {
  const error = { message: 'Request failed with status code 404' };

  assert.equal(await getDownloadErrorMessage(error), 'Request failed with status code 404');
});
