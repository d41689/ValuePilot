'use client';

import Link from 'next/link';
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BriefcaseBusiness,
  CalendarRange,
  ChartNoAxesColumnIncreasing,
  CircleDollarSign,
  History,
  Info,
  Layers3,
} from 'lucide-react';

import managerHelpers from '@/lib/thirteenfManagers';
import type {
  ThirteenFManagerChange,
  ThirteenFManagerHistory,
  ThirteenFManagerHoldings,
  ThirteenFManagerPosition,
} from '@/lib/thirteenfManagers';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { OpenResearchCaseButton } from '@/components/research/OpenResearchCaseButton';

const {
  activityLabel,
  filterManagerActivity,
  formatCurrency,
  formatInteger,
  formatPercentPoints,
  sortManagerActivity,
  titleizeCode,
} = managerHelpers;

export type ManagerView = 'holdings' | 'activity' | 'buys' | 'sells' | 'history';

const VIEWS: Array<{ value: ManagerView; label: string }> = [
  { value: 'holdings', label: 'Holdings' },
  { value: 'activity', label: 'Activity' },
  { value: 'buys', label: 'Buys' },
  { value: 'sells', label: 'Sells' },
  { value: 'history', label: 'History' },
];

function formatPrice(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function actionVariant(status: string) {
  if (status === 'new_position' || status === 'increased') return 'success' as const;
  if (status === 'reduced' || status === 'exited_position') return 'danger' as const;
  if (status === 'no_prior_data' || status === 'unresolvable') return 'warning' as const;
  return 'secondary' as const;
}

function confidenceVariant(confidence: string) {
  if (confidence === 'high_confidence') return 'success' as const;
  if (confidence === 'medium_confidence') return 'secondary' as const;
  return 'warning' as const;
}

function SecurityCell({ item }: { item: Pick<ThirteenFManagerPosition, 'ticker' | 'companyName'> }) {
  return (
    <div className="min-w-44">
      {item.ticker ? (
        <Link
          href={`/stocks/${encodeURIComponent(item.ticker)}/summary`}
          className="font-semibold text-foreground hover:text-primary hover:underline"
        >
          {item.ticker}
        </Link>
      ) : (
        <span className="font-semibold">Unresolved</span>
      )}
      <div className="mt-1 max-w-64 truncate text-xs text-muted-foreground">{item.companyName}</div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string;
  value: string;
  detail?: string;
  icon: typeof CalendarRange;
}) {
  return (
    <Card className="rounded-xl shadow-none">
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
          <Icon className="h-4 w-4 text-muted-foreground" />
        </div>
        <div className="mt-2 text-xl font-semibold tabular-nums">{value}</div>
        {detail ? <div className="mt-1 text-xs text-muted-foreground">{detail}</div> : null}
      </CardContent>
    </Card>
  );
}

function HoldingsView({
  managerId,
  holdings,
  loading,
  selectedQuarter,
  activity,
}: {
  managerId: number;
  holdings: ThirteenFManagerHoldings | undefined;
  loading: boolean;
  selectedQuarter: string;
  activity: ThirteenFManagerChange[];
}) {
  const selectedActivity = activity.filter((item) => item.reportQuarter === selectedQuarter);
  const activityByStock = new Map<string, ThirteenFManagerChange>();
  for (const item of selectedActivity) {
    const key = item.stockId !== null ? `stock:${item.stockId}` : `ticker:${item.ticker}`;
    activityByStock.set(key, item);
  }

  if (loading) return <div className="p-6 text-sm text-muted-foreground">Loading reported positions…</div>;
  if (holdings?.status === 'unavailable') {
    return <div className="p-6 text-sm text-muted-foreground">{holdings.reason?.message ?? 'Holdings are unavailable.'}</div>;
  }
  if (!holdings?.commonHoldings.length) {
    return <div className="p-6 text-sm text-muted-foreground">No reported common-stock positions are available.</div>;
  }

  return (
    <>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-12" aria-label="Holding history" />
              <TableHead className="w-16">Rank</TableHead>
              <TableHead>Security</TableHead>
              <TableHead className="text-right">Portfolio</TableHead>
              <TableHead>Recent activity</TableHead>
              <TableHead className="text-right">Shares</TableHead>
              <TableHead className="text-right">Implied report price</TableHead>
              <TableHead className="text-right">Reported value</TableHead>
              <TableHead className="text-right">Latest local price</TableHead>
              <TableHead className="text-right">Since report</TableHead>
              <TableHead className="text-right">52-week range</TableHead>
              <TableHead>Research</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {holdings.commonHoldings.map((item) => {
              const key = item.stockId !== null ? `stock:${item.stockId}` : `ticker:${item.ticker}`;
              const recent = activityByStock.get(key);
              const move = item.marketContext?.changeSinceReportPct;
              return (
                <TableRow key={item.id}>
                  <TableCell>
                    {item.stockId !== null ? (
                      <Button asChild variant="ghost" size="icon" className="h-8 w-8">
                        <Link
                          href={`/13f/managers/${managerId}/stocks/${item.stockId}`}
                          aria-label={`View ${item.ticker ?? item.companyName} holding history`}
                        >
                          <History className="h-4 w-4" />
                        </Link>
                      </Button>
                    ) : null}
                  </TableCell>
                  <TableCell className="font-mono text-xs">#{item.positionRank ?? '—'}</TableCell>
                  <TableCell><SecurityCell item={item} /></TableCell>
                  <TableCell className="text-right font-mono text-xs font-semibold">
                    {formatPercentPoints(item.weightPct)}
                  </TableCell>
                  <TableCell>
                    {recent ? (
                      <Badge variant={actionVariant(recent.changeStatus)}>{activityLabel(recent)}</Badge>
                    ) : (
                      <span className="text-xs text-muted-foreground">No comparable move</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {formatInteger(item.shares)}
                    {item.shareType ? <div className="mt-1 text-muted-foreground">{item.shareType}</div> : null}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {formatPrice(item.impliedReportPrice)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">{formatCurrency(item.valueUsd)}</TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    <div>{formatPrice(item.marketContext?.latestPrice)}</div>
                    <div className="mt-1 text-muted-foreground">{item.marketContext?.latestPriceDate ?? 'No local quote'}</div>
                  </TableCell>
                  <TableCell
                    className={cn(
                      'text-right font-mono text-xs font-semibold',
                      typeof move === 'number' && move > 0 && 'text-emerald-700',
                      typeof move === 'number' && move < 0 && 'text-rose-700',
                    )}
                  >
                    {typeof move === 'number' ? `${move > 0 ? '+' : ''}${formatPercentPoints(move)}` : '—'}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    {item.marketContext
                      ? `${formatPrice(item.marketContext.week52Low)} – ${formatPrice(item.marketContext.week52High)}`
                      : '—'}
                  </TableCell>
                  <TableCell>
                    {item.stockId !== null ? (
                      <OpenResearchCaseButton
                        stockId={item.stockId}
                        originType="manager_holding"
                        originKey={`manager:${managerId}:holding:${item.id}`}
                        sourceVersion={`${selectedQuarter}:holding-${item.id}`}
                        sourceRef={{ holding_id: item.id, manager_id: managerId }}
                      />
                    ) : null}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <div className="border-t border-border/70 px-5 py-4 text-xs leading-5 text-muted-foreground">
        “Implied report price” is reported 13F value divided by reported shares at quarter end. It is
        not a transaction price or cost basis. Latest and 52-week values appear only when ValuePilot
        has dated local market-price rows.
      </div>

      {holdings.options.length ? (
        <div className="border-t border-border/70 p-5">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <Layers3 className="h-4 w-4" />
            Reported options — separate context
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {holdings.options.map((item) => (
              <div key={item.id} className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
                <div>
                  <span className="font-medium">{item.ticker ?? item.issuerName}</span>
                  <Badge variant="warning" className="ml-2">{item.putCall ?? 'Option'}</Badge>
                </div>
                <div className="font-mono text-xs text-muted-foreground">{formatCurrency(item.valueUsd)}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}

function ActivityView({
  history,
  loading,
  view,
}: {
  history: ThirteenFManagerHistory | undefined;
  loading: boolean;
  view: 'activity' | 'buys' | 'sells';
}) {
  const rows = filterManagerActivity(history?.activity ?? [], view);
  const grouped = new Map<string, ThirteenFManagerChange[]>();
  for (const row of rows) {
    const key = row.reportQuarter ?? 'Unknown quarter';
    grouped.set(key, [...(grouped.get(key) ?? []), row]);
  }
  for (const [quarter, quarterRows] of grouped.entries()) {
    grouped.set(quarter, sortManagerActivity(quarterRows, view));
  }

  if (loading) return <div className="p-6 text-sm text-muted-foreground">Loading multi-quarter activity…</div>;
  if (!rows.length) {
    return <div className="p-6 text-sm text-muted-foreground">No comparable {view} rows are available.</div>;
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Quarter / security</TableHead>
            <TableHead>Activity</TableHead>
            <TableHead className="text-right">Share change</TableHead>
            <TableHead className="text-right">Change to portfolio</TableHead>
            <TableHead>Evidence quality</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {[...grouped.entries()].map(([quarter, quarterRows]) => (
            <ActivityQuarterRows key={quarter} quarter={quarter} rows={quarterRows} />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function ActivityQuarterRows({ quarter, rows }: { quarter: string; rows: ThirteenFManagerChange[] }) {
  return (
    <>
      <TableRow className="bg-muted/40 hover:bg-muted/40">
        <TableCell colSpan={5} className="py-2 text-sm font-semibold">{quarter}</TableCell>
      </TableRow>
      {rows.map((item) => (
        <TableRow key={item.id}>
          <TableCell>
            <SecurityCell item={item} />
          </TableCell>
          <TableCell>
            <Badge variant={actionVariant(item.changeStatus)}>{activityLabel(item)}</Badge>
          </TableCell>
          <TableCell className="text-right font-mono text-xs">
            <div>{formatInteger(item.shareDelta === null ? null : Math.abs(item.shareDelta))}</div>
            <div className="mt-1 text-muted-foreground">
              {item.shareChangePct === null ? '—' : formatPercentPoints(Math.abs(item.shareChangePct * 100))}
            </div>
          </TableCell>
          <TableCell className="text-right font-mono text-xs font-semibold">
            {formatPercentPoints(item.portfolioImpactPct)}
          </TableCell>
          <TableCell>
            <div className="flex max-w-sm flex-wrap gap-1.5">
              <Badge variant={confidenceVariant(item.confidenceLevel)}>
                {titleizeCode(item.confidenceLevel)}
              </Badge>
              {!item.isPrimarySignalEligible ? <Badge variant="warning">Caveated evidence</Badge> : null}
              {item.caveatCodes.map((code) => (
                <Badge key={code} variant="outline">{titleizeCode(code)}</Badge>
              ))}
            </div>
          </TableCell>
        </TableRow>
      ))}
    </>
  );
}

function HistoryView({ history, loading }: { history: ThirteenFManagerHistory | undefined; loading: boolean }) {
  if (loading) return <div className="p-6 text-sm text-muted-foreground">Loading portfolio history…</div>;
  if (!history?.quarters.length) {
    return <div className="p-6 text-sm text-muted-foreground">No active filing history is available.</div>;
  }
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Period</TableHead>
            <TableHead className="text-right">Portfolio value</TableHead>
            <TableHead className="text-right">Positions</TableHead>
            <TableHead className="text-right">Top 1 / 5 / 10</TableHead>
            <TableHead>Top holdings in rank order</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {history.quarters.map((quarter) => (
            <TableRow key={quarter.quarter ?? quarter.quarterEndDate ?? 'unknown'}>
              <TableCell>
                <div className="font-semibold">{quarter.quarter ?? 'Unknown'}</div>
                <div className="mt-1 text-xs text-muted-foreground">{quarter.quarterEndDate ?? '—'}</div>
                {quarter.status !== 'available' ? (
                  <Badge className="mt-2" variant="warning">{titleizeCode(quarter.status)}</Badge>
                ) : null}
              </TableCell>
              <TableCell className="text-right font-mono text-xs font-semibold">
                {formatCurrency(quarter.reportedCommonValueUsd)}
              </TableCell>
              <TableCell className="text-right font-mono text-xs">
                {quarter.commonPositionCount ?? '—'}
              </TableCell>
              <TableCell className="text-right font-mono text-xs">
                {quarter.concentration.top1Pct === null
                  ? '—'
                  : `${formatPercentPoints(quarter.concentration.top1Pct)} / ${formatPercentPoints(quarter.concentration.top5Pct)} / ${formatPercentPoints(quarter.concentration.top10Pct)}`}
              </TableCell>
              <TableCell>
                {quarter.topHoldings.length ? (
                  <div className="flex min-w-[32rem] flex-wrap gap-1.5">
                    {quarter.topHoldings.map((item) => (
                      item.ticker ? (
                        <Button key={item.id} asChild variant="outline" size="sm" className="h-7 px-2 font-mono">
                          <Link href={`/stocks/${encodeURIComponent(item.ticker)}/summary`}>
                            {item.ticker}
                            <span className="text-muted-foreground">{formatPercentPoints(item.weightPct, 1)}</span>
                          </Link>
                        </Button>
                      ) : (
                        <Badge key={item.id} variant="outline">{item.issuerName}</Badge>
                      )
                    ))}
                  </div>
                ) : (
                  <span className="text-xs text-muted-foreground">Holdings unavailable for this filing type</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export default function ManagerResearchWorkbench({
  managerId,
  activeView,
  onViewChange,
  selectedQuarter,
  holdings,
  history,
  holdingsLoading,
  historyLoading,
}: {
  managerId: number;
  activeView: ManagerView;
  onViewChange: (view: ManagerView) => void;
  selectedQuarter: string;
  holdings: ThirteenFManagerHoldings | undefined;
  history: ThirteenFManagerHistory | undefined;
  holdingsLoading: boolean;
  historyLoading: boolean;
}) {
  const quarterHistory = history?.quarters.find((item) => item.quarter === selectedQuarter);
  const top5 = quarterHistory?.concentration.top5Pct ?? null;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <SummaryCard label="Reported period" value={selectedQuarter || '—'} icon={CalendarRange} />
        <SummaryCard
          label="Portfolio date"
          value={holdings?.quarterEndDate ?? quarterHistory?.quarterEndDate ?? '—'}
          icon={History}
        />
        <SummaryCard
          label="Common positions"
          value={String(holdings?.summary.commonPositionCount ?? quarterHistory?.commonPositionCount ?? '—')}
          icon={BriefcaseBusiness}
        />
        <SummaryCard
          label="Reported 13F value"
          value={formatCurrency(holdings?.summary.reportedCommonValueUsd ?? quarterHistory?.reportedCommonValueUsd)}
          detail="Common-stock book, not firm AUM"
          icon={CircleDollarSign}
        />
        <SummaryCard
          label="Top 5 concentration"
          value={formatPercentPoints(top5)}
          detail="Available only for complete coverage"
          icon={ChartNoAxesColumnIncreasing}
        />
      </div>

      <Card className="overflow-hidden rounded-xl">
        <CardHeader className="border-b border-border/70 bg-muted/20 p-4">
          <div className="flex flex-col gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                {activeView === 'holdings' ? <BriefcaseBusiness className="h-4 w-4" /> : null}
                {activeView === 'activity' ? <Activity className="h-4 w-4" /> : null}
                {activeView === 'buys' ? <ArrowUpRight className="h-4 w-4" /> : null}
                {activeView === 'sells' ? <ArrowDownRight className="h-4 w-4" /> : null}
                {activeView === 'history' ? <History className="h-4 w-4" /> : null}
                Manager research
              </CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                Holdings answer what is owned now; activity and history reveal changes in conviction over time.
              </p>
            </div>
            <div className="flex flex-wrap gap-2" aria-label="Manager research views">
              {VIEWS.map((view) => (
                <Button
                  key={view.value}
                  type="button"
                  size="sm"
                  variant={activeView === view.value ? 'default' : 'outline'}
                  aria-pressed={activeView === view.value}
                  onClick={() => onViewChange(view.value)}
                >
                  {view.label}
                </Button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {activeView === 'holdings' ? (
            <HoldingsView
              managerId={managerId}
              holdings={holdings}
              loading={holdingsLoading}
              selectedQuarter={selectedQuarter}
              activity={history?.activity ?? []}
            />
          ) : null}
          {activeView === 'activity' || activeView === 'buys' || activeView === 'sells' ? (
            <ActivityView history={history} loading={historyLoading} view={activeView} />
          ) : null}
          {activeView === 'history' ? <HistoryView history={history} loading={historyLoading} /> : null}
        </CardContent>
      </Card>

      <div className="flex gap-2 rounded-md border border-sky-200 bg-sky-50 px-4 py-3 text-xs leading-5 text-sky-950">
        <Info className="mt-0.5 h-4 w-4 shrink-0" />
        Sector allocation is intentionally omitted until ValuePilot has a canonical, queryable sector taxonomy.
        Issuer-name guesses would make the allocation look precise without trustworthy source data.
      </div>
    </div>
  );
}
