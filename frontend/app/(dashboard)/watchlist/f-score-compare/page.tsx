'use client';

import { Suspense, useMemo } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, BarChart3 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import apiClient from '@/lib/api/client';
import {
  OVERVIEW_WATCHLIST_ID,
  formatOverviewOptionLabel,
  formatWatchlistOptionLabel,
  isOverviewWatchlistId,
} from '@/lib/watchlistState';
import { normalizeFScoreComparePayload } from '@/lib/watchlistFScoreCompare';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

type StockPool = {
  id: number;
  name: string;
  description?: string | null;
  member_count?: number;
};

function endpointForWatchlist(value: string) {
  return isOverviewWatchlistId(value)
    ? '/stock_pools/overview/f-score-compare'
    : `/stock_pools/${value}/f-score-compare`;
}

function scoreCellClassName(tone: string) {
  if (tone === 'strong') {
    return 'bg-emerald-500/10 text-emerald-700';
  }
  if (tone === 'mixed') {
    return 'bg-amber-500/10 text-amber-700';
  }
  if (tone === 'weak') {
    return 'bg-rose-500/10 text-rose-700';
  }
  return 'bg-muted/40 text-muted-foreground';
}

export default function WatchlistFScoreComparePage() {
  return (
    <Suspense fallback={<div className="py-12 text-sm text-muted-foreground">Loading F-Score comparison...</div>}>
      <WatchlistFScoreCompareContent />
    </Suspense>
  );
}

function WatchlistFScoreCompareContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const selectedWatchlistId = searchParams?.get('watchlistId') || OVERVIEW_WATCHLIST_ID;

  const poolsQuery = useQuery({
    queryKey: ['watchlist-pools'],
    queryFn: async () => {
      const res = await apiClient.get('/stock_pools');
      return res.data as StockPool[];
    },
  });

  const compareQuery = useQuery({
    queryKey: ['watchlist-f-score-compare', selectedWatchlistId],
    queryFn: async () => {
      const res = await apiClient.get(endpointForWatchlist(selectedWatchlistId));
      return normalizeFScoreComparePayload(res.data);
    },
  });

  const pools = useMemo(() => poolsQuery.data ?? [], [poolsQuery.data]);
  const model = compareQuery.data;
  const overviewCount = isOverviewWatchlistId(selectedWatchlistId)
    ? model?.rows.length ?? null
    : null;
  const selectedPoolName = model?.watchlist.name ?? 'Watchlist';

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Button asChild variant="ghost" className="-ml-3 mb-2">
            <Link href="/watchlist">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Watchlist
            </Link>
          </Button>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/10 text-primary">
              <BarChart3 className="h-5 w-5" />
            </div>
            <div>
              <h1 className="font-display text-3xl font-semibold tracking-tight">
                F-Score Compare
              </h1>
              <p className="text-sm text-muted-foreground">
                Compare Piotroski strength across watchlist holdings by fiscal year.
              </p>
            </div>
          </div>
        </div>
      </header>

      <Card className="border-border/60 bg-card/85">
        <CardHeader className="gap-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div className="flex max-w-sm flex-col gap-1">
              <span className="text-xs font-semibold uppercase text-muted-foreground">
                Watchlist
              </span>
              <Select
                value={selectedWatchlistId}
                onValueChange={(nextValue) => {
                  router.replace(`/watchlist/f-score-compare?watchlistId=${encodeURIComponent(nextValue)}`);
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={OVERVIEW_WATCHLIST_ID}>
                    {formatOverviewOptionLabel(overviewCount)}
                  </SelectItem>
                  {pools.map((pool) => (
                    <SelectItem key={pool.id} value={String(pool.id)}>
                      {formatWatchlistOptionLabel(pool)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="success">7-9 strong</Badge>
              <Badge variant="warning">4-6 mixed</Badge>
              <Badge variant="danger">0-3 weak</Badge>
              <Badge variant="outline">Est = estimate</Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {compareQuery.isLoading && (
            <div className="py-12 text-sm text-muted-foreground">Loading F-Score comparison...</div>
          )}

          {!compareQuery.isLoading && model && model.rows.length === 0 && (
            <div className="py-12 text-sm text-muted-foreground">
              No stocks in {selectedPoolName}.
            </div>
          )}

          {!compareQuery.isLoading && model && model.rows.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-border/60 bg-background/70">
              <Table className="min-w-[920px]">
                <TableHeader>
                  <TableRow>
                    <TableHead className="sticky left-0 z-10 w-36 bg-background/95">Ticker</TableHead>
                    <TableHead className="sticky left-36 z-10 min-w-64 bg-background/95">
                      Company
                    </TableHead>
                    {model.years.map((year) => (
                      <TableHead key={year} className="text-center">
                        {year}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {model.rows.map((row) => (
                    <TableRow key={row.stockId ?? row.ticker}>
                      <TableCell className="sticky left-0 z-10 bg-background/95 font-semibold">
                        <Link
                          href={`/stocks/${encodeURIComponent(row.ticker)}/summary`}
                          className="text-primary underline-offset-4 hover:underline"
                        >
                          {row.ticker}
                        </Link>
                      </TableCell>
                      <TableCell className="sticky left-36 z-10 bg-background/95 text-muted-foreground">
                        {row.companyName}
                      </TableCell>
                      {row.scores.map((cell) => (
                        <TableCell key={`${row.stockId}-${cell.fiscalYear}`} className="text-center">
                          <div
                            className={`inline-flex min-w-12 items-center justify-center gap-1 rounded-md px-2.5 py-1.5 text-sm font-semibold ${scoreCellClassName(cell.tone)}`}
                          >
                            <span>{cell.displayScore}</span>
                            {cell.factNature === 'estimate' && (
                              <span className="text-[10px] uppercase tracking-normal opacity-80">
                                Est
                              </span>
                            )}
                          </div>
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
