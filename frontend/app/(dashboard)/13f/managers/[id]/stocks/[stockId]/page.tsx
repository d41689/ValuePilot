'use client';

import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { AlertTriangle, ArrowLeft, History, TrendingUp } from 'lucide-react';

import apiClient from '@/lib/api/client';
import managerHelpers from '@/lib/thirteenfManagers';
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

const {
  activityLabel,
  formatCurrency,
  formatInteger,
  formatPercentPoints,
  normalizeManagerPositionHistory,
  titleizeCode,
} = managerHelpers;

function formatPrice(value: number | null) {
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
  return 'secondary' as const;
}

export default function ManagerPositionHistoryPage() {
  const params = useParams();
  const rawManagerId = Array.isArray(params?.id) ? params.id[0] : params?.id;
  const rawStockId = Array.isArray(params?.stockId) ? params.stockId[0] : params?.stockId;
  const managerId = Number(rawManagerId);
  const stockId = Number(rawStockId);
  const historyQuery = useQuery({
    queryKey: ['13f-manager-position-history', managerId, stockId],
    enabled: Number.isFinite(managerId) && Number.isFinite(stockId),
    queryFn: async () => {
      const response = await apiClient.get(
        `/13f/managers/${managerId}/stocks/${stockId}/history`,
      );
      return normalizeManagerPositionHistory(response.data);
    },
  });
  const history = historyQuery.data;
  const latest = history?.items[0] ?? null;

  if (!Number.isFinite(managerId) || !Number.isFinite(stockId)) {
    return <div className="text-sm text-rose-700">Invalid manager or stock identifier.</div>;
  }

  return (
    <div className="space-y-5">
      <Button asChild variant="ghost" size="sm" className="-ml-2">
        <Link href={`/13f/managers/${managerId}`}>
          <ArrowLeft className="h-4 w-4" />
          Back to manager holdings
        </Link>
      </Button>

      {historyQuery.isLoading ? (
        <div className="text-sm text-muted-foreground">Loading holding history…</div>
      ) : historyQuery.isError || !history ? (
        <div className="rounded-md border border-rose-300/70 bg-rose-50 p-4 text-sm text-rose-800">
          Holding history could not be loaded.
        </div>
      ) : (
        <>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Manager × security history
            </div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">
              {history.stock.ticker ?? history.stock.companyName}
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">{history.stock.companyName}</p>
            <p className="mt-1 text-sm font-medium">{history.manager.displayName}</p>
          </div>

          <div className="flex gap-3 rounded-md border border-amber-300/70 bg-amber-50 px-4 py-3 text-sm text-amber-950">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              This timeline compares quarter-end 13F snapshots. The implied report price is a
              valuation ratio, not a trade price or cost basis; missing quarters can reflect filing
              coverage or identity limitations.
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Card className="rounded-xl shadow-none">
              <CardContent className="p-4">
                <div className="text-xs font-semibold uppercase text-muted-foreground">Latest period</div>
                <div className="mt-2 text-xl font-semibold">{latest?.quarter ?? '—'}</div>
              </CardContent>
            </Card>
            <Card className="rounded-xl shadow-none">
              <CardContent className="p-4">
                <div className="text-xs font-semibold uppercase text-muted-foreground">Latest weight</div>
                <div className="mt-2 text-xl font-semibold tabular-nums">
                  {formatPercentPoints(latest?.portfolioWeightPct)}
                </div>
              </CardContent>
            </Card>
            <Card className="rounded-xl shadow-none">
              <CardContent className="p-4">
                <div className="text-xs font-semibold uppercase text-muted-foreground">Observed periods</div>
                <div className="mt-2 text-xl font-semibold tabular-nums">{history.items.length}</div>
              </CardContent>
            </Card>
          </div>

          <Card className="overflow-hidden rounded-xl">
            <CardHeader className="border-b border-border/70 bg-muted/20 p-4">
              <CardTitle className="flex items-center gap-2 text-base">
                <History className="h-4 w-4" />
                Holding and activity timeline
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                Use share count to distinguish an actual position change from a weight change caused by price movement.
              </p>
            </CardHeader>
            <CardContent className="p-0">
              {history.status === 'unavailable' || !history.items.length ? (
                <div className="p-6 text-sm text-muted-foreground">
                  {history.reason?.message ?? 'No active holding history is available.'}
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Period</TableHead>
                        <TableHead className="text-right">Shares</TableHead>
                        <TableHead className="text-right">Portfolio</TableHead>
                        <TableHead>Activity</TableHead>
                        <TableHead className="text-right">Change to portfolio</TableHead>
                        <TableHead className="text-right">Reported value</TableHead>
                        <TableHead className="text-right">Implied report price</TableHead>
                        <TableHead>Data notes</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {history.items.map((item) => (
                        <TableRow key={item.quarter ?? item.quarterEndDate ?? 'unknown'}>
                          <TableCell>
                            <div className="font-semibold">{item.quarter ?? '—'}</div>
                            <div className="mt-1 text-xs text-muted-foreground">{item.quarterEndDate ?? '—'}</div>
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs">{formatInteger(item.shares)}</TableCell>
                          <TableCell className="text-right font-mono text-xs font-semibold">
                            {formatPercentPoints(item.portfolioWeightPct)}
                          </TableCell>
                          <TableCell>
                            {item.activity ? (
                              <Badge variant={actionVariant(item.activity.changeStatus)}>
                                {activityLabel(item.activity)}
                              </Badge>
                            ) : (
                              <span className="text-xs text-muted-foreground">No share change</span>
                            )}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs">
                            {formatPercentPoints(item.activity?.portfolioImpactPct)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs">
                            {formatCurrency(item.reportedValueUsd)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs">
                            {formatPrice(item.impliedReportPrice)}
                          </TableCell>
                          <TableCell>
                            <div className="flex max-w-xs flex-wrap gap-1.5">
                              {item.caveats.map((caveat) => (
                                <Badge key={caveat.code} variant="warning">{titleizeCode(caveat.code)}</Badge>
                              ))}
                              {item.activity?.caveatCodes.map((code) => (
                                <Badge key={code} variant="outline">{titleizeCode(code)}</Badge>
                              ))}
                              {!item.caveats.length && !item.activity?.caveatCodes.length ? (
                                <Badge variant="secondary">Comparable</Badge>
                              ) : null}
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>

          {history.stock.ticker ? (
            <div className="flex justify-end">
              <Button asChild variant="outline" size="sm">
                <Link href={`/stocks/${encodeURIComponent(history.stock.ticker)}/summary`}>
                  Open stock research
                  <TrendingUp className="h-4 w-4" />
                </Link>
              </Button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
