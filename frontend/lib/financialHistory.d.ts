export type FinancialHistoryRow = {
  row_kind: 'fact' | 'slot_state' | 'metric_state' | 'filing_cycle_state';
  row_key: string;
  status: string;
  reason_code: string | null;
  metric_key: string | null;
  fact_id: number | null;
  publication_id: number | null;
  value_numeric_exact: string | null;
  value_text: string | null;
  unit: string | null;
  currency: string | null;
  period_type: string | null;
  period_basis: string | null;
  period_start: string | null;
  period_end: string | null;
  fiscal_year: number | null;
  fiscal_quarter: number | null;
  source_type: string | null;
  source_role: string | null;
  fact_nature: string | null;
  comparison_identity: Record<string, unknown> | null;
  scope: Record<string, unknown> | null;
  evidence_capability: 'sec_statement' | 'document_review' | 'reference_only' | 'unavailable';
  document_id: number | null;
};
export function formatExactDecimal(value: string | null | undefined): string;
export type FinancialHistory = {
  schema_version: 1;
  evaluated_at: string;
  annual_window: { status: 'determined' | 'undetermined'; years: number[]; anchor_fact_id: number | null; reason_code: string | null };
  total_rows: number;
  available_fact_count: number;
  state_count: number;
  rows: FinancialHistoryRow[];
};
export const CORE_METRICS: ReadonlyArray<{ key: string; label: string; description: string; basis: string }>;
export function formatFinancialValue(row: FinancialHistoryRow): {
  status: 'display_value' | 'exact_value' | 'no_numeric_value' | 'invalid_numeric'; text: string; unitLabel: string; exact: string | null;
};
export function annualCells(history: FinancialHistory): {
  cells: Record<string, Record<number, { observations: FinancialHistoryRow[]; states: FinancialHistoryRow[] }>>;
  metricStates: Record<string, FinancialHistoryRow[]>;
  cycleStates: FinancialHistoryRow[];
  otherRows: FinancialHistoryRow[];
};
export function pageRows(rows: FinancialHistoryRow[], page: number): {
  page: number; pageCount: number; start: number; end: number; total: number; rows: FinancialHistoryRow[];
};
export function sameEvidenceIdentity(row: FinancialHistoryRow, evidence: unknown): boolean;
export function secEvidencePath(stockId: number, row: FinancialHistoryRow): string;
type EvidenceFiling = { accession: string; form?: string; sec_url?: string | null };
type FilingInput = { accession?: string; statement?: EvidenceFiling; inputs?: FilingInput[] };
export function inputEvidenceFilings(evidence: { filings: EvidenceFiling[]; inputs: FilingInput[] }): EvidenceFiling[];
export function readFinancialEvidence<T>(client: {
  get: (url: string, config: { params: { fact_id: number | null }; signal?: AbortSignal }) => Promise<{ data: T }>;
}, stockId: number,
  row: FinancialHistoryRow, signal?: AbortSignal): Promise<{ evidence?: T; error?: string; cancelled?: boolean }>;
