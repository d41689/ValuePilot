/* Pure presentation over one server response. No source selection or arithmetic conclusions. */
const CORE_METRICS = [
  { key: 'is.revenue', label: 'Revenue', description: 'Reported revenue', basis: 'duration' },
  { key: 'is.net_income', label: 'Net income', description: 'Reported net income', basis: 'duration' },
  { key: 'is.operating_cash_flow', label: 'Operating cash flow', description: 'Cash from operating activities, not owner earnings', basis: 'duration' },
  { key: 'cf.capital_expenditures', label: 'Capital expenditures', description: 'Purchases of property, plant and equipment; not an estimate of maintenance capex', basis: 'duration' },
  { key: 'bs.cash_and_equivalents', label: 'Cash and equivalents', description: 'Period-end cash and cash equivalents; not all liquid investments', basis: 'instant' },
  { key: 'cap.long_term_debt_current', label: 'Long-term debt — current portion', description: 'Current portion of long-term debt, not total debt', basis: 'instant' },
  { key: 'cap.long_term_debt_noncurrent', label: 'Long-term debt — noncurrent portion', description: 'Noncurrent long-term debt, not total debt', basis: 'instant' },
  { key: 'equity.weighted_average_diluted_shares', label: 'Weighted-average diluted shares', description: 'Weighted-average diluted shares, not period-end shares outstanding', basis: 'duration' },
  { key: 'cf.stock_based_compensation', label: 'Stock-based compensation', description: 'Reported share-based compensation expense', basis: 'duration' },
];

function decimalParts(exact) {
  if (typeof exact !== 'string' || exact.length > 256 || !/^-?\d+(?:\.\d+)?$/.test(exact)) return null;
  const negative = exact.startsWith('-');
  const [integer, fraction = ''] = (negative ? exact.slice(1) : exact).split('.');
  return { negative, integer, fraction };
}

