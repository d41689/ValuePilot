const formatValue = (input) => {
  const value = input?.value;
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '';
  }
  return value.toFixed(3);
};

const resolveDcfInputsPayload = (payload, selection) => {
  if (!payload || typeof payload !== 'object') {
    return null;
  }
  const current = payload.dcf_inputs ?? null;
  const series = Array.isArray(payload.dcf_inputs_series) ? payload.dcf_inputs_series : [];

  if (typeof selection === 'number') {
    const match = series.find((entry) => entry && entry.year === selection);
    if (match) {
      return match;
    }
  }
  return current;
};

const resolveDcfComponentInputs = (payload, selection) => {
  const inputs = resolveDcfInputsPayload(payload, selection) ?? {};

  if (inputs.currency_state?.status !== 'available' || !inputs.currency_state?.currency) {
    return {
      netProfitPerShare: '',
      depreciationPerShare: '',
      capexPerShare: '',
    };
  }

  const canonical = inputs.canonical_model_inputs;
  if (
    canonical &&
    typeof canonical.net_profit_per_share === 'string' &&
    typeof canonical.depreciation_per_share === 'string' &&
    typeof canonical.capital_spending_per_share === 'string'
  ) {
    return {
      netProfitPerShare: canonical.net_profit_per_share,
      depreciationPerShare: canonical.depreciation_per_share,
      capexPerShare: canonical.capital_spending_per_share,
    };
  }

  return {
    netProfitPerShare: formatValue(inputs.net_profit_per_share),
    depreciationPerShare: formatValue(inputs.depreciation_per_share),
    capexPerShare: formatValue(inputs.capital_spending_per_share),
  };
};

module.exports = {
  resolveDcfComponentInputs,
  resolveDcfInputsPayload,
};
