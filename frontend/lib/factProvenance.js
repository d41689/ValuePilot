function formatFactProvenanceLabel(provenance) {
  if (!provenance || typeof provenance !== 'object') {
    return null;
  }

  const segments = [];
  if (provenance.is_active_report) {
    segments.push('Active report');
  } else if (provenance.source_type === 'parsed') {
    segments.push('Parsed fact');
  } else if (typeof provenance.source_type === 'string') {
    segments.push(capitalize(provenance.source_type));
  }

  const reportDate = formatDateOnly(provenance.source_report_date);
  if (reportDate) {
    segments.push(reportDate);
  }

  if (Number.isInteger(provenance.source_document_id)) {
    segments.push(`doc #${provenance.source_document_id}`);
  } else {
    const periodEnd = formatDateOnly(provenance.period_end_date);
    if (periodEnd) {
      segments.push(`period end ${periodEnd}`);
    }
  }

  return segments.length > 0 ? segments.join(' · ') : null;
}

function formatComputedFactProvenanceLabel(provenance) {
  if (!provenance || !Array.isArray(provenance.inputs) || provenance.inputs.length === 0) {
    return null;
  }
  const first = provenance.inputs[0];
  const segments = [first && first.is_active_report ? 'Computed from active report' : 'Computed from parsed facts'];
  const reportDate = formatDateOnly(first?.source_report_date);
  if (reportDate) {
    segments.push(reportDate);
  }
  if (Number.isInteger(first?.source_document_id)) {
    segments.push(`doc #${first.source_document_id}`);
  }
  return segments.join(' · ');
}

function formatDateOnly(value) {
  if (typeof value !== 'string' || value.length === 0) {
    return null;
  }
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString('en-US');
}

function capitalize(value) {
  if (typeof value !== 'string' || value.length === 0) {
    return '';
  }
  return value.charAt(0).toUpperCase() + value.slice(1);
}

module.exports = {
  formatFactProvenanceLabel,
  formatComputedFactProvenanceLabel,
};
