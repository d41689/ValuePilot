'use client';

import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { Plus, RefreshCcw, Trash2 } from 'lucide-react';

import apiClient from '@/lib/api/client';
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
};

type ApiError = {
  response?: {
    data?: {
      detail?: string;
    };
  };
};

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
  const [activePoolId, setActivePoolId] = useState<number | null>(null);
  const [newPoolName, setNewPoolName] = useState('');
  const [tickerInput, setTickerInput] = useState('');
  const [fairValueEdits, setFairValueEdits] = useState<Record<number, string>>({});
  const [refreshedPoolId, setRefreshedPoolId] = useState<number | null>(null);

  const poolsQuery = useQuery({
    queryKey: ['watchlist-pools'],
    queryFn: async () => {
      const res = await apiClient.get('/stock_pools');
      return res.data as StockPool[];
    },
  });

  const pools = poolsQuery.data ?? [];

  useEffect(() => {
    if (!activePoolId && pools.length > 0) {
      setActivePoolId(pools[0].id);
    }
  }, [activePoolId, pools]);

  const membersQuery = useQuery({
    queryKey: ['watchlist-members', activePoolId],
    enabled: Boolean(activePoolId),
    queryFn: async () => {
      const res = await apiClient.get(`/stock_pools/${activePoolId}/members`);
      return res.data as WatchlistRow[];
    },
  });

  const members = membersQuery.data ?? [];

  const sortedMembers = useMemo(() => {
    return [...members].sort((a, b) => {
      const aMos = a.mos ?? -Infinity;
      const bMos = b.mos ?? -Infinity;
      if (bMos === aMos) {
        return a.ticker.localeCompare(b.ticker);
      }
      return bMos - aMos;
    });
  }, [members]);

  useEffect(() => {
    setFairValueEdits((prev) => {
      if (!members.length) {
        return Object.keys(prev).length === 0 ? prev : {};
      }
      const next: Record<number, string> = {};
      for (const row of members) {
        next[row.stock_id] = row.fair_value !== null ? row.fair_value.toString() : '';
      }
      const prevKeys = Object.keys(prev);
      const nextKeys = Object.keys(next);
      if (prevKeys.length !== nextKeys.length) return next;
      for (const key of nextKeys) {
        if (prev[key] !== next[key]) {
          return next;
        }
      }
      return prev;
    });
  }, [members]);

  useEffect(() => {
    if (!activePoolId) return;
    if (refreshedPoolId === activePoolId) return;
    if (!members.length) return;
    setRefreshedPoolId(activePoolId);
    const stockIds = members.map((row) => row.stock_id);
    refreshPrices.mutate(stockIds);
  }, [activePoolId, refreshedPoolId, members]);

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
      setActivePoolId(pool.id);
      setRefreshedPoolId(null);
      toast({
        title: 'Watchlist created',
        description: `“${pool.name}” is ready.`,
      });
    },
    onError: () => {
      toast({
        title: 'Create failed',
        description: 'Unable to create watchlist. Please try again.',
        variant: 'destructive',
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
      setActivePoolId(null);
      setRefreshedPoolId(null);
      toast({
        title: 'Watchlist deleted',
        description: 'The watchlist has been removed.',
      });
    },
    onError: () => {
      toast({
        title: 'Delete failed',
        description: 'Unable to delete watchlist.',
        variant: 'destructive',
      });
    },
  });

  const addMember = useMutation({
    mutationFn: async (stockId: number) => {
      const res = await apiClient.post(`/stock_pools/${activePoolId}/members`, { stock_id: stockId });
      return res.data;
    },
    onSuccess: () => {
      membersQuery.refetch();
      poolsQuery.refetch();
      setTickerInput('');
      setRefreshedPoolId(null);
      toast({ title: 'Ticker added' });
    },
    onError: (error: unknown) => {
      const apiError = (typeof error === 'object' && error !== null ? error : {}) as ApiError;
      const message = apiError.response?.data?.detail ?? 'Unable to add ticker.';
      toast({ title: 'Add failed', description: message, variant: 'destructive' });
    },
  });

  const removeMember = useMutation({
    mutationFn: async (membershipId: number) => {
      const res = await apiClient.delete(`/stock_pools/${activePoolId}/members/${membershipId}`);
      return res.data;
    },
    onSuccess: () => {
      membersQuery.refetch();
      poolsQuery.refetch();
      toast({ title: 'Removed from watchlist' });
    },
    onError: () => {
      toast({
        title: 'Remove failed',
        description: 'Unable to remove ticker.',
        variant: 'destructive',
      });
    },
  });

  const refreshPrices = useMutation({
    mutationFn: async (stockIds: number[]) => {
      if (!stockIds.length) return [];
      const res = await apiClient.post('/stocks/prices/refresh', {
        stock_ids: stockIds,
        reason: 'watchlist_open',
      });
      return res.data;
    },
    onSuccess: () => {
      membersQuery.refetch();
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
      toast({
        title: 'Update failed',
        description: 'Unable to update Fair Value.',
        variant: 'destructive',
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
      toast({ title: 'Lookup failed', description: message, variant: 'destructive' });
    }
  };

  const handleFairValueSave = (stockId: number) => {
    const raw = fairValueEdits[stockId];
    if (raw === undefined) return;
    const value = Number(raw);
    if (!Number.isFinite(value)) {
      toast({
        title: 'Invalid value',
        description: 'Fair Value must be a number.',
        variant: 'destructive',
      });
      return;
    }
    updateFairValue.mutate({ stockId, value });
  };

  const activePool = useMemo(
    () => pools.find((pool) => pool.id === activePoolId) ?? null,
    [pools, activePoolId]
  );

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">Watchlist</h1>
          <p className="text-sm text-muted-foreground">
            Daily decision dashboard for your highest-conviction names.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            onClick={() => refreshPrices.mutate(members.map((row) => row.stock_id))}
            disabled={!members.length || refreshPrices.isPending}
          >
            <RefreshCcw className="mr-2 h-4 w-4" />
            Refresh Prices
          </Button>
          {activePool && (
            <Button
              variant="destructive"
              onClick={() => deletePool.mutate(activePool.id)}
              disabled={deletePool.isPending}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete Watchlist
            </Button>
          )}
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <Card className="border-border/60 bg-card/85">
          <CardHeader>
            <CardTitle className="text-base">My Watchlists</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1">
              {pools.length === 0 && (
                <div className="text-sm text-muted-foreground">No watchlists yet.</div>
              )}
              {pools.map((pool) => (
                <button
                  key={pool.id}
                  className={`w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                    pool.id === activePoolId
                      ? 'bg-primary/10 text-primary'
                      : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'
                  }`}
                  onClick={() => {
                    setActivePoolId(pool.id);
                    setRefreshedPoolId(null);
                  }}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{pool.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {pool.member_count ?? 0}
                    </span>
                  </div>
                </button>
              ))}
            </div>
            <div className="space-y-2">
              <input
                className="w-full rounded-lg border border-border/60 bg-background px-3 py-2 text-sm outline-none"
                placeholder="New watchlist name"
                value={newPoolName}
                onChange={(event) => setNewPoolName(event.target.value)}
              />
              <Button
                className="w-full"
                onClick={() => createPool.mutate()}
                disabled={!newPoolName.trim() || createPool.isPending}
              >
                <Plus className="mr-2 h-4 w-4" />
                Create Watchlist
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/60 bg-card/85">
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div>
              <CardTitle className="text-base">
                {activePool ? activePool.name : 'Select a Watchlist'}
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                Add tickers and update Fair Value to see Margin of Safety.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <input
                className="w-40 rounded-lg border border-border/60 bg-background px-3 py-2 text-sm outline-none"
                placeholder="Ticker"
                value={tickerInput}
                onChange={(event) => setTickerInput(event.target.value)}
                disabled={!activePoolId}
              />
              <Button
                onClick={handleAddTicker}
                disabled={!tickerInput.trim() || !activePoolId || addMember.isPending}
              >
                <Plus className="mr-2 h-4 w-4" />
                Add Ticker
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {membersQuery.isLoading && (
              <div className="py-10 text-sm text-muted-foreground">Loading watchlist...</div>
            )}
            {!membersQuery.isLoading && members.length === 0 && (
              <div className="py-10 text-sm text-muted-foreground">
                No stocks yet. Add your first ticker →
              </div>
            )}
            {members.length > 0 && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Ticker</TableHead>
                    <TableHead>Company</TableHead>
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
                      <TableCell>{formatNumber(row.price)}</TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          <input
                            className="w-24 rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
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
                          <Button
                            variant="ghost"
                            onClick={() => removeMember.mutate(row.membership_id)}
                          >
                            Remove
                          </Button>
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
    </div>
  );
}
