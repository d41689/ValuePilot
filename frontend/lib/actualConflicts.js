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

function formatConflictRawValue(valueNumeric, valueText) {
  return formatConflictValue({
    value_numeric: valueNumeric,
    value_text: valueText,
  });
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

function formatSelectionRuleLabel(selectionRule) {
  if (selectionRule === 'latest_report_wins_for_same_actual_period') {
    return 'Same historical period: latest report wins.';
  }
  return 'Same historical period: current source value is used.';
}

function formatUsageLabel(prefix, valueLabel, reportLabel) {
  if (reportLabel) {
    return `${prefix}: ${valueLabel} from ${reportLabel}`;
  }
  return `${prefix}: ${valueLabel}`;
}

function buildActualConflictDisplayItems(conflicts, maxItems = 5) {
  if (!Array.isArray(conflicts) || conflicts.length === 0) {
    return [];
  }
  return conflicts.slice(0, maxItems).map((conflict) => {
    const observations = Array.isArray(conflict.observations) ? conflict.observations : [];
    const latest = observations[0] ?? null;
    const previous = observations[1] ?? null;
    const latestValueLabel =
      conflict.current_value_numeric !== undefined || conflict.current_value_text !== undefined
        ? formatConflictRawValue(conflict.current_value_numeric, conflict.current_value_text)
        : formatConflictValue(latest);
    const previousValueLabel =
      conflict.previous_value_numeric !== undefined || conflict.previous_value_text !== undefined
        ? formatConflictRawValue(conflict.previous_value_numeric, conflict.previous_value_text)
        : formatConflictValue(previous);
    const latestReportLabel = conflict.current_report_date
      ? formatDateOnly(conflict.current_report_date)
      : latest?.source_report_date
        ? formatDateOnly(latest.source_report_date)
        : null;
    const previousReportLabel = conflict.previous_report_date
      ? formatDateOnly(conflict.previous_report_date)
      : previous?.source_report_date
        ? formatDateOnly(previous.source_report_date)
        : null;
    return {
      metricLabel: formatMetricLabel(conflict.metric_key),
      periodLabel: formatPeriodLabel(conflict.period_type, conflict.period_end_date),
      latestValueLabel,
      previousValueLabel,
      latestReportLabel,
      previousReportLabel,
      selectionRuleLabel: formatSelectionRuleLabel(conflict.selection_rule),
      currentUsageLabel: formatUsageLabel('Current value used', latestValueLabel, latestReportLabel),
      previousUsageLabel: formatUsageLabel('Previous report value', previousValueLabel, previousReportLabel),
      observationCount: observations.length,
    };
  });
}

module.exports = {
  buildActualConflictDisplayItems,
  formatConflictValue,
  formatMetricLabel,
  formatPeriodLabel,
  formatSelectionRuleLabel,
};
