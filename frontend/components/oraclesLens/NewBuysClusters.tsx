'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Network, PanelRightOpen } from 'lucide-react';

import apiClient from '@/lib/api/client';
import managerHelpers from '@/lib/thirteenfManagers';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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

const {
  formatCurrency,
  formatPercentPoints,
  normalizeNewBuyClusters,
  titleizeCode,
} = managerHelpers;

type Props = {
  selectedQuarter?: string | null;
  onOpenStock: (stockId: number) => void;
};

export function NewBuysClusters({ selectedQuarter, onOpenStock }: Props) {
  const [quarter, setQuarter] = useState(selectedQuarter ?? '');
  const [managerScope, setManagerScope] = useState('value');
  useEffect(() => {
    if (selectedQuarter) setQuarter(selectedQuarter);
  }, [selectedQuarter]);

  const query = useQuery({
    queryKey: ['13f-new-buy-clusters', quarter, managerScope],
    queryFn: async () => {
      const params = new URLSearchParams({
        min_cluster_size: '2',
        superinvestors_only: 'true',
        manager_scope: managerScope,
      });
      if (quarter) params.set('quarter', quarter);
      const response = await apiClient.get(`/13f/new-buys/clusters?${params.toString()}`);
      return normalizeNewBuyClusters(response.data);
    },
  });
  const payload = query.data;
  const periods = useMemo(
    () => Array.from(new Set([...(payload?.periods ?? []), ...(quarter ? [quarter] : [])])),
    [payload?.periods, quarter],
  );

  return (
    <Card className="rounded-md">
      <CardHeader className="pb-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Network className="h-4 w-4" />
              New-position clusters
            </CardTitle>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
              Independent value managers opening the same position in one quarter. Ranking counts
              only eligible, caveat-free evidence; excluded disclosures remain visible.
            </p>
          </div>
          <div className="grid min-w-64 grid-cols-2 gap-2">
            <Select value={managerScope} onValueChange={setManagerScope}>
              <SelectTrigger aria-label="Cluster manager scope">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="value">Value DNA</SelectItem>
                <SelectItem value="value_plus_activist">+ Activists</SelectItem>
                <SelectItem value="all">All tracked</SelectItem>
              </SelectContent>
            </Select>
            {periods.length ? (
              <Select value={quarter || payload?.quarter || ''} onValueChange={setQuarter}>
                <SelectTrigger aria-label="Cluster quarter">
                  <SelectValue placeholder="Latest" />
                </SelectTrigger>
                <SelectContent>
                  {periods.map((period) => (
                    <SelectItem key={period} value={period}>{period}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : null}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {payload?.filingWindowOpen ? (
          <div className="mx-4 mb-4 flex gap-2 rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-xs text-amber-950">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            Filing window open through {payload.officialFilingDeadline ?? 'the official deadline'}.
            Coverage is {payload.coverage.reportedManagerCount} of {payload.coverage.trackedManagerCount}
            tracked managers and may still change.
          </div>
        ) : null}
        {query.isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Finding independent new-buy clusters…</div>
        ) : query.isError ? (
          <div className="p-6 text-sm text-rose-700">New-position clusters could not be loaded.</div>
        ) : !payload?.items.length ? (
          <div className="p-6 text-sm text-muted-foreground">
            No two-manager clusters meet the current value-investor scope for this quarter.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Company</TableHead>
                  <TableHead>Independent buyers</TableHead>
                  <TableHead>Quality-weighted score</TableHead>
                  <TableHead>Buyer evidence</TableHead>
                  <TableHead className="w-12" aria-label="Open research drawer" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {payload.items.map((cluster) => (
                  <TableRow key={cluster.stock.id}>
                    <TableCell>
                      <div className="font-medium">{cluster.stock.ticker}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {cluster.stock.companyName}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="text-lg font-semibold tabular-nums">{cluster.clusterSize}</div>
                      {cluster.hasExcludedEvidence ? (
                        <div className="mt-1 text-xs text-amber-700">
                          {cluster.visibleBuyerCount - cluster.clusterSize} additional caveated
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <Badge variant="success">
                        {cluster.qualityWeightedClusterScore.toFixed(2)}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex max-w-2xl flex-wrap gap-2">
                        {cluster.buyers.map((buyer) => (
                          <div
                            key={`${cluster.stock.id}-${buyer.manager.id}`}
                            className="rounded-md border border-border/70 px-2.5 py-2 text-xs"
                          >
                            <div className="flex items-center gap-1.5">
                              <Link
                                href={`/13f/managers/${buyer.manager.id}`}
                                className="font-medium hover:underline"
                              >
                                {buyer.manager.displayName}
                              </Link>
                              <Badge variant={buyer.includedInScore ? 'outline' : 'warning'}>
                                {buyer.includedInScore ? titleizeCode(buyer.manager.stylePrimary) : 'Excluded'}
                              </Badge>
                            </div>
                            <div className="mt-1 text-muted-foreground">
                              {formatPercentPoints(buyer.portfolioWeightPct)} · {formatCurrency(buyer.currentValueUsd)}
                            </div>
                            {!buyer.includedInScore ? (
                              <div className="mt-1 text-amber-700">
                                {buyer.scoreExclusionReasons.map(titleizeCode).join(' · ')}
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`Open ${cluster.stock.ticker} research drawer`}
                        onClick={() => onOpenStock(cluster.stock.id)}
                      >
                        <PanelRightOpen className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
