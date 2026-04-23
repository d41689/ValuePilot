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

function formatDocumentCompareMeta(item) {
  if (!item || typeof item !== 'object') {
    return null;
  }
  const parts = [];
  if (item.period_type) {
    parts.push(item.period_type);
  }
  const formattedDate = formatDateOnly(item.period_end_date);
  if (formattedDate) {
    parts.push(formattedDate);
  }
  return parts.join(' · ') || null;
}

function buildVisibleDocumentCompareSections(sections) {
  if (!Array.isArray(sections)) {
    return [];
  }
  return sections
    .filter((section) => Array.isArray(section.items) && section.items.length > 0)
    .map((section) => ({
      id: section.fact_nature,
      title: section.title || section.fact_nature,
      items: section.items.map((item) => ({
        ...item,
        meta: formatDocumentCompareMeta(item),
      })),
    }));
}

module.exports = {
  buildVisibleDocumentCompareSections,
  formatDocumentCompareMeta,
};
