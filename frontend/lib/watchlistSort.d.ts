export type WatchlistSortKey =
  | 'default'
  | 'ticker'
  | 'company'
  | 'conviction'
  | 'delta_holders'
  | 'distinctiveness'
  | 'caveat_severity';

export type WatchlistSortDirection = 'asc' | 'desc';

export type WatchlistSortState = {
  key: WatchlistSortKey;
  direction: WatchlistSortDirection;
};

export const WATCHLIST_SORT_KEYS: ReadonlyArray<Exclude<WatchlistSortKey, 'default'>>;

export const DEFAULT_SORT_DIRECTION: Readonly<
  Record<Exclude<WatchlistSortKey, 'default'>, WatchlistSortDirection>
>;

export const DEFAULT_SORT_STATE: Readonly<WatchlistSortState>;

export function nextSortState(
  currentState: WatchlistSortState,
  clickedKey: Exclude<WatchlistSortKey, 'default'>,
): WatchlistSortState;

type SnapshotLike = {
  available?: boolean;
  conviction_percentile?: number | null;
  delta_holders?: number | null;
  distinctiveness_tier?: 'distinctive' | 'mixed' | 'crowded';
  caveat_severity?: 'ok' | 'caution' | 'high-caution';
};

type MemberLike = {
  stock_id: number;
  ticker: string;
  company_name?: string | null;
  mos?: number | null;
};

export function sortMembers<T extends MemberLike>(
  members: T[],
  snapshotsByStockId:
    | Map<number, SnapshotLike | null | undefined>
    | Record<number, SnapshotLike | null | undefined>
    | null
    | undefined,
  sortState: WatchlistSortState,
): T[];
