/**
 * MVP7-02: Watchlist × 13F Insight data layer.
 *
 * Types + React Query hook + merge helper for the per-stock 13F
 * snapshots that enrich `/watchlist` rows. Column-render helpers
 * (formatters / tier-to-badge / cross-signal glyph) land in
 * MVP7-03 in this same module.
 *
 * Backend contract: ``POST /api/v1/stocks/13f-snapshots`` —
 * see ``docs/tasks/2026-05-13_mvp7-01-stocks-13f-snapshots-endpoint.md``.
 */

import { useQuery } from '@tanstack/react-query';

import apiClient from '@/lib/api/client';

// ----- Types --------------------------------------------------------------

export type Watchlist13FAvailableSnapshot = {
  stock_id: number;
  available: true;
  conviction_score: number;
  conviction_percentile: number;
  delta_holders: number;
  adders_count: number;
  reducers_count: number;
  consensus_count: number;
  distinctiveness_tier: 'distinctive' | 'mixed' | 'crowded';
  caveat_severity: 'ok' | 'caution' | 'high-caution';
  caveat_codes: string[];
  score_confidence: 'high' | 'medium' | 'low';
};

export type Watchlist13FUnavailableSnapshot = {
  stock_id: number;
  available: false;
  unavailable_reason:
    | 'no_holders'
    | 'below_min_holders'
    | 'no_qualifying_period';
};

export type Watchlist13FSnapshot =
  | Watchlist13FAvailableSnapshot
  | Watchlist13FUnavailableSnapshot;

export type Watchlist13FSnapshotPayload = {
  period: string | null;
  period_filing_deadline: string | null;
  universe_size: number;
  snapshots: Watchlist13FSnapshot[];
};

// ----- Query hook --------------------------------------------------------

/**
 * Fetch 13F snapshots for an arbitrary set of watchlist stock IDs.
 *
 * The query key is keyed on the SORTED stock_ids so two callers
 * passing `[3, 1, 2]` and `[1, 2, 3]` share the same cache entry.
 *
 * Returns the React Query result directly — the page render code
 * builds the per-row Map via `buildSnapshotsByStockId`.
 */
export function useWatchlist13FSnapshots(stockIds: number[]) {
  const sortedStockIds = [...stockIds].sort((a, b) => a - b);
  return useQuery({
    queryKey: ['watchlist-13f-snapshots', sortedStockIds],
    queryFn: async () => {
      const res = await apiClient.post('/stocks/13f-snapshots', {
        stock_ids: sortedStockIds,
      });
      return res.data as Watchlist13FSnapshotPayload;
    },
    enabled: sortedStockIds.length > 0,
    // 13F filings are quarterly EOD data; no need to refetch on
    // every window focus.
    staleTime: 60_000,
  });
}

// ----- Merge helper -------------------------------------------------------

/**
 * Build an O(1) lookup map of stock_id → snapshot. Page render
 * code passes a `WatchlistRow.stock_id` to this map to retrieve
 * the row's 13F snapshot without iterating the snapshots array.
 *
 * Returns an empty Map when the payload is null/undefined.
 */
export function buildSnapshotsByStockId(
  payload: Watchlist13FSnapshotPayload | undefined | null,
): Map<number, Watchlist13FSnapshot> {
  const map = new Map<number, Watchlist13FSnapshot>();
  if (!payload) return map;
  for (const snapshot of payload.snapshots) {
    map.set(snapshot.stock_id, snapshot);
  }
  return map;
}