function formatFinancialValue(row) {
  const exact = row.value_numeric_exact;
  const unitLabel = row.unit === 'shares' ? 'million shares'
    : row.unit === 'currency' ? (row.currency ? `million ${row.currency}` : 'million · currency unknown')
      : (row.unit || 'unit unknown');
  if (exact == null) return { status: 'no_numeric_value', text: 'No numeric value', unitLabel, exact: null };
  const parts = decimalParts(exact);
  if (!parts) return { status: 'invalid_numeric', text: 'Invalid numeric value', unitLabel, exact: null };
  const magnitude = BigInt(parts.integer + parts.fraction);
  // For unknown units we retain the base exact value: a guessed scale is not a display policy.
  if (!['currency', 'shares'].includes(row.unit)) return { status: 'exact_value', text: exact, unitLabel, exact };
  const denominator = 10n ** BigInt(parts.fraction.length + 4);
  const cents = (magnitude + denominator / 2n) / denominator;
  let text;
  if (magnitude !== 0n && cents === 0n) {
    text = parts.negative ? '>-0.01' : '<0.01';
  } else {
    const integer = (cents / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    text = `${parts.negative && magnitude !== 0n ? '-' : ''}${integer}.${(cents % 100n).toString().padStart(2, '0')}`;
  }
  return { status: 'display_value', text, unitLabel, exact };
}

function annualCells(history) {
  const years = history.annual_window.status === 'determined' ? history.annual_window.years : [];
  const cells = Object.fromEntries(CORE_METRICS.map(metric => [metric.key,
    Object.fromEntries(years.map(year => [year, { observations: [], states: [] }]))]));
  const metricStates = {};
  const cycleStates = [];
  const otherRows = [];
  const sorted = [...history.rows].sort((a, b) => a.row_key.localeCompare(b.row_key));
  for (const row of sorted) {
    if (row.row_kind === 'filing_cycle_state') { cycleStates.push(row); continue; }
    if (row.row_kind === 'metric_state') {
      (metricStates[row.metric_key] ||= []).push(row);
      continue;
    }
    const cell = cells[row.metric_key]?.[row.fiscal_year];
    if (cell && row.period_type === 'FY' && row.row_kind === 'slot_state') {
      cell.states.push(row);
    } else if (cell && row.period_type === 'FY' && row.row_kind === 'fact'
      && ['actual', 'derived_actual'].includes(row.fact_nature)
      && ['instant', 'duration'].includes(row.period_basis)) {
      cell.observations.push(row);
    } else {
      otherRows.push(row);
    }
  }
  return { cells, metricStates, cycleStates, otherRows };
}

function pageRows(rows, requestedPage) {
  const pageCount = Math.max(1, Math.ceil(rows.length / 50));
  const page = Math.min(pageCount, Math.max(1, Number.isInteger(requestedPage) ? requestedPage : 1));
  const offset = (page - 1) * 50;
  return { page, pageCount, start: rows.length ? offset + 1 : 0,
    end: Math.min(offset + 50, rows.length), total: rows.length, rows: rows.slice(offset, offset + 50) };
}

function canonicalDecimal(exact) {
  const parts = decimalParts(exact);
  if (!parts) return null;
  const integer = parts.integer.replace(/^0+(?=\d)/, '');
  const fraction = parts.fraction.replace(/0+$/, '');
  return `${parts.negative && (integer !== '0' || fraction) ? '-' : ''}${integer}${fraction ? `.${fraction}` : ''}`;
}

function sameEvidenceIdentity(row, evidence) {
  const period = evidence?.period;
  if (!period || row.row_kind !== 'fact' || row.fact_id !== evidence.metric_fact_id
    || row.publication_id !== evidence.publication_id || row.metric_key !== evidence.metric_key) return false;
  if (canonicalDecimal(row.value_numeric_exact) === null
    || canonicalDecimal(row.value_numeric_exact) !== canonicalDecimal(evidence.value_numeric_exact)) return false;
  return ['unit', 'currency', 'source_role', 'fact_nature'].every(key => (row[key] ?? null) === (evidence[key] ?? null))
    && Object.entries({ period_type: 'type', period_basis: 'basis', period_start: 'start',
      period_end: 'end', fiscal_year: 'fiscal_year', fiscal_quarter: 'fiscal_quarter' })
      .every(([key, target]) => (row[key] ?? null) === (period[target] ?? null));
}

function secEvidencePath(stockId, row) {
  if (!Number.isSafeInteger(stockId) || stockId <= 0 || row.row_kind !== 'fact'
    || !Number.isSafeInteger(row.fact_id) || row.fact_id <= 0
    || !Number.isSafeInteger(row.publication_id) || row.publication_id <= 0) {
    throw new Error('evidence_identity_mismatch');
  }
  return `/stocks/${stockId}/sec-publications/${row.publication_id}/evidence`;
}

async function readFinancialEvidence(client, stockId, row, signal) {
  if (signal?.aborted) return { cancelled: true };
  try {
    const { data } = await client.get(secEvidencePath(stockId, row), { params: { fact_id: row.fact_id }, signal });
    if (signal?.aborted) return { cancelled: true };
    if (data?.evidence_state !== 'available') return { error: data?.evidence_reason_code || 'evidence_unavailable' };
    if (!sameEvidenceIdentity(row, data)) return { error: 'evidence_identity_mismatch' };
    return { evidence: data };
  } catch (error) {
    if (signal?.aborted) return { cancelled: true };
    return { error: ({ 401: 'authentication_required', 403: 'source_unavailable', 404: 'evidence_unavailable' })[error?.response?.status] || 'evidence_request_failed' };
  }
}

function inputEvidenceFilings(evidence) {
  const accessions = new Set();
  const retained = new Map(evidence.filings.map(filing => [filing.accession, filing]));
  const collect = inputs => inputs.forEach(input => {
    if (input.accession) accessions.add(input.accession);
    if (input.statement?.accession) {
      const { accession, form, sec_url } = input.statement;
      accessions.add(accession);
      retained.set(accession, { accession, form, sec_url });
    }
    if (input.inputs) collect(input.inputs);
  });
  collect(evidence.inputs);
  return [...retained.values()].filter(filing => accessions.has(filing.accession));
}

module.exports = { CORE_METRICS, formatFinancialValue, annualCells, pageRows, sameEvidenceIdentity, secEvidencePath, readFinancialEvidence, inputEvidenceFilings };
// Readable exact base units; no floating-point conversion or rounded financial value.
function formatExactDecimal(value) {
  if (value === null || value === undefined) return 'Not available';
  if (typeof value !== 'string' || !/^-?\d+(\.\d+)?$/.test(value)) return String(value);
  const [integer, fraction] = value.split('.');
  const tail = fraction?.replace(/0+$/, '');
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (tail ? `.${tail}` : '');
}
module.exports.formatExactDecimal = formatExactDecimal;
