export type CanonicalCurrentPrice = {
  status: 'available' | 'unavailable';
  value: number | null;
  observation_value: number | null;
  price_id: number | null;
  price_date: string | null;
  currency: string | null;
  source: string | null;
  observed_at: string | null;
  freshness_state: 'fresh' | 'stale' | 'missing' | 'unknown_freshness';
  source_authorization_state: 'authorized' | 'unauthorized' | 'unavailable';
  reason_code: string | null;
  as_of_date: string;
  as_of_mode: 'latest_completed_session' | 'start_of_day' | 'through_session';
  expected_session_date: string | null;
  calendar_code: string | null;
  freshness_policy_version: string;
  calendar_policy_version: string;
  source_policy_version: string;
};

export type ReportPriceReference = {
  label: 'report_reference';
  value: number | null;
  as_of_date: string | null;
  currency: string | null;
  provenance?: {
    source_type?: string | null;
    source_document_id?: number | null;
    source_report_date?: string | null;
    period_end_date?: string | null;
    is_active_report?: boolean;
  } | null;
};

export function currentPriceEvidenceLabel(price: CanonicalCurrentPrice): string {
  const parts = [
    price.price_date ?? 'no observation',
    price.source ?? 'source unavailable',
    price.currency ?? 'currency unknown',
    price.freshness_state,
  ];
  return parts.join(' · ');
}
