'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { BarChart3, MoreHorizontal, Plus, RefreshCcw, Trash2 } from 'lucide-react';

import apiClient from '@/lib/api/client';
import { showAppToast } from '@/lib/appToast';
import {
  OVERVIEW_WATCHLIST_ID,
  buildFairValueEdits,
  formatOverviewOptionLabel,
  formatPiotroskiFScoreSeries,
  formatRefreshPricesSuccessDescription,
  formatWatchlistOptionLabel,
  getRefreshPricesButtonPresentation,
  hasFairValueEditChanges,
  isOverviewWatchlistId,
  sortWatchlistMembers,
} from '@/lib/watchlistState';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
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
import { useToast } from '@/components/ui/use-toast';

type StockPool = {
  id: number;
  name: string;
  description?: string | null;
  member_count?: number;
};

type WatchlistRow = {
  membership_id: number;
  stock_id: number;
  ticker: string;
  exchange: string;
  company_name: string;
  price: number | null;
  price_date: string;
  price_updated_at: string | null;
  fair_value: number | null;
  fair_value_source: string | null;
  mos: number | null;
  delta_today: number | null;
  piotroski_f_scores: Array<{
    period_end_date: string | null;
    fiscal_year: number | null;
    score: number | null;
    status: string | null;
    variant: string | null;
    partial_score: number | null;
    available_indicators: number | null;
    max_available_score: number | null;
    missing_indicators: string[];
  }>;
};

type ApiError = {
  response?: {
    data?: {
      detail?: string;
    };
  };
};

type RefreshPricesPayload = {
  showToast?: boolean;
  stockIds: number[];
};

type RefreshPriceResult = {
  stock_id: number;
  status: string;
};

type ActiveWatchlistId = number | typeof OVERVIEW_WATCHLIST_ID;

function formatNumber(value: number | null, digits = 2) {
  if (value === null || Number.isNaN(value)) return '—';
  return value.toFixed(digits);
}

