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

