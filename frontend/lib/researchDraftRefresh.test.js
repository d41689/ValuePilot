/* eslint-disable @typescript-eslint/no-require-imports */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { emptyResearchNotes, hasResearchNotes } = require('./researchPath');

// Execute the page's real effect/functions, with only browser/React boundaries
// replaced. In particular, do not duplicate the head-change decision in a helper.
const source = fs.readFileSync(path.join(__dirname, '../app/(dashboard)/research/cases/[id]/page.tsx'), 'utf8');
const tree = ts.createSourceFile('page.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const page = tree.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'ResearchCaseWorkspacePage');
const statements = page.body.statements;
function variable(name) {
  for (const statement of statements) {
    if (!ts.isVariableStatement(statement)) continue;
    const declaration = statement.declarationList.declarations.find(item => item.name.getText(tree) === name);
    if (declaration) return declaration;
  }
  throw new Error(`Missing page variable ${name}`);
}
function execute(code, context) {
  const compiled = ts.transpileModule(code, { compilerOptions: {
    target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS,
  } }).outputText;
  return vm.runInNewContext(compiled, context);
}
const initializers = ['listToText', 'textToList', 'initialDraft'].map(name =>
  tree.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === name).getText(tree)).join('\n');
const draftEffect = statements.find(node => ts.isExpressionStatement(node)
  && ts.isCallExpression(node.expression) && node.expression.expression.getText(tree) === 'useEffect'
  && node.getText(tree).includes('initialDraft(workspace)')).getText(tree);
const persistenceEffect = statements.find(node => ts.isExpressionStatement(node)
  && ts.isCallExpression(node.expression) && node.expression.expression.getText(tree) === 'useEffect'
  && node.getText(tree).includes('window.localStorage.setItem(storageKey')).getText(tree);
const updateDraft = statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'updateDraft').getText(tree);
const addEvidence = statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'addEvidence').getText(tree);
const mutationOptions = variable('saveMutation').initializer.arguments[0];
const mutationFn = mutationOptions.properties.find(node => node.name?.getText(tree) === 'mutationFn').initializer.getText(tree);
const mutationOnSuccess = mutationOptions.properties.find(node => node.name?.getText(tree) === 'onSuccess').initializer.getText(tree);
let discardHandler;
function findDiscardHandler(node) {
  if (ts.isJsxAttribute(node) && node.name.getText(tree) === 'onClick'
    && node.initializer?.getText(tree).includes('Discard this local draft')) {
    discardHandler = node.initializer.expression.getText(tree);
  }
  ts.forEachChild(node, findDiscardHandler);
}
findDiscardHandler(page);
assert.ok(discardHandler, 'The conflict recovery action must remain reachable');

function fixture({ serverHead = 3, loadedHead = 2, dirty = true, notes = true } = {}) {
  const draft = { thesis: 'Original thesis\nUser edits', researchNotes: {
    ...emptyResearchNotes(), observation: notes ? 'UNAPPENDED observation' : '',
  }, targetState: 'researching', assumptionsText: '', risksText: '', evidence: [], valuationMode: 'none' };
  const workspace = { case: { id: 2, head_revision_number: serverHead, state: 'researching' },
    as_of: '2026-09-10', revisions: [{ thesis: 'New server thesis' }] };
  const storage = new Map([['vp-research-draft:2:2', JSON.stringify(draft)]]);
  const result = { draft, dirty, loadedHead, conflict: false, requests: [] };
  const context = {
    workspace, loadedHead, draft, dirty, conflict: false, caseId: 2,
    emptyResearchNotes, hasResearchNotes, useEffect: callback => callback(),
    window: { localStorage: { getItem: key => storage.get(key), removeItem: key => storage.delete(key),
      setItem: (key, value) => storage.set(key, value) } },
    setDraft: value => { result.draft = typeof value === 'function' ? value(result.draft) : value; },
    setDirty: value => { result.dirty = value; },
    setConflict: value => { result.conflict = typeof value === 'function' ? value(result.conflict) : value; },
    setLoadedHead: value => { result.loadedHead = value; },
    saveMutation: { isPending: false },
    crypto: { randomUUID: () => 'test-correlation' },
    apiClient: { post: async (url, payload) => { result.requests.push({ url, payload }); return {}; } },
    queryClient: { invalidateQueries: async () => undefined },
    showAppToast: () => undefined, toast: {},
  };
  return { context, result, storage };
}

test('new server head preserves dirty notes, thesis, original head and signals conflict', () => {
  const { context, result } = fixture();
  const original = result.draft;
  execute(`${initializers}\n${draftEffect}`, context);
  assert.equal(result.draft, original);
  assert.equal(result.draft.researchNotes.observation, 'UNAPPENDED observation');
  assert.equal(result.dirty, true);
  assert.equal(result.loadedHead, 2);
  assert.equal(result.conflict, true);
});

