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
  // MVP8-03B B4: portfolio-weight context for the Δ Holders chip
  // tooltip — sum of position_weight across adders / reducers.
  adders_portfolio_weight_sum: number;
  reducers_portfolio_weight_sum: number;
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
 * Pre-MVP7-01 D1, with the MVP7-06 SME-flag suffix appended so
 * the chip cannot be misread as an overall ranking or
 * signal-weighted consensus position.
 *
 * - ``percentile > 0.85`` → "Top N% conviction" (N = distance
 *   from the top).
 * - ``percentile > 0.50`` → "Mid N% conviction".
 * - ``percentile <= 0.50`` → "Bot N% conviction".
 */
export function formatConvictionLabel(percentile: number): string {
  if (percentile > 0.85) {
    const topPct = 1 - percentile;
    return `Top ${PCT_FORMATTER.format(Math.max(topPct, 0))} conviction`;
  }
  if (percentile > 0.5) {
    const fromTop = 1 - percentile;
    return `Mid ${PCT_FORMATTER.format(fromTop)} conviction`;
  }
  return `Bot ${PCT_FORMATTER.format(Math.max(percentile, 0))} conviction`;
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

// ----- MVP7-04 cross-signal helpers --------------------------------------

export type MosCrossSignal =
  | 'aligned'
  | 'weak-aligned'
  | 'exit-divergence'
  | 'buy-divergence'
  | 'neutral';

/**
 * MOS × 13F cross-signal. Returns ``'neutral'`` for any input where
 * MOS or Δ Holders is unavailable.
 *
 * MVP8-03B B3 (2026-05-13): two-tier alignment — V1's
 * ``(MOS ≥ 0.20, Δ ≥ +1)`` is preserved as the new ``weak-aligned``
 * tier; ``aligned`` is reserved for the stronger
 * ``(MOS ≥ 0.30, Δ ≥ +3)`` cross-signal so the visual emphasis
 * actually tracks high-confidence cases. SME flag from the
 * MVP7-06 four-role review.
 *
 * - ``aligned``: MOS ≥ 30% AND Δ Holders ≥ +3
 * - ``weak-aligned``: MOS ≥ 20% AND Δ Holders ≥ +1 (and below aligned)
 * - ``exit-divergence``: MOS ≥ 20% AND Δ Holders ≤ −1
 * - ``buy-divergence``: MOS ≤ 0 AND Δ Holders ≥ +1
 * - ``neutral``: otherwise
 */
export function mosCrossSignal(args: {
  mos: number | null | undefined;
  deltaHolders: number | null | undefined;
}): MosCrossSignal {
  const { mos, deltaHolders } = args;
  if (mos === null || mos === undefined) return 'neutral';
  if (deltaHolders === null || deltaHolders === undefined) return 'neutral';
  if (mos >= 0.3 && deltaHolders >= 3) return 'aligned';
  if (mos >= 0.2 && deltaHolders >= 1) return 'weak-aligned';
  if (mos >= 0.2 && deltaHolders <= -1) return 'exit-divergence';
  if (mos <= 0 && deltaHolders >= 1) return 'buy-divergence';
  return 'neutral';
}

export function mosCrossSignalTooltip(signal: MosCrossSignal): string {
  switch (signal) {
    case 'aligned':
      return 'Aligned: smart money is meaningfully adding (Δ ≥ +3) into a deep value setup (MOS ≥ 30%).';
    case 'weak-aligned':
      return 'Weakly aligned: smart money is adding (Δ ≥ +1) and there is some margin of safety (MOS ≥ 20%), but neither signal is strong.';
    case 'exit-divergence':
      return 'Re-examine: smart money is exiting while you see value.';
    case 'buy-divergence':
      return 'Re-examine FV: smart money is adding despite no margin of safety.';
    case 'neutral':
      return '';
  }
}

/**
 * Tailwind class string for a 13F cell that respects D4 responsive
 * tiers. The caller passes the current ``mdExpanded`` state.
 *
 * - At xl (≥ 1280px): always shown.
 * - At md (768–1279px): shown when ``mdExpanded`` is true.
 * - Below md: hidden.
 */
export function responsive13FCellClass(mdExpanded: boolean): string {
  return mdExpanded ? 'hidden md:table-cell xl:table-cell' : 'hidden xl:table-cell';
}

// ----- MVP7-05 detail-endpoint types + hook -------------------------------

export type StockDetailTopHolderAction =
  | 'new'
  | 'add'
  | 'reduce'
  | 'exit'
  | 'flat';

export type Watchlist13FTopHolder = {
  manager_id: number;
  manager_name: string;
  manager_type: string;
  // MVP8-03B B1: admin-classified manager_type alongside the canonical
  // (behavior-derived where applicable) one. Drawer renders both when
  // they differ.
  manager_type_admin_classified: string;
  manager_signal_weight: number;
  position_weight: number;
  position_rank: number | null;
  action: StockDetailTopHolderAction | string;
  share_delta_pct: number | null;
  current_shares: number | null;
  previous_shares: number | null;
  current_value_thousands: number | null;
  holding_streak_quarters: number;
  portfolio_concentration: number | null;
  portfolio_holding_count: number | null;
  average_holding_period_quarters: number | null;
  filing_date: string | null;
  accession_no: string | null;
};

export type Watchlist13FCaveatFlag = {
  key: string;
  group: string;
  severity: 'warning' | 'info';
  label: string;
};

export type Watchlist13FAvailableDetail = {
  stock_id: number;
  ticker: string;
  company_name: string | null;
  available: true;
  conviction_score: number;
  conviction_percentile: number;
  delta_holders: number;
  adders_count: number;
  reducers_count: number;
  // MVP8-03B B4: portfolio-weight context.
  adders_portfolio_weight_sum: number;
  reducers_portfolio_weight_sum: number;
  consensus_count: number;
  distinctiveness_tier: 'distinctive' | 'mixed' | 'crowded';
  caveat_severity: 'ok' | 'caution' | 'high-caution';
  score_confidence: 'high' | 'medium' | 'low';
  top_holders: Watchlist13FTopHolder[];
  caveat_flags: Watchlist13FCaveatFlag[];
};

export type Watchlist13FUnavailableDetail = {
  stock_id: number;
  ticker: string | null;
  company_name: string | null;
  available: false;
  unavailable_reason:
    | 'no_holders'
    | 'below_min_holders'
    | 'no_qualifying_period';
};

export type Watchlist13FDetailPayload = {
  period: string | null;
  period_filing_deadline: string | null;
  universe_size: number;
  detail: Watchlist13FAvailableDetail | Watchlist13FUnavailableDetail;
};

/**
 * Fetch detail-level 13F data for one stock when the user opens the
 * drawer. ``enabled`` gated on stockId !== null so the query stays
 * dormant until a row is selected.
 */
export function useWatchlistStock13FDetail(
  stockId: number | null,
  period?: string,
) {
  return useQuery({
    queryKey: ['watchlist-13f-stock-detail', stockId, period ?? 'latest'],
    queryFn: async () => {
      if (stockId === null) {
        throw new Error('stockId is required');
      }
      const params = period ? { params: { period } } : undefined;
      const res = await apiClient.get(
        `/stocks/${stockId}/13f-detail`,
        params,
      );
      return res.data as Watchlist13FDetailPayload;
    },
    enabled: stockId !== null,
    staleTime: 60_000,
  });
}

// Action vocabulary from the dashboard's ``_apply_action``:
// new / add / reduce / exit / flat. The labels and tone here are
// V1 — refine if the SME wants different copy.
export function topHolderActionLabel(action: string): string {
  switch (action) {
    case 'new':
      return 'New position';
    case 'add':
      return 'Added';
    case 'reduce':
      return 'Reduced';
    case 'exit':
      return 'Exited';
    case 'flat':
      return 'Unchanged';
    default:
      return action;
  }
}

export function topHolderActionTone(action: string): BadgeVariant {
  switch (action) {
    case 'new':
    case 'add':
      return 'success';
    case 'reduce':
    case 'exit':
      return 'danger';
    case 'flat':
    default:
      return 'secondary';
  }
}

export function caveatGroupLabel(group: string): string {
  switch (group) {
    case 'signal_quality':
      return 'Signal quality';
    case 'conviction':
      return 'Conviction';
    case 'data_coverage':
      return 'Data coverage';
    case 'timing':
      return 'Timing';
    default:
      return group.replace(/_/g, ' ');
  }
}
