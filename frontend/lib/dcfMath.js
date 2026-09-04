const DCF_MODEL_BOUNDS = Object.freeze({
  maxYears: 1000,
  maxRatePct: 1000,
  maxAbsPerShare: 1_000_000,
  maxResultPerShare: 1_000_000_000_000,
});

const inModelBounds = (base, rate, years) => {
  return (
    Number.isFinite(base) &&
    base >= 0 &&
    base <= DCF_MODEL_BOUNDS.maxAbsPerShare &&
    Number.isFinite(rate) &&
    rate >= 0 &&
    rate <= DCF_MODEL_BOUNDS.maxRatePct &&
    Number.isFinite(years) &&
    years >= 0 &&
    years <= DCF_MODEL_BOUNDS.maxYears
  );
};

const computeGrowthValue = (baseValue, discountRatePct, years, growthRatePct) => {
  const base = Number(baseValue);
  const discountPct = Number(discountRatePct);
  const growthPct = Number(growthRatePct);
  const rawYears = Number(years);
  if (
    !inModelBounds(base, discountPct, rawYears) ||
    !inModelBounds(base, growthPct, rawYears)
  ) {
    return Number.NaN;
  }
  const r = discountPct / 100;
  const g = growthPct / 100;
  const n = Math.floor(rawYears);
  if (n === 0) {
    return 0;
  }

  const ratio = (1 + g) / (1 + r);
  let discountedValue = base;
  let total = 0;
  for (let year = 0; year < n; year += 1) {
    discountedValue *= ratio;
    total += discountedValue;
    if (!Number.isFinite(discountedValue) || !Number.isFinite(total)) {
      return Number.NaN;
    }
  }
  return total;
};

const computeTerminalValue = (
  baseValue,
  discountRatePct,
  growthYears,
  growthRatePct,
  terminalYears,
  terminalRatePct
) => {
  const base = Number(baseValue);
  const discountPct = Number(discountRatePct);
  const growthPct = Number(growthRatePct);
  const terminalPct = Number(terminalRatePct);
  const rawGrowthYears = Number(growthYears);
  const rawTerminalYears = Number(terminalYears);
  if (
    !inModelBounds(base, discountPct, rawGrowthYears) ||
    !inModelBounds(base, growthPct, rawGrowthYears) ||
    !inModelBounds(base, terminalPct, rawTerminalYears) ||
    rawTerminalYears > DCF_MODEL_BOUNDS.maxYears ||
    discountPct <= terminalPct
  ) {
    return Number.NaN;
  }
  const r = discountPct / 100;
  const g1 = growthPct / 100;
  const g2 = terminalPct / 100;
  const n1 = Math.floor(rawGrowthYears);
  const n2 = Math.floor(rawTerminalYears);

  if (n2 === 0) {
    return 0;
  }

  let discountedValue = base;
  const growthRatio = (1 + g1) / (1 + r);
  for (let year = 0; year < n1; year += 1) {
    discountedValue *= growthRatio;
    if (!Number.isFinite(discountedValue)) {
      return Number.NaN;
    }
  }
  const terminalRatio = (1 + g2) / (1 + r);
  let total = 0;
  for (let year = 0; year < n2; year += 1) {
    discountedValue *= terminalRatio;
    total += discountedValue;
    if (!Number.isFinite(discountedValue) || !Number.isFinite(total)) {
      return Number.NaN;
    }
  }
  return total;
};

const computeTotalValue = (growthValue, terminalValue) => {
  const growth = Number(growthValue);
  const terminal = Number(terminalValue);
  if (!Number.isFinite(growth) || !Number.isFinite(terminal)) {
    return Number.NaN;
  }
  const total = growth + terminal;
  return total > 0 && total <= DCF_MODEL_BOUNDS.maxResultPerShare
    ? total
    : Number.NaN;
};

module.exports = {
  DCF_MODEL_BOUNDS,
  computeGrowthValue,
  computeTerminalValue,
  computeTotalValue,
};