test('new server head also preserves a dirty thesis without pending guided notes', () => {
  const { context, result } = fixture({ notes: false });
  const original = result.draft;
  execute(`${initializers}\n${draftEffect}`, context);
  assert.equal(result.draft, original);
  assert.equal(result.conflict, true);
});

test('clean drafts adopt the newer server head while same-head refresh leaves edits alone', () => {
  const clean = fixture({ dirty: false, notes: false });
  execute(`${initializers}\n${draftEffect}`, clean.context);
  assert.equal(clean.result.draft.thesis, 'New server thesis');
  assert.equal(clean.result.loadedHead, 3);
  assert.equal(clean.result.dirty, false);
  assert.equal(hasResearchNotes(clean.result.draft.researchNotes), false);
  const same = fixture({ serverHead: 2 });
  const original = same.result.draft;
  execute(`${initializers}\n${draftEffect}`, same.context);
  assert.equal(same.result.draft, original);
  assert.equal(same.result.dirty, true);
  assert.equal(same.result.conflict, false);
});

test('browser persistence remains addressed to the loaded draft head during a conflict', () => {
  const { context } = fixture();
  const key = execute(`(${variable('storageKey').initializer.getText(tree)})`, context);
  assert.equal(key, 'vp-research-draft:2:2');
  context.loadedHead = null;
  assert.equal(execute(`(${variable('storageKey').initializer.getText(tree)})`, context), 'vp-research-draft:2:3');
});

test('editing after a conflict keeps the warning for cached and refreshed server heads', () => {
  for (const serverHead of [2, 3]) {
    const { context, result } = fixture({ serverHead });
    context.conflict = true;
    result.conflict = true;
    execute(`${updateDraft}\nupdateDraft({ thesis: 'Further user edits' });`, context);
    assert.equal(result.draft.thesis, 'Further user edits');
    assert.equal(result.conflict, true);
  }
});

test('pending save rejects direct draft and evidence callbacks, then editing reopens unchanged', () => {
  const setup = fixture({ serverHead: 2, dirty: false, notes: false });
  const original = setup.result.draft;
  setup.context.saveMutation.isPending = true;
  execute(`${updateDraft}\nupdateDraft({ thesis: 'Blocked while saving' });`, setup.context);
  execute(`${updateDraft}\n${addEvidence}\naddEvidence({ source_type: 'test', label: 'Blocked', claim: 'Blocked' });`, setup.context);
  assert.equal(setup.result.draft, original);
  assert.equal(setup.result.dirty, false);

  setup.context.saveMutation.isPending = false;
  execute(`${updateDraft}\nupdateDraft({ thesis: 'Editable after error' });`, setup.context);
  assert.equal(setup.result.draft.thesis, 'Editable after error');
  assert.equal(setup.result.dirty, true);
});

test('save lifecycle cannot accept a later edit that success would erase', async () => {
  const setup = fixture({ serverHead: 2, notes: false });
  setup.context.storageKey = 'vp-research-draft:2:2';
  setup.context.draft.thesis = 'Submitted A';
  setup.result.draft.thesis = 'Submitted A';
  let finishPost;
  setup.context.apiClient.post = async (url, payload) => {
    setup.result.requests.push({ url, payload });
    await new Promise(resolve => { finishPost = resolve; });
    return {};
  };

  const save = execute(`${initializers}\n(${mutationFn})`, setup.context)('draft');
  assert.equal(setup.result.requests[0].payload.thesis, 'Submitted A');
  setup.context.saveMutation.isPending = true;
  execute(`${updateDraft}\nupdateDraft({ thesis: 'Edited B during save' });`, setup.context);
  assert.equal(setup.result.draft.thesis, 'Submitted A');

  setup.context.draft = setup.result.draft;
  execute(persistenceEffect, setup.context);
  assert.equal(JSON.parse(setup.storage.get(setup.context.storageKey)).thesis, 'Submitted A');

  finishPost();
  await save;
  await execute(`(${mutationOnSuccess})`, setup.context)();
  assert.equal(setup.storage.has(setup.context.storageKey), false);
  assert.equal(setup.result.dirty, false);
  assert.equal(setup.result.loadedHead, null);

  setup.context.workspace = { ...setup.context.workspace,
    case: { ...setup.context.workspace.case, head_revision_number: 3 },
    revisions: [{ thesis: 'Submitted A' }] };
  setup.context.loadedHead = setup.result.loadedHead;
  setup.context.dirty = setup.result.dirty;
  execute(`${initializers}\n${draftEffect}`, setup.context);
  assert.equal(setup.result.draft.thesis, 'Submitted A');
  assert.equal(setup.result.dirty, false);
  assert.equal(setup.result.loadedHead, 3);
});

