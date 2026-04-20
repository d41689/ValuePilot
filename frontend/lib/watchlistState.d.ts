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
