/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { getDocumentProcessingResult, getCalculationWarnings } = require('./documentProcessing');

const blocked = {
  calculation: 'piotroski_f_score', status: 'unavailable',
  reason_code: 'unresolved_source_reconciliation',
  blocking_reasons: ['period_identity_unavailable'],
};

test('parsed source with a blocked optional calculation is a warning, not failed or fully available', () => {
  const result = getDocumentProcessingResult({status: 'parsed', page_reports: [
    {status: 'parsed', calculation_outcomes: [blocked]},
  ]});
  assert.equal(result.tone, 'warning');
  assert.match(result.title, /Source facts parsed/);
  assert.equal(result.warnings.length, 1);
  assert.match(result.warnings[0], /Piotroski F-Score.*unavailable.*source reconciliation/i);
  assert.doesNotMatch(result.description, /available in the screener/i);
});

test('HTTP success cannot turn a failed, partial or unsupported parse into full success', () => {
  assert.equal(getDocumentProcessingResult({status: 'failed'}).tone, 'danger');
  assert.equal(getDocumentProcessingResult({status: 'parsed_partial'}).tone, 'warning');
  assert.equal(getDocumentProcessingResult({status: 'requires_ocr'}).tone, 'warning');
  assert.equal(getDocumentProcessingResult({}).tone, 'warning');
  assert.equal(getDocumentProcessingResult({status: 'parsed'}).tone, 'success');
});

test('persisted document and reparse outcomes retain the warning without rendering arbitrary content', () => {
  assert.deepEqual(getCalculationWarnings({calculation_outcomes: [blocked, blocked]}),
    getCalculationWarnings({page_reports: [{calculation_outcomes: [blocked]}]}));
  const result = getCalculationWarnings({calculation_outcomes: [
    {...blocked, calculation: '<script>unsafe</script>'},
    {...blocked, status: 'available'},
    {...blocked, reason_code: 'unrelated_error'},
  ]});
  assert.deepEqual(result, []);
});

test('upload and document list wire the outcome disclosure into their rendered paths', () => {
  const upload = fs.readFileSync(path.join(__dirname, '../features/upload/components/UploadZone.tsx'), 'utf8');
  const documents = fs.readFileSync(path.join(__dirname, '../app/(dashboard)/documents/page.tsx'), 'utf8');
  assert.match(upload, /getDocumentProcessingResult/);
  assert.match(upload, /\.warnings\.map/);
  assert.doesNotMatch(upload, /Upload successful!/);
  assert.match(upload, /Document ID: \{uploadMutation\.data\.document_id\}/);
  assert.match(documents, /getCalculationWarnings\(doc\)/);
  assert.match(documents, /getDocumentProcessingResult\(data\)/);
  const shell = fs.readFileSync(path.join(__dirname, '../components/layout/AppShell.tsx'), 'utf8');
  assert.doesNotMatch(shell, /Parsed reports feed the screener instantly/);
  assert.match(shell, /Availability depends on evidence and source checks/);
});
