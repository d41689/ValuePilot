const SECTION_META = {
  'company.business_description.as_of': {
    sectionId: 'business',
    sectionTitle: 'Business',
    label: 'Business Description',
  },
  'analyst.commentary.as_of': {
    sectionId: 'commentary',
    sectionTitle: 'Commentary',
    label: 'Analyst Commentary',
  },
  'rating.timeliness.event': {
    sectionId: 'ratings',
    sectionTitle: 'Rating Events',
    label: 'Timeliness',
  },
  'rating.safety.event': {
    sectionId: 'ratings',
    sectionTitle: 'Rating Events',
    label: 'Safety',
  },
  'rating.technical.event': {
    sectionId: 'ratings',
    sectionTitle: 'Rating Events',
    label: 'Technical',
  },
};

const SECTION_ORDER = ['business', 'commentary', 'ratings'];

function formatDocumentEvidencePeriod(periodType, periodEndDate) {
  if (!periodEndDate) {
    return null;
  }

  const parsed = new Date(`${periodEndDate}T00:00:00`);
  const formatted = Number.isNaN(parsed.getTime())
    ? periodEndDate
    : parsed.toLocaleDateString('en-US');

  if (periodType === 'EVENT') {
    return `Event date ${formatted}`;
  }
  return `As of ${formatted}`;
}

function buildDocumentEvidenceSections(items) {
  const sections = new Map();

  for (const item of items || []) {
    const meta = SECTION_META[item.mapping_id];
    if (!meta) {
      continue;
    }

    const current = sections.get(meta.sectionId) || {
      id: meta.sectionId,
      title: meta.sectionTitle,
      items: [],
    };

    const period = formatDocumentEvidencePeriod(item.period_type, item.period_end_date);
    const pageMeta =
      typeof item.page_number === 'number' ? `p.${item.page_number}` : null;
    const metaText = [period, pageMeta].filter(Boolean).join(' · ') || null;
    const detail =
      item.value_json && typeof item.value_json.raw === 'string'
        ? item.value_json.raw
        : item.original_text_snippet || null;

    current.items.push({
      label: meta.label,
      value: capitalizeEvidenceValue(item.value_text),
      meta: metaText,
      detail,
    });
    sections.set(meta.sectionId, current);
  }

  return SECTION_ORDER.map((sectionId) => sections.get(sectionId)).filter(Boolean);
}

function capitalizeEvidenceValue(value) {
  if (typeof value !== 'string' || value.length === 0) {
    return value || '';
  }
  return value.charAt(0).toUpperCase() + value.slice(1);
}

module.exports = {
  buildDocumentEvidenceSections,
  formatDocumentEvidencePeriod,
};
