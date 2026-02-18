const toNumber = (value, fallback = 0) => {
  if (value === null || value === undefined) {
    return fallback;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const safePow = (base, exponent) => {
  if (exponent === 0) {
    return 1;
  }
  if (base === 0) {
    return 0;
  }
  const logValue = Math.log(base);
  const power = exponent * logValue;
  if (power > 700) {
    return Number.POSITIVE_INFINITY;
  }
  if (power < -700) {
    return 0;
  }
  return Math.exp(power);
};

const computeGrowthValue = (baseValue, discountRatePct, years, growthRatePct) => {
  const base = toNumber(baseValue);
  const r = toNumber(discountRatePct) / 100;
  const g = toNumber(growthRatePct) / 100;
  const n = Math.max(0, Math.floor(toNumber(years)));
  if (n === 0) {
    return 0;
  }

  const ratio = (1 + g) / (1 + r);
  if (Math.abs(ratio - 1) < 1e-12) {
    return base * n;
  }
  const ratioPow = safePow(ratio, n);
  return base * (ratio * (1 - ratioPow)) / (1 - ratio);
};

const computeTerminalValue = (
  baseValue,
  discountRatePct,
  growthYears,
  growthRatePct,
  terminalYears,
  terminalRatePct
) => {
  const base = toNumber(baseValue);
  const r = toNumber(discountRatePct) / 100;
  const g1 = toNumber(growthRatePct) / 100;
  const g2 = toNumber(terminalRatePct) / 100;
  const n1 = Math.max(0, Math.floor(toNumber(growthYears)));
  const n2 = Math.max(0, Math.floor(toNumber(terminalYears)));

  if (n2 === 0) {
    return 0;
  }

  const baseAfterGrowth = base * safePow(1 + g1, n1);
  const ratio = (1 + g2) / (1 + r);

  if (Math.abs(ratio - 1) < 1e-12) {
    const discountFactor = safePow(1 + r, n1);
    return discountFactor === 0 ? Number.POSITIVE_INFINITY : (baseAfterGrowth * n2) / discountFactor;
  }

  const ratioPow = safePow(ratio, n2);
  const discountFactor = safePow(1 + r, n1);

  if (discountFactor === 0) {
    return Number.POSITIVE_INFINITY;
  }

  const pvMultiplier = (ratio * (1 - ratioPow)) / (1 - ratio);
  const pv = (baseAfterGrowth / discountFactor) * pvMultiplier;
  return pv;
};

const computeTotalValue = (growthValue, terminalValue) =>
  toNumber(growthValue) + toNumber(terminalValue);

module.exports = {
  computeGrowthValue,
  computeTerminalValue,
  computeTotalValue,
};