test('every draft-mutating control is frozen while save is pending', () => {
  const controls = [];
  let lowerSave;
  function inspectControl(node) {
    const element = ts.isJsxElement(node) ? node.openingElement : ts.isJsxSelfClosingElement(node) ? node : null;
    if (element) {
      const tag = element.tagName.getText(tree);
      const attributes = element.attributes.properties;
      const handlers = attributes.filter(attribute =>
        ['onChange', 'onValueChange', 'onClick', 'onAdd', 'onAppend', 'onClear'].includes(attribute.name?.getText(tree)))
        .map(attribute => attribute.getText(tree)).join(' ');
      if (handlers.includes('updateDraft') || handlers.includes('addEvidence')) {
        const guard = attributes.find(attribute => ['disabled', 'readOnly'].includes(attribute.name?.getText(tree)));
        controls.push({ tag, guard: guard?.getText(tree) ?? '' });
      }
      if (tag === 'Button' && node.getText(tree).includes('Save research revision')) lowerSave = element;
    }
    ts.forEachChild(node, inspectControl);
  }
  inspectControl(page);
  assert.ok(controls.length >= 16, `Expected the complete draft control inventory, found ${controls.length}`);
  assert.deepEqual(controls.filter(control => !control.guard.includes('saveMutation.isPending')), []);
  assert.ok(lowerSave, 'The lower save action must remain reachable');
  const lowerDisabled = lowerSave.attributes.properties.find(attribute => attribute.name?.getText(tree) === 'disabled')?.getText(tree) ?? '';
  assert.match(lowerDisabled, /saveMutation\.isPending/);
  assert.match(lowerDisabled, /conflict/);
});

test('save rejects a newer server head or latched 409 conflict and sends the original expected head when aligned', async () => {
  const stale = fixture({ notes: false });
  const saveStale = execute(`${initializers}\n(${mutationFn})`, stale.context);
  await assert.rejects(saveStale('draft'));
  assert.equal(stale.result.requests.length, 0);
  const cachedConflict = fixture({ serverHead: 2, notes: false });
  cachedConflict.context.conflict = true;
  cachedConflict.result.conflict = true;
  await assert.rejects(execute(`${initializers}\n(${mutationFn})`, cachedConflict.context)('draft'));
  assert.equal(cachedConflict.result.requests.length, 0);
  const aligned = fixture({ serverHead: 2, notes: false });
  await execute(`${initializers}\n(${mutationFn})`, aligned.context)('draft');
  assert.equal(aligned.result.requests.length, 1);
  assert.equal(aligned.result.requests[0].payload.expected_head_revision_number, 2);
  assert.equal(aligned.result.requests[0].payload.thesis, aligned.context.draft.thesis);
});

function discardFixture({ confirmed = true, failed = false } = {}) {
  // A 409 need not update React Query's cached workspace: it may still be head 2.
  const setup = fixture({ serverHead: 2 });
  const { context, result } = setup;
  const events = [];
  result.conflict = true;
  context.conflict = true;
  context.storageKey = 'vp-research-draft:2:2';
  context.window.confirm = () => { events.push('confirm'); return confirmed; };
  context.workspaceQuery = { refetch: async () => {
    events.push('refetch');
    return failed ? { error: new Error('Server unavailable'), data: context.workspace }
      : { data: { ...context.workspace, case: { ...context.workspace.case, head_revision_number: 3 },
        revisions: [{ thesis: 'Latest fetched server thesis' }] } };
  } };
  return { ...setup, events, discard: execute(`${initializers}\n(${discardHandler})`, context) };
}

test('confirmed discard loads the fetched latest revision after a cached-head 409', async () => {
  const setup = discardFixture();
  await setup.discard();
  assert.deepEqual(setup.events, ['refetch', 'confirm']);
  assert.equal(setup.result.draft.thesis, 'Latest fetched server thesis');
  assert.equal(setup.result.loadedHead, 3);
  assert.equal(setup.result.dirty, false);
  assert.equal(setup.result.conflict, false);
  assert.equal(setup.storage.has('vp-research-draft:2:2'), false);
});

test('failed refresh preserves notes, browser storage and conflict even when cached data exists', async () => {
  const setup = discardFixture({ failed: true });
  const original = setup.result.draft;
  await setup.discard();
  assert.deepEqual(setup.events, ['refetch']);
  assert.equal(setup.result.draft, original);
  assert.equal(setup.result.loadedHead, 2);
  assert.equal(setup.result.dirty, true);
  assert.equal(setup.result.conflict, true);
  assert.equal(setup.storage.has('vp-research-draft:2:2'), true);
});

test('cancelling after the latest revision is fetched preserves the local draft', async () => {
  const setup = discardFixture({ confirmed: false });
  const original = setup.result.draft;
  await setup.discard();
  assert.deepEqual(setup.events, ['refetch', 'confirm']);
  assert.equal(setup.result.draft, original);
  assert.equal(setup.result.loadedHead, 2);
  assert.equal(setup.result.dirty, true);
  assert.equal(setup.result.conflict, true);
  assert.equal(setup.storage.has('vp-research-draft:2:2'), true);
});
