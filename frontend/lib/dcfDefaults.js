const isFiniteNumber = (value) => typeof value === 'number' && Number.isFinite(value);

const formatFixed3 = (value) => (isFiniteNumber(value) ? value.toFixed(3) : '');

const sanitizeOepsSeries = (series) => {
  if (!Array.isArray(series)) {
    return [];
  }
  return series
    .filter((item) => isFiniteNumber(item?.year) && isFiniteNumber(item?.value))
    .slice(0, 6);
};

const sanitizeGrowthRateOptions = (options) => {
  if (!Array.isArray(options)) {
    return [];
  }
  return options.filter(
    (item) =>
      typeof item?.key === 'string' &&
      typeof item?.label === 'string' &&
      isFiniteNumber(item?.value)
  );
};

const resolveDcfDefaults = (payload) => {
  const oepsNormalized = isFiniteNumber(payload?.oeps_normalized) ? payload.oeps_normalized : null;
  const oepsSeries = sanitizeOepsSeries(payload?.oeps_series);
  const growthRateOptions = sanitizeGrowthRateOptions(payload?.growth_rate_options);

  const lowestGrowthRate =
    growthRateOptions.length > 0
      ? growthRateOptions.reduce((min, current) => (current.value < min.value ? current : min))
      : null;

  if (oepsNormalized !== null) {
    return {
      oepsNormalized,
      oepsSeries,
      growthRateOptions,
      basedOnSelection: 'norm',
      basedOnOverride: formatFixed3(oepsNormalized),
      growthRateSelection: lowestGrowthRate?.key ?? null,
      growthRate: lowestGrowthRate?.value ?? null,
    };
  }

  const firstSeriesEntry = oepsSeries[0] ?? null;

  return {
    oepsNormalized,
    oepsSeries,
    growthRateOptions,
    basedOnSelection: firstSeriesEntry ? firstSeriesEntry.year : 'norm',
    basedOnOverride: formatFixed3(firstSeriesEntry?.value),
    growthRateSelection: lowestGrowthRate?.key ?? null,
    growthRate: lowestGrowthRate?.value ?? null,
  };
};

module.exports = {
  resolveDcfDefaults,
};
