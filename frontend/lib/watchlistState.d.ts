export function sortWatchlistMembers<T extends { ticker: string; mos: number | null }>(
  rows: T[]
): T[];

export function buildFairValueEdits(
  rows: Array<{ stock_id: number; fair_value: number | null }>
): Record<number, string>;

export function hasFairValueEditChanges(
  current: Record<number, string>,
  next: Record<number, string>
): boolean;

export type PiotroskiFScore = {
  fiscal_year: number | null;
  score: number | null;
  status?: string | null;
  variant?: string | null;
  partial_score?: number | null;
  available_indicators?: number | null;
  max_available_score?: number | null;
  missing_indicators?: string[];
};

export function formatPiotroskiFScore(score: PiotroskiFScore | null | undefined): string;

export function formatPiotroskiFScoreSeries(scores: PiotroskiFScore[] | null | undefined): string;
