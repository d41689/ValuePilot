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

function formatConflictValue(observation) {
  if (!observation || typeof observation !== 'object') {
    return '—';
  }
  if (typeof observation.value_numeric === 'number') {
    return observation.value_numeric.toLocaleString('en-US', {
      maximumFractionDigits: 4,
    });
  }
  if (observation.value_text) {
    return observation.value_text;
  }
  return '—';
}

function formatMetricLabel(metricKey) {
  if (!metricKey || typeof metricKey !== 'string') {
    return 'Unknown metric';
  }
  return metricKey.replaceAll('.', ' / ');
}

function formatPeriodLabel(periodType, periodEndDate) {
  const parts = [];
  if (periodType) {
    parts.push(periodType);
  }
  const formattedDate = formatDateOnly(periodEndDate);
  if (formattedDate) {
    parts.push(formattedDate);
  }
  return parts.join(' · ') || 'Unknown period';
}

function buildActualConflictDisplayItems(conflicts, maxItems = 5) {
  if (!Array.isArray(conflicts) || conflicts.length === 0) {
    return [];
  }
  return conflicts.slice(0, maxItems).map((conflict) => {
    const observations = Array.isArray(conflict.observations) ? conflict.observations : [];
    const latest = observations[0] ?? null;
    const previous = observations[1] ?? null;
    return {
      metricLabel: formatMetricLabel(conflict.metric_key),
      periodLabel: formatPeriodLabel(conflict.period_type, conflict.period_end_date),
      latestValueLabel: formatConflictValue(latest),
      previousValueLabel: formatConflictValue(previous),
      latestReportLabel: latest?.source_report_date ? formatDateOnly(latest.source_report_date) : null,
      previousReportLabel: previous?.source_report_date
        ? formatDateOnly(previous.source_report_date)
        : null,
      observationCount: observations.length,
    };
  });
}

module.exports = {
  buildActualConflictDisplayItems,
  formatConflictValue,
  formatMetricLabel,
  formatPeriodLabel,
};
