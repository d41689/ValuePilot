'use client';

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Info, Search } from 'lucide-react';

import apiClient from '@/lib/api/client';
import oracleLensHelpers from '@/lib/oraclesLens';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

const { cautionTone, normalizeOracleLensRows } = oracleLensHelpers;

type OracleLensPayload = {
  period: string | null;
  period_end_date: string | null;
  latest_complete_period: string | null;
  baseline_notice: string;
  coverage: {
    manager_count: number;
    holding_count: number;
    linked_holding_count: number;
    manager_signal_quality_coverage?: number;
    price_coverage_count?: number;
    value_line_coverage_count?: number;
  };
  items: unknown[];
};

function formatInteger(value: number | null | undefined) {
  if (typeof value !== 'number') {
    return '—';
  }
  return value.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

export default function OraclesLensPage() {
  const dashboardQuery = useQuery({
    queryKey: ['oracles-lens-dashboard'],
    queryFn: async () => {
      const res = await apiClient.get('/13f/oracles-lens');
      return res.data as OracleLensPayload;
    },
  });

  const payload = dashboardQuery.data;
  const rows = useMemo(() => normalizeOracleLensRows(payload?.items ?? []), [payload?.items]);
  const coverage = payload?.coverage;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase text-muted-foreground">
            13F Research Funnel
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Oracle&apos;s Lens</h1>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            Signal-ranked research candidates from reported 13F ownership behavior.
          </p>
        </div>
        <div className="rounded-md border border-border/70 bg-background px-3 py-2 text-sm">
          <div className="text-xs uppercase text-muted-foreground">Latest complete period</div>
          <div className="mt-1 font-medium">{payload?.latest_complete_period ?? '—'}</div>
        </div>
      </div>

      <div className="flex gap-3 rounded-md border border-amber-300/70 bg-amber-50 px-4 py-3 text-sm text-amber-950">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div>{payload?.baseline_notice ?? '13F filings are delayed snapshots.'}</div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <Card className="rounded-md">
          <CardContent className="p-4">
            <div className="text-xs uppercase text-muted-foreground">Selected period</div>
            <div className="mt-2 text-xl font-semibold">{payload?.period ?? '—'}</div>
          </CardContent>
        </Card>
        <Card className="rounded-md">
          <CardContent className="p-4">
            <div className="text-xs uppercase text-muted-foreground">Managers</div>
            <div className="mt-2 text-xl font-semibold">{formatInteger(coverage?.manager_count)}</div>
          </CardContent>
        </Card>
        <Card className="rounded-md">
          <CardContent className="p-4">
            <div className="text-xs uppercase text-muted-foreground">Linked holdings</div>
            <div className="mt-2 text-xl font-semibold">
              {formatInteger(coverage?.linked_holding_count)}
            </div>
          </CardContent>
        </Card>
        <Card className="rounded-md">
          <CardContent className="p-4">
            <div className="text-xs uppercase text-muted-foreground">Candidates</div>
            <div className="mt-2 text-xl font-semibold">{formatInteger(rows.length)}</div>
          </CardContent>
        </Card>
      </div>

      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Search className="h-4 w-4" />
            Signal-Ranked Candidates
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Signal Score is the primary rank. Conviction, streak, holder count, and caution
            flags are supporting context.
          </p>
        </CardHeader>
        <CardContent className="p-0">
          {dashboardQuery.isLoading ? (
            <div className="p-6 text-sm text-muted-foreground">Loading 13F signals…</div>
          ) : rows.length === 0 ? (
            <div className="flex gap-2 p-6 text-sm text-muted-foreground">
              <Info className="h-4 w-4" />
              No signal-ranked candidates are available for the selected coverage rules.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Company</TableHead>
                  <TableHead className="text-right">Signal Score</TableHead>
                  <TableHead>Why It Appears</TableHead>
                  <TableHead>Quality</TableHead>
                  <TableHead>Context</TableHead>
                  <TableHead>Caution</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.stockId}>
                    <TableCell>
                      <div className="font-semibold">{row.ticker}</div>
                      <div className="mt-1 text-xs text-muted-foreground">{row.companyName}</div>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="text-xl font-semibold tabular-nums">{row.signalScoreLabel}</div>
                      <Badge variant={row.confidenceTone} className="mt-2">
                        {row.confidence} confidence
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1.5">
                        {row.reasonChips.map((reason) => (
                          <Badge key={reason} variant="outline" className="rounded-md">
                            {reason}
                          </Badge>
                        ))}
                      </div>
                      <div className="mt-2 text-xs text-muted-foreground">
                        Manager signal coverage: {row.unknownCoverageLabel}
                      </div>
                    </TableCell>
                    <TableCell>
                      {row.quality.hasValueLineQuality ? (
                        <div className="space-y-1 text-sm">
                          <div className="tabular-nums">
                            F-Score {row.quality.piotroskiLabel} · ROTC{' '}
                            {row.quality.returnOnCapitalLabel}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            NPM {row.quality.netMarginLabel} · Debt/Cap{' '}
                            {row.quality.debtToCapitalLabel}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            Owner yield {row.quality.ownerEarningsYieldLabel}
                          </div>
                        </div>
                      ) : (
                        <div className="text-sm text-muted-foreground">No quality facts</div>
                      )}
                      <div className="mt-2">
                        <Badge variant="outline" className="rounded-md">
                          {row.quality.qualityCoverageLabel}
                        </Badge>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="text-sm">{row.convictionLabel} conviction</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {row.holdingStreakLabel} · {row.rawHoldersLabel} holders
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">{row.addReduceLabel}</div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1.5">
                        {row.cautionFlags.length ? (
                          row.cautionFlags.map((flag) => (
                            <Badge key={flag.key} variant={cautionTone(flag)} className="rounded-md">
                              {flag.label ?? flag.key}
                            </Badge>
                          ))
                        ) : (
                          <Badge variant="secondary" className="rounded-md">
                            No primary caution
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
