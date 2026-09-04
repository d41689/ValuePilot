/* eslint-disable @typescript-eslint/no-require-imports */
const { DCF_MODEL_BOUNDS } = require('./dcfMath');

const MODEL_VERSION = 'dcf_model_v1';
const COMPONENT_FIELDS = [
  'net_profit_per_share',
  'depreciation_per_share',
  'capital_spending_per_share',
  'based_on_per_share',
];
const INPUT_FIELDS = [
  ...COMPONENT_FIELDS,
  'discount_rate_pct',
  'growth_years',
  'growth_rate_pct',
  'terminal_years',
  'terminal_rate_pct',
];

const finiteString = (value) => {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? String(value) : null;
};

const buildDcfModelPayload = ({
  selection,
  inputManifest,
  inputManifestToken,
  canonicalInputs,
  actualInputs,
  growthRateSelection,
  clientResultPerShare,
}) => {
  if (
    (selection !== 'norm' && !Number.isInteger(selection)) ||
    !inputManifest ||
    typeof inputManifest !== 'object' ||
    typeof inputManifestToken !== 'string' ||
    !inputManifestToken ||
    !canonicalInputs ||
    typeof canonicalInputs !== 'object' ||
    !actualInputs ||
    typeof actualInputs !== 'object' ||
    (growthRateSelection !== null && typeof growthRateSelection !== 'string')
  ) {
    return null;
  }
  const normalizedInputs = {};
  for (const field of INPUT_FIELDS) {
    const value = finiteString(actualInputs[field]);
    if (value === null) {
      return null;
    }
    normalizedInputs[field] = value;
  }
  const canonical = {};
  for (const field of COMPONENT_FIELDS) {
    const value = finiteString(canonicalInputs[field]);
    if (value === null) {
      return null;
    }
    canonical[field] = value;
  }
  const clientResult = finiteString(clientResultPerShare);
  if (clientResult === null) {
    return null;
  }
  const nonnegativeFields = [
    'based_on_per_share',
    'discount_rate_pct',
    'growth_years',
    'growth_rate_pct',
    'terminal_years',
    'terminal_rate_pct',
  ];
  if (
    nonnegativeFields.some((field) => Number(normalizedInputs[field]) < 0) ||
    COMPONENT_FIELDS.some(
      (field) => Math.abs(Number(normalizedInputs[field])) > DCF_MODEL_BOUNDS.maxAbsPerShare
    ) ||
    Number(normalizedInputs.growth_years) > DCF_MODEL_BOUNDS.maxYears ||
    Number(normalizedInputs.terminal_years) > DCF_MODEL_BOUNDS.maxYears ||
    Number(normalizedInputs.discount_rate_pct) > DCF_MODEL_BOUNDS.maxRatePct ||
    Number(normalizedInputs.growth_rate_pct) > DCF_MODEL_BOUNDS.maxRatePct ||
    Number(normalizedInputs.terminal_rate_pct) > DCF_MODEL_BOUNDS.maxRatePct ||
    Number(normalizedInputs.discount_rate_pct) <=
      Number(normalizedInputs.terminal_rate_pct) ||
    Number(clientResult) <= 0 ||
    Number(clientResult) > DCF_MODEL_BOUNDS.maxResultPerShare
  ) {
    return null;
  }
  return {
    model_version: MODEL_VERSION,
    selection,
    input_manifest: inputManifest,
    input_manifest_token: inputManifestToken,
    actual_inputs: normalizedInputs,
    user_override_fields: COMPONENT_FIELDS.filter(
      (field) => Number(normalizedInputs[field]) !== Number(canonical[field])
    ),
    growth_rate_selection: growthRateSelection,
    client_result_per_share: clientResult,
  };
};

module.exports = { buildDcfModelPayload };
