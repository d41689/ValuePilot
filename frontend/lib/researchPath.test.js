/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { emptyResearchNotes, hasResearchNotes, appendResearchNotes } = require('./researchPath');
const { formatExactDecimal } = require('./financialHistory');

test('guide is blank by default; absence never becomes a proposed investment conclusion', () => {
  assert.equal(hasResearchNotes(undefined), false);
  assert.equal(hasResearchNotes(emptyResearchNotes()), false);
  assert.equal(hasResearchNotes({ observation: '  \n' }), false);
  assert.equal(appendResearchNotes('Existing thesis', emptyResearchNotes()), 'Existing thesis');
});

test('explicit append preserves old thesis byte-for-byte and all five user-written answers', () => {
  const before = '  Old thesis\n\nDo not rewrite.  ';
  const notes = { observation: 'Cash fell, profit rose.', explanations: 'Possibly timing; unverified.',
    evidenceNeeded: 'Compare working-capital notes.\nCheck taxes.', falsification: 'If timing does not reverse.',
    judgment: 'Cannot judge yet.' };
  const result = appendResearchNotes(before, notes);
  assert.ok(result.startsWith(before + '\n\n'));
  for (const answer of Object.values(notes)) assert.ok(result.includes(answer));
  assert.ok(result.indexOf('1. Observation') < result.indexOf('5. Current judgment'));
  assert.equal(before, '  Old thesis\n\nDo not rewrite.  ');
  assert.equal(notes.observation, 'Cash fell, profit rose.');
});

test('partial notes mark unanswered steps without inventing text and local JSON round trips', () => {
  const notes = { ...emptyResearchNotes(), judgment: '尚不能判断' };
  assert.equal(hasResearchNotes(notes), true);
  assert.match(appendResearchNotes('', notes), /Not recorded/);
  assert.match(appendResearchNotes('', JSON.parse(JSON.stringify(notes))), /尚不能判断/);
  assert.equal(appendResearchNotes('Legacy [Research notes] text', undefined), 'Legacy [Research notes] text');
});

test('readable exact decimals group without Number conversion or loss of significant precision', () => {
  assert.equal(formatExactDecimal('111482000000.000000000000'), '111,482,000,000');
  assert.equal(formatExactDecimal('9007199254740993.000000000001'), '9,007,199,254,740,993.000000000001');
  assert.equal(formatExactDecimal('-0.000001000000'), '-0.000001');
  assert.equal(formatExactDecimal('0.000000'), '0');
  assert.equal(formatExactDecimal(null), 'Not available');
  assert.equal(formatExactDecimal('1e12'), '1e12');
});

test('workspace leads with financial reading and guards explicit saves against unappended notes', () => {
  const page = fs.readFileSync(path.join(__dirname, '../app/(dashboard)/research/cases/[id]/page.tsx'), 'utf8');
  assert.ok(page.indexOf('<AnnualFinancialsTable') < page.indexOf('Canonical EOD price'));
  assert.ok(page.indexOf('<AnnualFinancialsTable') < page.indexOf('<ResearchPath'));
  assert.match(page, /hasResearchNotes\(draft\.researchNotes\)/);
  assert.match(page, /appendResearchNotes\(draft\.thesis, draft\.researchNotes\)/);
  assert.match(page, /if \(hasResearchNotes\(draft\.researchNotes\)\) throw/);
  assert.match(page, /<ResearchPath[^>]*readOnly=\{terminal \|\| saveMutation\.isPending\}/);
  assert.doesNotMatch(page, /research_notes:/);
});
