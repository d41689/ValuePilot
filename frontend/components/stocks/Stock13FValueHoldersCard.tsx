'use client';

import { useMemo, useState, type ComponentProps } from 'react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { AlertTriangle, Landmark, TrendingDown, TrendingUp } from 'lucide-react';

import apiClient from '@/lib/api/client';
import managerHelpers from '@/lib/thirteenfManagers';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

const { actionLabel, formatCurrency, formatInteger, formatPercentPoints, titleizeCode } = managerHelpers;

type BadgeVariant = ComponentProps<typeof Badge>['variant'];

type StockHolderManager = {
  id: number;
  display_name?: string | null;
  canonical_name?: string | null;
  style_primary?: string | null;
  historical_turnover?: string | null;
};

type StockHolder = {
  holding_id: number;
  constituent_row_count?: number;
  manager: StockHolderManager;
  portfolio_weight_pct: number | null;
  value_usd: number | null;
};

type StockHolderChange = {
  manager: StockHolderManager;
  change_status: string;
};

type StockHolderCaveat = { code: string; message?: string };

type StockHoldersPayload = {
  status: string;
  as_of_quarter?: string | null;
  direct_holder_count?: number;
  value_manager_direct_count?: number;
  top_holders?: StockHolder[];
  recent_changes?: StockHolderChange[];
  data_caveats?: StockHolderCaveat[];
  reason?: { message?: string } | null;
};

function actionTone(action: string): BadgeVariant {
  if (action === 'new_position' || action === 'increased') return 'success';
  if (action === 'reduced' || action === 'exited_position') return 'danger';
  return 'secondary';
}

export function Stock13FValueHoldersCard({ stockId }: { stockId: number }) {
  const [managerScope, setManagerScope] = useState('value');
  const holdersQuery = useQuery({
    queryKey: ['stock-value-13f-holders', stockId, managerScope],
    queryFn: async () => {
      const response = await apiClient.get(
        `/13f/stocks/${stockId}/holders?manager_scope=${managerScope}&limit=8`,
      );
      return response.data as StockHoldersPayload;
    },
  });
  const data = holdersQuery.data;
  const changesByManager = useMemo(() => {
    const result = new Map<number, StockHolderChange>();
    for (const change of Array.isArray(data?.recent_changes) ? data.recent_changes : []) {
      if (typeof change?.manager?.id === 'number') result.set(change.manager.id, change);
    }
    return result;
  }, [data?.recent_changes]);

  return (
    <Card className="rounded-md">
      <CardHeader className="pb-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Landmark className="h-4 w-4" />
              Value Investor 13F
            </CardTitle>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
              Who among reviewed value-oriented managers reported this stock, how important it was
              in their 13F common-stock book, and whether comparable shares changed.
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Button
              type="button"
              size="sm"
              variant={managerScope === 'value' ? 'default' : 'outline'}
              onClick={() => setManagerScope('value')}
            >
              Value DNA
            </Button>
            <Button
              type="button"
              size="sm"
              variant={managerScope === 'value_plus_activist' ? 'default' : 'outline'}
              onClick={() => setManagerScope('value_plus_activist')}
            >
              + Activists
            </Button>
            <Button
              type="button"
              size="sm"
              variant={managerScope === 'all' ? 'default' : 'outline'}
              onClick={() => setManagerScope('all')}
            >
              All tracked
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2 rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <div>
            Quarter-end snapshot, filed up to 45 days later. It is not a current holding, transaction
            price, cost basis, or complete portfolio. The default excludes growth/long-short, macro,
            quant and passive-style noise using reviewed manager taxonomy.
          </div>
        </div>

        {holdersQuery.isLoading ? (
          <div className="text-sm text-muted-foreground">Loading 13F holder context…</div>
        ) : holdersQuery.isError ? (
          <div className="text-sm text-rose-700">13F holder context could not be loaded.</div>
        ) : data?.status === 'unavailable' ? (
          <div className="text-sm text-muted-foreground">
            {data?.reason?.message ?? 'No active 13F holders are available for this stock.'}
          </div>
        ) : (
          <>
            <div className="grid gap-2 sm:grid-cols-3">
              <div className="rounded-md border border-border/70 px-3 py-2">
                <div className="text-xs uppercase text-muted-foreground">As of</div>
                <div className="mt-1 font-semibold">{data?.as_of_quarter ?? '—'}</div>
              </div>
              <div className="rounded-md border border-border/70 px-3 py-2">
                <div className="text-xs uppercase text-muted-foreground">Managers in scope</div>
                <div className="mt-1 font-semibold tabular-nums">
                  {formatInteger(data?.direct_holder_count)}
                </div>
              </div>
              <div className="rounded-md border border-border/70 px-3 py-2">
                <div className="text-xs uppercase text-muted-foreground">Strict value managers</div>
                <div className="mt-1 font-semibold tabular-nums">
                  {formatInteger(data?.value_manager_direct_count)}
                </div>
              </div>
            </div>

            <div className="space-y-2">
              {(Array.isArray(data?.top_holders) ? data.top_holders : []).map((holder) => {
                const manager = holder?.manager ?? {};
                const change = changesByManager.get(manager.id);
                return (
                  <div
                    key={`${manager.id}:${holder.holding_id}`}
                    className="flex flex-col gap-3 rounded-md border border-border/70 px-3 py-3 md:flex-row md:items-center md:justify-between"
                  >
                    <div className="min-w-0">
                      <Link
                        href={`/13f/managers/${manager.id}`}
                        className="font-medium hover:underline"
                      >
                        {manager.display_name ?? manager.canonical_name ?? `Manager #${manager.id}`}
                      </Link>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        <Badge variant="outline">{titleizeCode(manager.style_primary)}</Badge>
                        {manager.historical_turnover ? (
                          <Badge variant="secondary">
                            {titleizeCode(manager.historical_turnover)} turnover
                          </Badge>
                        ) : null}
                        {(holder.constituent_row_count ?? 1) > 1 ? (
                          <Badge variant="outline">{holder.constituent_row_count} rows combined</Badge>
                        ) : null}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-4 text-sm md:justify-end">
                      <div className="text-right">
                        <div className="text-xs uppercase text-muted-foreground">13F common weight</div>
                        <div className="mt-1 font-mono font-semibold">
                          {formatPercentPoints(holder.portfolio_weight_pct)}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-xs uppercase text-muted-foreground">Reported value</div>
                        <div className="mt-1 font-mono">{formatCurrency(holder.value_usd)}</div>
                      </div>
                      {change ? (
                        <Badge variant={actionTone(change.change_status)}>
                          {change.change_status === 'reduced' || change.change_status === 'exited_position' ? (
                            <TrendingDown className="h-3.5 w-3.5" />
                          ) : (
                            <TrendingUp className="h-3.5 w-3.5" />
                          )}
                          {actionLabel(change.change_status)}
                        </Badge>
                      ) : (
                        <Badge variant="secondary">No comparable move</Badge>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {data?.data_caveats?.length ? (
              <div className="flex flex-wrap gap-1.5">
                {data.data_caveats.map((caveat) => (
                  <Badge key={caveat.code} variant="warning" title={caveat.message}>
                    {titleizeCode(caveat.code)}
                  </Badge>
                ))}
              </div>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
