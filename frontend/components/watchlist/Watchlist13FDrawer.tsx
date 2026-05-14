/**
 * MVP7-05: per-row 13F drawer for /watchlist.
 *
 * Mounted in /watchlist/page.tsx with a ``selectedStockId`` state.
 * Fetches the detail payload via ``useWatchlistStock13FDetail`` when
 * opened. Renders three sections inside ``DrawerShell``:
 *
 *   1. Header recap — the four column chips (conviction percentile,
 *      Δ holders, distinctiveness, caveat severity) so the operator
 *      keeps the row context.
 *   2. Top Holders — up to 3 cards: manager name + manager_type
 *      badge + position_weight + action chip + magnitude
 *      (share_delta_pct) + holding_streak + filing link.
 *   3. Caveats — structured list per caveat flag with severity + group.
 *
 * Reuses oraclesLens.js normalizers per Pre-MVP7-01.
 */
'use client';

import Link from 'next/link';
import { AlertTriangle, Loader2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { DrawerShell } from '@/components/admin13f/Admin13FPrimitives';
import {
  caveatGroupLabel,
  caveatSeverityLabel,
  caveatSeverityTone,
  convictionTone,
  deltaHoldersTone,
  distinctivenessLabel,
  distinctivenessTone,
  formatConvictionLabel,
  formatDeltaHolders,
  topHolderActionLabel,
  topHolderActionTone,
  unavailableTooltip,
  useWatchlistStock13FDetail,
  type Watchlist13FAvailableDetail,
  type Watchlist13FCaveatFlag,
  type Watchlist13FTopHolder,
} from '@/lib/watchlist13f';
import oraclesLens from '@/lib/oraclesLens';

const { humanizeTier, formatPercent } = oraclesLens;

// ``humanizeTier`` titleizes underscore-separated codes. ``titleizeCode`` is
// not exported from ``oraclesLens.js`` so we reuse ``humanizeTier`` for
// the manager_type chip ("long_term_fundamental" → "Long term fundamental").
const titleizeCode = humanizeTier;

interface Watchlist13FDrawerProps {
  stockId: number | null;
  onClose: () => void;
}

export function Watchlist13FDrawer({ stockId, onClose }: Watchlist13FDrawerProps) {
  const query = useWatchlistStock13FDetail(stockId);

  if (stockId === null) return null;

  const payload = query.data;
  const detail = payload?.detail;

  const titleTicker =
    detail && 'ticker' in detail && detail.ticker
      ? detail.ticker
      : `Stock ${stockId}`;
  const companyName =
    detail && 'company_name' in detail && detail.company_name
      ? detail.company_name
      : undefined;

  return (
    <DrawerShell
      title={titleTicker}
      description={
        <span>
          {companyName ? <span className="font-medium">{companyName}</span> : null}
          {companyName && payload?.period ? <span> · </span> : null}
          {payload?.period ? (
            <span>
              13F snapshot for{' '}
              <span className="font-mono">{payload.period}</span>
              {payload.period_filing_deadline ? (
                <span className="text-muted-foreground/80">
                  {' '}
                  (as of {payload.period_filing_deadline})
                </span>
              ) : null}
            </span>
          ) : null}
        </span>
      }
      closeLabel="Close 13F detail"
      labelledBy={`watchlist-13f-drawer-title-${stockId}`}
      maxWidthClassName="max-w-[560px]"
      onClose={onClose}
    >
      {query.isPending ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading 13F detail...
        </div>
      ) : query.isError ? (
        <div
          role="alert"
          className="rounded-md border border-rose-300/70 bg-rose-50 px-3 py-2 text-sm text-rose-900"
        >
          <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
          Failed to load 13F detail. Try closing and reopening.
        </div>
      ) : detail?.available === false ? (
        <UnavailableBody
          reason={detail.unavailable_reason}
          period={payload?.period ?? null}
        />
      ) : detail?.available === true ? (
        <AvailableBody detail={detail} universeSize={payload?.universe_size ?? 0} />
      ) : null}
    </DrawerShell>
  );
}

function UnavailableBody({
  reason,
  period,
}: {
  reason: 'no_holders' | 'below_min_holders' | 'no_qualifying_period';
  period: string | null;
}) {
  return (
    <div className="rounded-md border border-border/70 bg-muted/30 px-3 py-3 text-sm text-muted-foreground">
      {unavailableTooltip(reason, period)}
    </div>
  );
}

