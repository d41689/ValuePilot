export const OVERVIEW_WATCHLIST_ID: 'overview';

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

export function formatWatchlistOptionLabel(pool: {
  name?: string | null;
  member_count?: number | null;
}): string;

export function isOverviewWatchlistId(value: unknown): value is typeof OVERVIEW_WATCHLIST_ID;

export function formatOverviewOptionLabel(count: number | null | undefined): string;

export function getRefreshPricesButtonPresentation(isPending: boolean): {
  iconClassName: string;
  label: string;
};

export function formatRefreshPricesSuccessDescription(
  results: Array<{ status?: string | null }> | null | undefined,
  requestedCount: number
): string;

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
