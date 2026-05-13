/**
 * MVP7-02 + MVP7-03: Watchlist × 13F Insight data + render layer.
 *
 * Types + React Query hook + merge helper for the per-stock 13F
 * snapshots that enrich `/watchlist` rows (MVP7-02), plus the
 * column-render helpers (chip labels, tone variants, tooltip
 * copy, group-header formatting) that the four-column UI
 * consumes (MVP7-03).
 *
 * Backend contract: ``POST /api/v1/stocks/13f-snapshots`` —
 * see ``docs/tasks/2026-05-13_mvp7-01-stocks-13f-snapshots-endpoint.md``.
 */

import type { ComponentProps } from 'react';
import { useQuery } from '@tanstack/react-query';

import apiClient from '@/lib/api/client';
import type { Badge } from '@/components/ui/badge';

type BadgeVariant = ComponentProps<typeof Badge>['variant'];

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

// ----- MVP7-03 render helpers --------------------------------------------

const PCT_FORMATTER = new Intl.NumberFormat('en-US', {
  style: 'percent',
  maximumFractionDigits: 0,
});

/**
 * Display label for the conviction percentile chip per
 * Pre-MVP7-01 D1: "Top 15%" / "Mid N%" / "Bot N%".
 *
 * - ``percentile > 0.85`` → "Top 15%" (or smaller if even higher
 *   percentile).
 * - ``percentile > 0.50`` → "Mid {1 - percentile}%" — the
 *   "distance from top" reading.
 * - ``percentile <= 0.50`` → "Bot {percentile}%".
 */
export function formatConvictionLabel(percentile: number): string {
  if (percentile > 0.85) {
    const topPct = 1 - percentile;
    return `Top ${PCT_FORMATTER.format(Math.max(topPct, 0))}`;
  }
  if (percentile > 0.5) {
    const fromTop = 1 - percentile;
    return `Mid ${PCT_FORMATTER.format(fromTop)}`;
  }
  return `Bot ${PCT_FORMATTER.format(Math.max(percentile, 0))}`;
}

export function convictionTone(percentile: number): BadgeVariant {
  if (percentile > 0.85) return 'success';
  if (percentile > 0.5) return 'secondary';
  return 'outline';
}

/**
 * Signed-integer formatter for the Δ Holders chip. Uses a Unicode
 * minus sign (U+2212) for negative values so the chip reads
 * cleanly at small sizes.
 */
export function formatDeltaHolders(delta: number): string {
  if (delta > 0) return `+${delta}`;
  if (delta < 0) return `−${Math.abs(delta)}`;
  return '0';
}

export function deltaHoldersTone(delta: number): BadgeVariant {
  if (delta > 0) return 'success';
  if (delta < 0) return 'danger';
  return 'secondary';
}

export function distinctivenessLabel(
  tier: Watchlist13FAvailableSnapshot['distinctiveness_tier'],
): string {
  switch (tier) {
    case 'distinctive':
      return 'Distinctive';
    case 'crowded':
      return 'Crowded';
    case 'mixed':
    default:
      return 'Mixed';
  }
}

export function distinctivenessTone(
  tier: Watchlist13FAvailableSnapshot['distinctiveness_tier'],
): BadgeVariant {
  switch (tier) {
    case 'distinctive':
      return 'success';
    case 'crowded':
      return 'warning';
    case 'mixed':
    default:
      return 'secondary';
  }
}

export function caveatSeverityLabel(
  severity: Watchlist13FAvailableSnapshot['caveat_severity'],
): string {
  switch (severity) {
    case 'ok':
      return 'OK';
    case 'caution':
      return 'Caution';
    case 'high-caution':
      return 'Caution';
  }
}

export function caveatSeverityTone(
  severity: Watchlist13FAvailableSnapshot['caveat_severity'],
): BadgeVariant {
  switch (severity) {
    case 'ok':
      return 'success';
    case 'caution':
      return 'warning';
    case 'high-caution':
      return 'danger';
  }
}

/**
 * Tooltip body for an unavailable-snapshot cell. The ``period``
 * argument is the payload's ``period`` string (e.g. ``"2025-Q4"``)
 * — null when no qualifying period exists.
 */
export function unavailableTooltip(
  reason: Watchlist13FUnavailableSnapshot['unavailable_reason'],
  period: string | null,
): string {
  const periodLabel = period ?? 'the latest period';
  switch (reason) {
    case 'no_holders':
      return `No 13F filer holds this stock above the $200M AUM reporting threshold for ${periodLabel}.`;
    case 'below_min_holders':
      return `Below the minimum-holders threshold for ${periodLabel}. Insufficient consensus for ranking.`;
    case 'no_qualifying_period':
      return `13F data is unavailable for ${periodLabel}.`;
  }
}

/**
 * Group-header text for the four-column 13F section.
 *
 * - Both period + deadline present → ``"13F (2025-Q4, as of 2026-02-14)"``.
 * - Period present, deadline null → ``"13F (2025-Q4)"``.
 * - Neither present → ``"13F (no data)"``.
 */
export function groupHeaderLabel(
  period: string | null,
  periodFilingDeadline: string | null,
): string {
  if (!period) return '13F (no data)';
  if (!periodFilingDeadline) return `13F (${period})`;
  return `13F (${period}, as of ${periodFilingDeadline})`;
}
