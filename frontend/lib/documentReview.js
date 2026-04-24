const SECTION_ORDER = [
  'identity_header',
  'ratings_quality',
  'target_projection',
  'capital_structure',
  'annual_rates',
  'quarterly_tables',
  'annual_financials',
  'institutional_decisions',
  'narrative',
];

function buildDocumentReviewSections(groups) {
  if (!Array.isArray(groups)) {
    return [];
  }
  const order = new Map(SECTION_ORDER.map((key, index) => [key, index]));
  return [...groups]
    .filter((group) => Array.isArray(group.items) && group.items.length > 0)
    .sort((a, b) => (order.get(a.key) ?? 999) - (order.get(b.key) ?? 999))
    .map((group) => ({
      ...group,
      items: group.items.map((item) => ({
        ...item,
        valueLabel: formatDocumentReviewValue(item),
        meta: formatDocumentReviewMeta(item),
        evidenceLabel: formatDocumentReviewEvidenceLabel(item),
      })),
    }));
}

function formatDocumentReviewValue(item) {
  if (!item || typeof item !== 'object') {
    return 'Not available';
  }
  if (item.display_value !== null && item.display_value !== undefined && item.display_value !== '') {
    return String(item.display_value);
  }
  if (item.value_numeric !== null && item.value_numeric !== undefined) {
    return [formatNumber(item.value_numeric), item.unit].filter(Boolean).join(' ');
  }
  if (item.value_text !== null && item.value_text !== undefined && item.value_text !== '') {
    return String(item.value_text);
  }
  return 'Not available';
}

function formatDocumentReviewMeta(item) {
  if (!item || typeof item !== 'object') {
    return null;
  }
  const parts = [];
  if (item.period_type) {
    parts.push(item.period_type);
  }
  const dateLabel = formatDateOnly(item.period_end_date || item.as_of_date);
  if (dateLabel) {
    parts.push(dateLabel);
  }
  if (item.source_type) {
    parts.push(item.source_type);
  }
  parts.push(item.is_current ? 'Current' : 'Historical');
  return parts.join(' · ') || null;
}

function formatDocumentReviewEvidenceLabel(item) {
  const pageNumber = item && item.lineage ? item.lineage.page_number : null;
  return typeof pageNumber === 'number' ? `p.${pageNumber}` : 'No lineage';
}

function formatDateOnly(iso) {
  if (!iso || typeof iso !== 'string') {
    return null;
  }
  const dt = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(dt.getTime())) {
    return iso;
  }
  return dt.toLocaleDateString();
}

function formatNumber(value) {
  if (typeof value !== 'number') {
    return String(value);
  }
  return Number.isInteger(value) ? String(value) : String(value);
}

module.exports = {
  SECTION_ORDER,
  buildDocumentReviewSections,
  formatDocumentReviewValue,
  formatDocumentReviewMeta,
  formatDocumentReviewEvidenceLabel,
};