function formatPercent(value: number | null) {
  if (value === null || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(1)}%`;
}

function formatDate(value: string | null) {
  if (!value) return '—';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return '—';
  return dt.toLocaleString();
}

export default function WatchlistPage() {
  const { toast } = useToast();
  const [activeWatchlistId, setActiveWatchlistId] =
    useState<ActiveWatchlistId>(OVERVIEW_WATCHLIST_ID);
  const [newPoolName, setNewPoolName] = useState('');
  const [tickerInput, setTickerInput] = useState('');
  const [fairValueEdits, setFairValueEdits] = useState<Record<number, string>>({});
  const [refreshedWatchlistId, setRefreshedWatchlistId] =
    useState<ActiveWatchlistId | null>(null);

  const poolsQuery = useQuery({
    queryKey: ['watchlist-pools'],
    queryFn: async () => {
      const res = await apiClient.get('/stock_pools');
      return res.data as StockPool[];
    },
  });

  const pools = useMemo(() => poolsQuery.data ?? [], [poolsQuery.data]);
  const isOverviewActive = isOverviewWatchlistId(activeWatchlistId);
  const activePoolId = typeof activeWatchlistId === 'number' ? activeWatchlistId : null;
  const activeWatchlistValue = isOverviewActive ? OVERVIEW_WATCHLIST_ID : String(activePoolId);

  const membersQuery = useQuery({
    queryKey: ['watchlist-members', activeWatchlistId],
    queryFn: async () => {
      const endpoint = isOverviewWatchlistId(activeWatchlistId)
        ? '/stock_pools/overview/members'
        : `/stock_pools/${activeWatchlistId}/members`;
      const res = await apiClient.get(endpoint);
      return res.data as WatchlistRow[];
    },
  });

  const members = useMemo(() => membersQuery.data ?? [], [membersQuery.data]);

  const sortedMembers = useMemo(() => {
    return sortWatchlistMembers(members);
  }, [members]);

  const refreshPrices = useMutation({
    mutationFn: async ({ stockIds }: RefreshPricesPayload) => {
      if (!stockIds.length) return [];
      const res = await apiClient.post('/stocks/prices/refresh', {
        stock_ids: stockIds,
        reason: 'watchlist_open',
      });
      return res.data as RefreshPriceResult[];
    },
    onSuccess: (results, payload) => {
      membersQuery.refetch();
      if (payload.showToast) {
        showAppToast(toast, {
          type: 'success',
          title: 'Prices refreshed',
          description: formatRefreshPricesSuccessDescription(results, payload.stockIds.length),
        });
      }
    },
    onError: (error: unknown, payload) => {
      if (!payload.showToast) return;
      const apiError = (typeof error === 'object' && error !== null ? error : {}) as ApiError;
      const message = apiError.response?.data?.detail ?? 'Unable to refresh prices.';
      showAppToast(toast, {
        type: 'error',
        title: 'Refresh failed',
        description: message,
      });
    },
  });

  const refreshPricesMutateRef = useRef(refreshPrices.mutate);

  useEffect(() => {
    refreshPricesMutateRef.current = refreshPrices.mutate;
  }, [refreshPrices.mutate]);

  useEffect(() => {
    setFairValueEdits((prev) => {
      const next = buildFairValueEdits(members);
      return hasFairValueEditChanges(prev, next) ? next : prev;
    });
  }, [members]);

  useEffect(() => {
    if (refreshedWatchlistId === activeWatchlistId) return;
    if (!members.length) return;
    setRefreshedWatchlistId(activeWatchlistId);
    refreshPricesMutateRef.current({
      showToast: false,
      stockIds: members.map((row) => row.stock_id),
    });
  }, [activeWatchlistId, refreshedWatchlistId, members]);

  const createPool = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/stock_pools', {
        name: newPoolName,
      });
      return res.data as StockPool;
    },
    onSuccess: (pool) => {
      setNewPoolName('');
      poolsQuery.refetch();
      setActiveWatchlistId(pool.id);
      setRefreshedWatchlistId(null);
      showAppToast(toast, {
        type: 'success',
        title: 'Watchlist created',
        description: `“${pool.name}” is ready.`,
      });
    },
    onError: () => {
      showAppToast(toast, {
        type: 'error',
        title: 'Create failed',
        description: 'Unable to create watchlist. Please try again.',
      });
    },
  });

  const deletePool = useMutation({
    mutationFn: async (poolId: number) => {
      const res = await apiClient.delete(`/stock_pools/${poolId}`);
      return res.data;
    },
    onSuccess: () => {
      poolsQuery.refetch();
      setActiveWatchlistId(OVERVIEW_WATCHLIST_ID);
      setRefreshedWatchlistId(null);
      showAppToast(toast, {
        type: 'success',
        title: 'Watchlist deleted',
        description: 'The watchlist has been removed.',
      });
    },
    onError: () => {
      showAppToast(toast, {
        type: 'error',
        title: 'Delete failed',
        description: 'Unable to delete watchlist.',
      });
    },
  });

  const addMember = useMutation({
    mutationFn: async (stockId: number) => {
      if (!activePoolId) {
        throw new Error('Cannot add ticker to Overview');
      }
      const res = await apiClient.post(`/stock_pools/${activePoolId}/members`, { stock_id: stockId });
      return res.data;
    },
    onSuccess: () => {
      membersQuery.refetch();
      poolsQuery.refetch();
      setTickerInput('');
      setRefreshedWatchlistId(null);
      showAppToast(toast, {
        type: 'success',
        title: 'Ticker added',
      });
    },
    onError: (error: unknown) => {
      const apiError = (typeof error === 'object' && error !== null ? error : {}) as ApiError;
      const message = apiError.response?.data?.detail ?? 'Unable to add ticker.';
      showAppToast(toast, {
        type: 'error',
        title: 'Add failed',
        description: message,
      });
    },
  });

  const removeMember = useMutation({
    mutationFn: async (membershipId: number) => {
      if (!activePoolId) {
        throw new Error('Cannot remove ticker from Overview');
      }
      const res = await apiClient.delete(`/stock_pools/${activePoolId}/members/${membershipId}`);
      return res.data;
    },
    onSuccess: () => {
      membersQuery.refetch();
      poolsQuery.refetch();
      showAppToast(toast, {
        type: 'success',
        title: 'Removed from watchlist',
      });
    },
    onError: () => {
      showAppToast(toast, {
        type: 'error',
        title: 'Remove failed',
        description: 'Unable to remove ticker.',
      });
    },
  });

  const updateFairValue = useMutation({
    mutationFn: async (payload: { stockId: number; value: number }) => {
      const res = await apiClient.put(`/stocks/${payload.stockId}/facts`, {
        metric_key: 'val.fair_value',
        value_numeric: payload.value,
      });
      return res.data;
    },
    onSuccess: () => {
      membersQuery.refetch();
    },
    onError: () => {
      showAppToast(toast, {
        type: 'error',
        title: 'Update failed',
        description: 'Unable to update Fair Value.',
      });
    },
  });

  const handleAddTicker = async () => {
    if (!activePoolId) return;
    const trimmed = tickerInput.trim().toUpperCase();
    if (!trimmed) return;
    try {
      const res = await apiClient.get(`/stocks/by_ticker/${encodeURIComponent(trimmed)}`);
      const stockId = res.data?.id;
      if (!stockId) {
        throw new Error('Stock not found');
      }
      addMember.mutate(stockId);
    } catch (error: unknown) {
      const apiError = (typeof error === 'object' && error !== null ? error : {}) as ApiError;
      const message = apiError.response?.data?.detail ?? 'Ticker not found.';
      showAppToast(toast, {
        type: 'error',
        title: 'Lookup failed',
        description: message,
      });
    }
  };

  const handleFairValueSave = (stockId: number) => {
    const raw = fairValueEdits[stockId];
    if (raw === undefined) return;
    const value = Number(raw);
    if (!Number.isFinite(value)) {
      showAppToast(toast, {
        type: 'error',
        title: 'Invalid value',
        description: 'Fair Value must be a number.',
      });
      return;
    }
    updateFairValue.mutate({ stockId, value });
  };

  const activePool = useMemo(
    () => pools.find((pool) => pool.id === activePoolId) ?? null,
    [pools, activePoolId]
  );
  const overviewMemberCount = isOverviewActive ? members.length : null;
  const refreshButton = getRefreshPricesButtonPresentation(refreshPrices.isPending);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">Watchlist</h1>
          <p className="text-sm text-muted-foreground">
            Daily decision dashboard for your highest-conviction names.
          </p>
        </div>
      </header>

      <Card className="min-w-0 border-border/60 bg-card/85">
        <CardHeader className="gap-4">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div className="flex min-w-0 flex-1 flex-wrap items-end gap-3">
              <div className="flex min-w-[15rem] flex-col gap-1">
                <span className="text-xs font-semibold uppercase text-muted-foreground">
                  Watchlist
                </span>
                <div className="flex items-center gap-2">
                  <Select
                    value={activeWatchlistValue}
                    onValueChange={(nextValue) => {
                      setActiveWatchlistId(
                        isOverviewWatchlistId(nextValue) ? OVERVIEW_WATCHLIST_ID : Number(nextValue)
                      );
                      setRefreshedWatchlistId(null);
                    }}
                  >
                    <SelectTrigger className="min-w-[15rem]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={OVERVIEW_WATCHLIST_ID}>
                        {formatOverviewOptionLabel(overviewMemberCount)}
                      </SelectItem>
                    {pools.map((pool) => (
                      <SelectItem key={pool.id} value={String(pool.id)}>
                        {formatWatchlistOptionLabel(pool)}
                      </SelectItem>
                    ))}
                    </SelectContent>
                  </Select>
                  <Button asChild variant="outline">
                    <Link href={`/watchlist/f-score-compare?watchlistId=${encodeURIComponent(activeWatchlistValue)}`}>
                      <BarChart3 className="mr-2 h-4 w-4" />
                      F-Score Compare
                    </Link>
                  </Button>
                </div>
              </div>

              <div className="flex min-w-[16rem] flex-1 items-end gap-2 sm:max-w-md">
                <div className="flex flex-1 flex-col gap-1">
                  <span className="text-xs font-semibold uppercase text-muted-foreground">
                    New List
                  </span>
                  <Input
                    placeholder="Name"
                    value={newPoolName}
                    onChange={(event) => setNewPoolName(event.target.value)}
                  />
                </div>
                <Button
                  onClick={() => createPool.mutate()}
                  disabled={!newPoolName.trim() || createPool.isPending}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Create
                </Button>
              </div>
            </div>

            <div className="flex flex-wrap items-end gap-2">
              <div className="flex items-end gap-2">
                <div className="flex flex-col gap-1">
                  <span className="text-xs font-semibold uppercase text-muted-foreground">
                    Ticker
                  </span>
                  <Input
                    className="w-32"
                    placeholder="Symbol"
                    value={tickerInput}
                    onChange={(event) => setTickerInput(event.target.value)}
                    disabled={isOverviewActive}
                  />
                </div>
                <Button
                  onClick={handleAddTicker}
                  disabled={isOverviewActive || !tickerInput.trim() || addMember.isPending}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Add
                </Button>
              </div>
              <Button
                variant="outline"
                onClick={() =>
                  refreshPrices.mutate({
                    showToast: true,
                    stockIds: members.map((row) => row.stock_id),
                  })
                }
                disabled={!members.length || refreshPrices.isPending}
              >
                <RefreshCcw className={refreshButton.iconClassName} />
                {refreshButton.label}
              </Button>
              {!isOverviewActive && activePool && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="outline" size="icon" type="button">
                      <MoreHorizontal className="h-4 w-4" />
                      <span className="sr-only">Watchlist actions</span>
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      className="text-destructive focus:text-destructive"
                      onClick={() => deletePool.mutate(activePool.id)}
                      disabled={deletePool.isPending}
                    >
                      <Trash2 className="mr-2 h-4 w-4" />
                      Delete Watchlist
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {membersQuery.isLoading && (
            <div className="py-10 text-sm text-muted-foreground">Loading watchlist...</div>
          )}
          {!membersQuery.isLoading && members.length === 0 && (
            <div className="py-10 text-sm text-muted-foreground">
              {isOverviewActive ? 'No stocks in Overview.' : 'No stocks yet. Add your first ticker.'}
            </div>
          )}
          {members.length > 0 && (
            <Table className="min-w-[1080px]">
              <TableHeader>
                <TableRow>
                  <TableHead>Ticker</TableHead>
                  <TableHead>Company</TableHead>
                  <TableHead>F-Score 3Y</TableHead>
                  <TableHead>Price</TableHead>
                  <TableHead>Fair Value</TableHead>
                  <TableHead>MOS</TableHead>
                  <TableHead>Δ Today</TableHead>
                  <TableHead>Last Update</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedMembers.map((row) => (
                  <TableRow key={row.membership_id}>
                    <TableCell className="font-medium">{row.ticker}</TableCell>
                    <TableCell>{row.company_name}</TableCell>
                    <TableCell className="min-w-[9rem] max-w-[11rem] whitespace-pre-line text-xs leading-5 text-muted-foreground">
                      {formatPiotroskiFScoreSeries(row.piotroski_f_scores)}
                    </TableCell>
                    <TableCell>{formatNumber(row.price)}</TableCell>
                    <TableCell>
                      <div className="flex flex-col gap-1">
                        <Input
                          className="h-8 w-24 px-2 py-1"
                          value={fairValueEdits[row.stock_id] ?? ''}
                          onChange={(event) =>
                            setFairValueEdits((prev) => ({
                              ...prev,
                              [row.stock_id]: event.target.value,
                            }))
                          }
                          onBlur={() => handleFairValueSave(row.stock_id)}
                        />
                        <span className="text-xs text-muted-foreground">
                          {row.fair_value_source ?? '—'}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell
                      className={
                        row.mos !== null && row.mos > 0.3 ? 'font-semibold text-emerald-600' : undefined
                      }
                    >
                      {formatPercent(row.mos)}
                    </TableCell>
                    <TableCell>{formatNumber(row.delta_today)}</TableCell>
                    <TableCell>{formatDate(row.price_updated_at)}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Button asChild variant="outline">
                          <Link href={`/stocks/${encodeURIComponent(row.ticker)}/dcf`}>DCF</Link>
                        </Button>
                        {!isOverviewActive && (
                          <Button
                            variant="ghost"
                            onClick={() => removeMember.mutate(row.membership_id)}
                          >
                            Remove
                          </Button>
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
