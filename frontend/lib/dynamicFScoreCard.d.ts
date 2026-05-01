export type DynamicFScoreStatusTone = 'success' | 'warning' | 'danger' | 'secondary';

export type DynamicFScoreApiRow = {
  category?: string;
  check?: string;
  metric_key?: string;
  formula?: string;
  scores?: Array<number | null>;
  status?: string;
  status_tone?: DynamicFScoreStatusTone | string;
  comment?: string;
};

export type DynamicFScoreApiCard = {
  years?: Array<number | string>;
  rows?: DynamicFScoreApiRow[];
} | null;

export type DynamicFScoreRow = {
  category: string;
  check: string;
  metricKey: string;
  formula: string;
  scores: Array<number | null>;
  status: string;
  statusTone: DynamicFScoreStatusTone;
  comment: string;
};

export type DynamicFScoreCardModel = {
  years: string[];
  rows: DynamicFScoreRow[];
};

export function normalizeDynamicFScoreCard(card: DynamicFScoreApiCard): DynamicFScoreCardModel;
export function formatDynamicFScoreValue(value: number | null | undefined): string;
