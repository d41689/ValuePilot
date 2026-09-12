const CALCULATION_LABELS = {
  piotroski_f_score: 'Piotroski F-Score',
  value_line_ratios: 'Value Line ratios',
};

function getCalculationWarnings(payload) {
  const entries = [
    ...(Array.isArray(payload?.calculation_outcomes) ? payload.calculation_outcomes : []),
    ...(Array.isArray(payload?.page_reports) ? payload.page_reports.flatMap(
      page => Array.isArray(page?.calculation_outcomes) ? page.calculation_outcomes : [],
    ) : []),
  ];
  const labels = new Set();
  for (const item of entries) {
    if (item?.status !== 'unavailable' || item.reason_code !== 'unresolved_source_reconciliation') continue;
    if (Object.hasOwn(CALCULATION_LABELS, item.calculation)) labels.add(CALCULATION_LABELS[item.calculation]);
  }
  return [...labels].map(label => `${label} is unavailable because source reconciliation is unresolved. No blocked numeric result was published.`);
}

function getDocumentProcessingResult(payload) {
  const warnings = getCalculationWarnings(payload);
  const status = payload?.status ?? payload?.parse_status;
  if (status === 'parsed') {
    return {
      tone: warnings.length ? 'warning' : 'success',
      title: 'Source facts parsed',
      description: 'Source facts were retained. Reading and calculation eligibility are checked separately; parsing is not an investment conclusion.',
      warnings,
    };
  }
  if (status === 'failed') {
    return {tone: 'danger', title: 'Document parsing failed',
      description: 'The document was received, but source parsing did not complete successfully. Review its status before using the data.', warnings};
  }
  return {tone: 'warning', title: status === 'parsed_partial' ? 'Source facts partially parsed' : 'Document requires review',
    description: 'Do not assume all pages or financial facts are available. Review the document processing status.', warnings};
}

module.exports = { getCalculationWarnings, getDocumentProcessingResult };
