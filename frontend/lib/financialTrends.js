/* Read-only display comparisons; never a canonical financial-fact writer. */
/* eslint-disable @typescript-eslint/no-require-imports */
const { CORE_METRICS, annualCells } = require('./financialHistory');
const POLICY = 'annual-reading-v1';
const SEMANTICS = ['definition_family', 'definition_basis', 'definition_id', 'mapping_version', 'source_mapping_version', 'dimensions_identity'];
const CROSS_METRIC_SCOPE = ['definition_basis', 'mapping_version', 'source_mapping_version', 'dimensions_identity'];
const known = value => typeof value === 'string' && value.length > 0 && value !== 'unknown';
function decimal(value) {
  if (typeof value !== 'string' || value.length > 256 || !/^-?\d+(?:\.\d+)?$/.test(value)) return null;
  const [whole, fraction = ''] = value.split('.');
  return { n: BigInt(whole + fraction), scale: fraction.length };
}
function aligned(values) {
  const parsed = values.map(decimal);
  const scale = Math.max(...parsed.map(p => p.scale));
  return parsed.map(p => p.n * 10n ** BigInt(scale - p.scale));
}
function formatBillions(row) {
  const value = decimal(row.value_numeric_exact);
  const unitLabel = row.unit === 'currency' ? `billion ${row.currency || '· currency unknown'}`
    : row.unit === 'shares' ? 'billion shares' : (row.unit || 'unit unknown');
  if (!value) return { text: row.value_numeric_exact == null ? 'No numeric value' : 'Invalid numeric value', unitLabel };
  if (!['currency', 'shares'].includes(row.unit)) return { text: row.value_numeric_exact, unitLabel };
  const negative = value.n < 0n; const magnitude = negative ? -value.n : value.n;
  const divisor = 10n ** BigInt(value.scale + 7);
  const cents = (magnitude + divisor / 2n) / divisor;
  return { unitLabel, text: magnitude !== 0n && cents === 0n ? (negative ? '>-0.01' : '<0.01')
    : `${negative ? '-' : ''}${(cents / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${(cents % 100n).toString().padStart(2, '0')}` };
}
function dateDay(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const stamp = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(stamp) && new Date(stamp).toISOString().slice(0, 10) === value ? stamp / 86400000 : null;
}
function observationProblem(row) {
  if (!row) return 'missing_observation';
  if (!decimal(row.value_numeric_exact)) return 'no_valid_numeric_value';
  const id = row.comparison_identity;
  if (row.row_kind !== 'fact' || row.status !== 'available' || row.period_type !== 'FY'
    || row.fact_nature !== 'actual' || !Number.isInteger(row.fiscal_year)
    || row.fiscal_quarter != null || id?.identity_complete !== true
    || !known(id.source_identity) || SEMANTICS.some(key => !known(id[key]))
    || !known(row.source_type) || !known(row.source_role)
    || !['currency', 'shares'].includes(row.unit) || (row.unit === 'currency' && !known(row.currency))) return 'identity_unproven';
  const end = dateDay(row.period_end);
  if (end === null) return 'annual_period_unproven';
  if (row.period_basis === 'instant') return row.period_start == null ? null : 'annual_period_unproven';
  const start = dateDay(row.period_start);
  if (row.period_basis !== 'duration' || start === null || id.period_duration_kind !== 'fiscal_year'
    || ![364, 365, 366, 371].includes(id.duration_days) || end - start + 1 !== id.duration_days) return 'annual_period_unproven';
  return null;
}
function comparisonProblem(current, previous) {
  const problem = observationProblem(current) || observationProblem(previous);
  if (problem) return problem;
  // This projection has no authoritative split/share-class basis. Same key and
  // mapping cannot prove that reported share counts are comparable over time.
  if (current.unit === 'shares' || previous.unit === 'shares') return 'share_split_basis_unproven';
  if (current.fiscal_year !== previous.fiscal_year + 1) return 'nonadjacent_fiscal_years';
  if (['metric_key', 'unit', 'currency', 'source_type', 'source_role', 'fact_nature', 'period_basis']
    .some(key => current[key] !== previous[key]) || SEMANTICS.some(key => current.comparison_identity[key] !== previous.comparison_identity[key])) return 'incompatible_identity';
  const interval = dateDay(current.period_end) - dateDay(previous.period_end);
  if (![364, 365, 366, 371].includes(interval)
    || (current.period_basis === 'duration' && dateDay(current.period_start) !== dateDay(previous.period_end) + 1)) return 'noncontiguous_fiscal_periods';
  return null;
}
function compareAnnual(current, previous) {
  const factIds = [previous?.fact_id, current?.fact_id].filter(id => id != null);
  const reason = comparisonProblem(current, previous);
  if (reason) return { status: 'unavailable', reason, text: 'YoY unavailable', factIds, policy: POLICY, caveat: null, direction: null };
  const [now, before] = aligned([current.value_numeric_exact, previous.value_numeric_exact]);
  const a = previous.comparison_identity.duration_days; const b = current.comparison_identity.duration_days;
  const caveat = current.period_basis === 'duration' && a !== b ? `${a} → ${b} days; reported years, not annualized.` : null;
  if (before <= 0n || now < 0n) return { status: 'not_meaningful', reason: 'nonpositive_base_or_loss', text: 'N/M', factIds, policy: POLICY, caveat, direction: null };
  const difference = now - before; const absolute = difference < 0n ? -difference : difference;
  const tenths = (absolute * 1000n + before / 2n) / before;
  const sign = difference > 0n ? '+' : difference < 0n ? '-' : '';
  const text = difference !== 0n && tenths === 0n ? (difference > 0n ? '<+0.1%' : '>-0.1%')
    : `${sign}${tenths / 10n}.${tenths % 10n}%`;
  return { status: 'available', reason: null, text, factIds, policy: POLICY, caveat,
    direction: difference > 0n ? 'up' : difference < 0n ? 'down' : 'flat' };
}
function annualReading(history, metricKey) {
  const pivot = annualCells(history);
  const metric = CORE_METRICS.find(item => item.key === metricKey);
  const years = history.annual_window.status === 'determined' ? history.annual_window.years : [];
  const points = years.map(year => {
    const cell = pivot.cells[metricKey]?.[year] || { observations: [], states: [] };
    const cycles = pivot.cycleStates.filter(row => {
      const scope = row.scope;
      // Unknown scope cannot prove that this reading is unaffected.
      return !Array.isArray(scope?.metric_keys) || !Array.isArray(scope?.fiscal_years)
        || (scope.metric_keys.includes(metricKey) && scope.fiscal_years.includes(year));
    });
    const states = [...cell.states, ...(pivot.metricStates[metricKey] || []), ...cycles];
    const reason = states.length ? (states.every(s => s.reason_code === 'not_returned') ? 'not_returned' : 'blocked_or_conflicting')
      : cell.observations.length > 1 ? 'multiple_observations'
        : observationProblem(cell.observations[0]) || (cell.observations[0].period_basis !== metric.basis ? 'incompatible_period_basis' : null);
    return { year, observations: cell.observations, states, reason, row: reason ? null : cell.observations[0] };
  });
  return { metric, points: points.map((point, i) => ({ ...point, change: compareAnnual(point.row, points[i - 1]?.row) })) };
}
function chartGeometry(readings) {
  const rows = readings.flatMap(reading => reading.points.flatMap(point => point.row ? [point.row] : []));
  if (!rows.length) return { reason: 'no_comparable_observations', series: [], zeroY: 100, minRow: null, maxRow: null };
  const dimensions = ['unit', 'currency', 'source_type', 'source_role', 'fact_nature', 'period_basis'];
  if (rows.some(row => dimensions.some(key => row[key] !== rows[0][key])
    || CROSS_METRIC_SCOPE.some(key => row.comparison_identity[key] !== rows[0].comparison_identity[key]))) {
    return { reason: 'mixed_units_or_sources', series: [], zeroY: 100, minRow: null, maxRow: null };
  }
  const periods = new Map();
  for (const row of rows) {
    const period = `${row.period_basis}:${row.period_start}:${row.period_end}`;
    if (periods.has(row.fiscal_year) && periods.get(row.fiscal_year) !== period) {
      return { reason: 'unaligned_fiscal_periods', series: [], zeroY: 100, minRow: null, maxRow: null };
    }
    periods.set(row.fiscal_year, period);
  }
  const values = aligned(rows.map(row => row.value_numeric_exact));
  let low = 0n; let high = 0n; let minRow = null; let maxRow = null;
  values.forEach((n, i) => { if (n < low) { low = n; minRow = rows[i]; } if (n > high) { high = n; maxRow = rows[i]; } });
  const span = high - low || 1n;
  // Only dimensionless bounded coordinates enter Number, never financial values.
  const y = n => Number((high - n) * 100000n / span) / 1000;
  const valuesByRow = new Map(rows.map((row, i) => [row, values[i]]));
  const series = readings.map(reading => {
    const segments = []; let segment = []; let previous = null;
    reading.points.forEach((point, i) => {
      if (!point.row || (previous && comparisonProblem(point.row, previous))) {
        if (segment.length) segments.push(segment);
        segment = [];
      }
      if (point.row) segment.push({ x: reading.points.length <= 1 ? 50 : i * 100 / (reading.points.length - 1), y: y(valuesByRow.get(point.row)), row: point.row, year: point.year });
      previous = point.row;
    });
    if (segment.length) segments.push(segment);
    return { key: reading.metric.key, segments };
  });
  return { reason: null, series, zeroY: y(0n), minRow, maxRow };
}
function cashQuestion(income, cash) {
  const a = income.points.at(-1); const b = cash.points.at(-1);
  const priorA = income.points.at(-2); const priorB = cash.points.at(-2);
  const samePeriod = (x, y) => x?.row && y?.row && ['fiscal_year', 'period_start', 'period_end', 'unit', 'currency', 'source_type', 'source_role', 'fact_nature']
    .every(key => x.row[key] === y.row[key]) && CROSS_METRIC_SCOPE.every(key => x.row.comparison_identity[key] === y.row.comparison_identity[key]);
  if (samePeriod(a, b) && samePeriod(priorA, priorB) && a.change.direction === 'up' && b.change.direction === 'down') {
    return `FY${a.year}: profit rose (${a.change.text}) while operating cash flow fell (${b.change.text}). What explains the divergence? Inspect both years; these figures alone do not establish a cause.`;
  }
  return 'Does reported profit translate into operating cash flow? Compare the periods and evidence before attributing a cause; operating cash flow is not owner earnings.';
}
module.exports = { annualReading, compareAnnual, formatBillions, chartGeometry, cashQuestion };