function AvailableBody({
  detail,
  universeSize,
}: {
  detail: Watchlist13FAvailableDetail;
  universeSize: number;
}) {
  return (
    <>
      <section className="space-y-2">
        <div className="text-xs font-semibold uppercase text-muted-foreground">
          Summary
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant={convictionTone(detail.conviction_percentile)}>
            {formatConvictionLabel(detail.conviction_percentile)}
          </Badge>
          <Badge variant={deltaHoldersTone(detail.delta_holders)}>
            {formatDeltaHolders(detail.delta_holders)} holders
          </Badge>
          <Badge variant={distinctivenessTone(detail.distinctiveness_tier)}>
            {distinctivenessLabel(detail.distinctiveness_tier)}
          </Badge>
          <Badge variant={caveatSeverityTone(detail.caveat_severity)}>
            {caveatSeverityLabel(detail.caveat_severity)}
          </Badge>
        </div>
        <div className="text-xs text-muted-foreground">
          {detail.consensus_count} qualifying holders · ranked vs {universeSize}{' '}
          stocks
        </div>
        {/* MVP8-03B B4: portfolio-weight context for the Δ Holders chip
           — surfaced inline in the drawer so users see depth alongside
           the count. Mean position weight is more interpretable than
           the raw sum (it answers "did adders hold this stock
           meaningfully in their portfolios?"). */}
        <div className="text-xs text-muted-foreground">
          {detail.adders_count} adders · mean position weight{' '}
          {formatPercent(
            detail.adders_count > 0
              ? detail.adders_portfolio_weight_sum / detail.adders_count
              : 0,
            1,
          )}{' '}
          · {detail.reducers_count} reducers · mean position weight{' '}
          {formatPercent(
            detail.reducers_count > 0
              ? detail.reducers_portfolio_weight_sum / detail.reducers_count
              : 0,
            1,
          )}
        </div>
      </section>

      <section className="space-y-3">
        <div className="text-xs font-semibold uppercase text-muted-foreground">
          Top Holders
        </div>
        {detail.top_holders.length === 0 ? (
          <div className="text-sm text-muted-foreground">
            No top holders captured for this period.
          </div>
        ) : (
          <div className="space-y-2">
            {detail.top_holders.map((holder) => (
              <TopHolderCard key={holder.manager_id} holder={holder} />
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <div className="text-xs font-semibold uppercase text-muted-foreground">
          Caveats
        </div>
        {detail.caveat_flags.length === 0 ? (
          <div className="text-sm text-muted-foreground">
            No caveat flags on this signal.
          </div>
        ) : (
          <div className="space-y-2">
            {detail.caveat_flags.map((flag) => (
              <CaveatFlagCard key={flag.key} flag={flag} />
            ))}
          </div>
        )}
      </section>
    </>
  );
}

function TopHolderCard({ holder }: { holder: Watchlist13FTopHolder }) {
  const showDeltaPct =
    (holder.action === 'add' || holder.action === 'reduce') &&
    holder.share_delta_pct !== null;
  return (
    <div className="rounded-md border border-border/70 p-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <Link
            href={`/admin/13f/managers/${holder.manager_id}`}
            className="font-medium hover:underline"
          >
            {holder.manager_name || `Manager #${holder.manager_id}`}
          </Link>
          <div className="mt-1 flex flex-wrap gap-2 text-xs">
            {/* MVP8-03B B1: when admin and derived manager_type diverge,
                surface both so reviewers see what admin curated vs what
                behavior derivation inferred. Equal values render once. */}
            {holder.manager_type_admin_classified &&
            holder.manager_type_admin_classified !== holder.manager_type ? (
              <>
                <Badge
                  variant="outline"
                  title="Behavior-derived manager type (overrides admin classification)."
                >
                  Derived: {titleizeCode(holder.manager_type)}
                </Badge>
                <Badge
                  variant="outline"
                  title="Admin-classified manager type from the curated InstitutionManager record."
                  className="border-dashed text-muted-foreground"
                >
                  Admin: {titleizeCode(holder.manager_type_admin_classified)}
                </Badge>
              </>
            ) : (
              <Badge variant="outline">{titleizeCode(holder.manager_type)}</Badge>
            )}
            <Badge variant={topHolderActionTone(holder.action)}>
              {topHolderActionLabel(holder.action)}
              {showDeltaPct ? (
                <span className="ml-1 font-mono">
                  {' '}
                  {(holder.share_delta_pct as number) > 0 ? '+' : ''}
                  {formatPercent(holder.share_delta_pct, 0)}
                </span>
              ) : null}
            </Badge>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="font-semibold">
            {formatPercent(holder.position_weight, 1)}
          </div>
          {/* PRD frontend terminology: position_weight is the holding's
              weight within the filer's reported 13F common-stock portfolio
              (denominator excludes non-common holdings). Reviewer SME +
              PO flagged "of portfolio" as misleading (reads as total AUM
              weight). */}
          <div className="text-xs text-muted-foreground">13F common weight</div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted-foreground">
        <span>Held {holder.holding_streak_quarters}q</span>
        {holder.position_rank ? (
          <span>Rank #{holder.position_rank} in fund</span>
        ) : null}
        {holder.filing_date ? <span>{holder.filing_date}</span> : null}
        {holder.accession_no ? (
          // MVP7-06 review-fix: the original Link pointed at a generic
          // EDGAR browse page with empty CIK, which is misleading
          // (looks clickable, lands on an unhelpful search page). The
          // proper accession-to-filing URL requires CIK
          // (https://www.sec.gov/Archives/edgar/data/{CIK}/{accession-no-dashes}/),
          // which is not currently in the top_holders payload. Queued
          // for MVP8 backlog: thread ``cik`` through
          // ``_stock_payload.top_holders`` → ``StockDetailTopHolder`` →
          // this Link. For now, render as plain text with the accession
          // in a title tooltip so operators can copy-paste into EDGAR.
          <span
            className="font-mono"
            title={`EDGAR accession ${holder.accession_no}`}
          >
            {holder.accession_no}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function CaveatFlagCard({ flag }: { flag: Watchlist13FCaveatFlag }) {
  const tone = flag.severity === 'warning' ? 'warning' : 'secondary';
  return (
    <div className="rounded-md border border-border/70 p-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {flag.severity === 'warning' ? (
              <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" aria-hidden="true" />
            ) : null}
            <span className="font-medium">{flag.label}</span>
          </div>
          <div className="mt-1 font-mono text-xs text-muted-foreground">
            {flag.key}
          </div>
        </div>
        <Badge variant={tone}>{caveatGroupLabel(flag.group)}</Badge>
      </div>
    </div>
  );
}
