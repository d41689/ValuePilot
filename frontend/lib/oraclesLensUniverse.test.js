/* eslint-disable @typescript-eslint/no-require-imports */
// Universe-selector helpers for Oracle's Lens.
// Task doc: docs/tasks/2026-05-24_oracles-lens-universe-selector.md
const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildOracleLensQueryParams,
  DEFAULT_PRESET_KEY,
  matchPreset,
  parseUniverseFromSearchParams,
  presetByKey,
  UNIVERSE_PRESETS,
  urlHasUniverseFilter,
} = require('./oraclesLens');


test('UNIVERSE_PRESETS includes the five planned chips plus Custom is dialog-only', () => {
  const keys = UNIVERSE_PRESETS.map((preset) => preset.key);
  assert.deepStrictEqual(keys, [
    'deep_value',
    'activists',
    'small_cap_sleuths',
    'permanent_capital',
    'all',
  ]);
});


test('DEFAULT_PRESET_KEY is Deep Value (the PO-confirmed default)', () => {
  assert.strictEqual(DEFAULT_PRESET_KEY, 'deep_value');
});


test('Deep Value preset is value_deep + value_concentrated + quality_compounder', () => {
  const preset = presetByKey('deep_value');
  assert.deepStrictEqual(preset.filters.stylePrimary, [
    'value_deep',
    'value_concentrated',
    'quality_compounder',
  ]);
});


test('All preset is empty filters (no manager subset)', () => {
  const preset = presetByKey('all');
  assert.deepStrictEqual(preset.filters, {});
});


test('Permanent Capital preset uses capital_structure dimension', () => {
  const preset = presetByKey('permanent_capital');
  assert.deepStrictEqual(preset.filters.capitalStructure, ['permanent_capital']);
});


test('Small-cap Sleuths preset uses market_cap_focus dimension', () => {
  const preset = presetByKey('small_cap_sleuths');
  assert.deepStrictEqual(preset.filters.marketCapFocus, ['small', 'micro']);
});


test('buildOracleLensQueryParams serializes the three new manager-universe filters', () => {
  const qs = buildOracleLensQueryParams({
    stylePrimary: ['value_deep', 'value_concentrated', 'quality_compounder'],
    capitalStructure: ['permanent_capital'],
    marketCapFocus: ['small'],
  });
  const params = new URLSearchParams(qs);
  assert.strictEqual(
    params.get('style_primary'),
    'value_deep,value_concentrated,quality_compounder',
  );
  assert.strictEqual(params.get('capital_structure'), 'permanent_capital');
  assert.strictEqual(params.get('market_cap_focus'), 'small');
});


test('buildOracleLensQueryParams omits empty universe filter arrays', () => {
  const qs = buildOracleLensQueryParams({
    stylePrimary: [],
    capitalStructure: [],
    marketCapFocus: [],
  });
  const params = new URLSearchParams(qs);
  assert.strictEqual(params.get('style_primary'), null);
  assert.strictEqual(params.get('capital_structure'), null);
  assert.strictEqual(params.get('market_cap_focus'), null);
});


test('parseUniverseFromSearchParams round-trips a Deep Value URL', () => {
  const params = new URLSearchParams(
    'style_primary=value_deep,value_concentrated,quality_compounder',
  );
  const universe = parseUniverseFromSearchParams(params);
  assert.deepStrictEqual(universe, {
    stylePrimary: ['value_deep', 'value_concentrated', 'quality_compounder'],
    capitalStructure: [],
    marketCapFocus: [],
  });
});


test('parseUniverseFromSearchParams tolerates whitespace + empty tokens', () => {
  const params = new URLSearchParams('style_primary=,value_deep, , value_concentrated,');
  const universe = parseUniverseFromSearchParams(params);
  assert.deepStrictEqual(universe.stylePrimary, ['value_deep', 'value_concentrated']);
});


test('matchPreset round-trips Deep Value selection back to its key', () => {
  const key = matchPreset({
    stylePrimary: ['value_deep', 'value_concentrated', 'quality_compounder'],
    capitalStructure: [],
    marketCapFocus: [],
  });
  assert.strictEqual(key, 'deep_value');
});


test('matchPreset ignores selection order (sort-then-compare)', () => {
  const key = matchPreset({
    stylePrimary: ['quality_compounder', 'value_concentrated', 'value_deep'],
    capitalStructure: [],
    marketCapFocus: [],
  });
  assert.strictEqual(key, 'deep_value');
});


test('matchPreset returns null for a Custom selection (no preset matches)', () => {
  const key = matchPreset({
    stylePrimary: ['value_deep', 'activist'],  // not any single preset
    capitalStructure: [],
    marketCapFocus: [],
  });
  assert.strictEqual(key, null);
});


test('matchPreset for empty selection returns the "all" preset', () => {
  const key = matchPreset({
    stylePrimary: [],
    capitalStructure: [],
    marketCapFocus: [],
  });
  assert.strictEqual(key, 'all');
});


test('urlHasUniverseFilter detects any one of the three filter params', () => {
  assert.strictEqual(
    urlHasUniverseFilter(new URLSearchParams('style_primary=value_deep')),
    true,
  );
  assert.strictEqual(
    urlHasUniverseFilter(new URLSearchParams('capital_structure=permanent_capital')),
    true,
  );
  assert.strictEqual(
    urlHasUniverseFilter(new URLSearchParams('market_cap_focus=small')),
    true,
  );
});


test('urlHasUniverseFilter returns false on a bare URL (triggers default-preset redirect)', () => {
  assert.strictEqual(urlHasUniverseFilter(new URLSearchParams('')), false);
  assert.strictEqual(
    urlHasUniverseFilter(new URLSearchParams('period=2025-Q4')),
    false,
  );
});
