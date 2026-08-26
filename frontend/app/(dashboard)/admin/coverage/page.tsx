'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock3, RefreshCw } from 'lucide-react';

import apiClient from '@/lib/api/client';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

type CoverageItem = {
  id: number;
  user_email: string;
  stock_id: number;
  ticker: string;
  company_name: string;
  kind: string;
  priority_rank: number;
  matched_rule: string;
  state: 'ready' | 'missing' | 'stale' | 'blocked' | 'in_progress' | 'failed';
  reason: string;
  reason_code: string | null;
  freshness_policy_version: string;
  evaluated_at: string;
  next_action: string | null;
};

type CoveragePayload = {
  priority_policy_version: string;
  summary: {
    total: number;
    by_state: Record<string, number>;
    by_kind: Record<string, number>;
  };
  items: CoverageItem[];
};

const stateVariant = {
  ready: 'success',
  missing: 'warning',
  stale: 'warning',
  blocked: 'danger',
  in_progress: 'info',
  failed: 'danger',
} as const;

function label(value: string) {
  return value.replaceAll('_', ' ');
}

export default function CoverageAdminPage() {
  const [payload, setPayload] = useState<CoveragePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [evaluating, setEvaluating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.get<CoveragePayload>('/coverage/admin/requirements');
      setPayload(response.data);
    } catch {
      setError('Unable to load coverage queue. Check authorization and API health, then retry.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function evaluateAll() {
    setEvaluating(true);
    setError(null);
    try {
      await apiClient.post('/coverage/admin/evaluate-all?lens=consensus');
      await load();
    } catch {
      setError('Coverage evaluation failed. Existing results remain visible and can be retried.');
    } finally {
      setEvaluating(false);
    }
  }

  const unresolved = payload?.items.filter((item) => item.state !== 'ready').length ?? 0;
  const blocked = payload?.summary.by_state.blocked ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="space-y-2">
          <Badge variant="outline">Operations</Badge>
          <h1 className="text-3xl font-semibold tracking-tight">Research coverage queue</h1>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Explainable EOD and Value Line readiness for active research priorities. Blocked is not covered,
            and proprietary reports enter the system only through an authorized source or explicit upload.
          </p>
        </div>
        <Button type="button" onClick={() => void evaluateAll()} disabled={evaluating}>
          <RefreshCw className={evaluating ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
          {evaluating ? 'Evaluating…' : 'Evaluate all users'}
        </Button>
      </div>

      {error ? (
        <Card className="border-rose-500/40 bg-rose-500/5">
          <CardContent className="flex items-start gap-3 p-5">
            <AlertTriangle className="mt-0.5 h-5 w-5 text-rose-600" />
            <div>
              <div className="font-medium">{error}</div>
              <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => void load()}>
                Retry
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Current requirements</CardDescription>
            <CardTitle className="text-3xl">{payload?.summary.total ?? '—'}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Needs action</CardDescription>
            <CardTitle className="flex items-center gap-2 text-3xl">
              <Clock3 className="h-5 w-5 text-amber-600" /> {unresolved}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Blocked</CardDescription>
            <CardTitle className="flex items-center gap-2 text-3xl">
              <AlertTriangle className="h-5 w-5 text-rose-600" /> {blocked}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Priority queue</CardTitle>
          <CardDescription>
            Policy {payload?.priority_policy_version ?? '—'} · owned/watch cases will outrank discovery as they enter the workflow.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="py-12 text-center text-sm text-muted-foreground">Loading coverage queue…</div>
          ) : payload && payload.items.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Priority</TableHead>
                  <TableHead>Stock / user</TableHead>
                  <TableHead>Requirement</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead>Why</TableHead>
                  <TableHead>Permitted next action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {payload.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="font-mono text-xs">{item.priority_rank}</TableCell>
                    <TableCell>
                      <Link href={`/stocks/${item.ticker}/summary`} className="font-semibold text-primary hover:underline">
                        {item.ticker}
                      </Link>
                      <div className="max-w-48 truncate text-xs text-muted-foreground">{item.user_email}</div>
                      <div className="text-xs text-muted-foreground">{label(item.matched_rule)}</div>
                    </TableCell>
                    <TableCell>
                      <div className="font-medium">{label(item.kind)}</div>
                      <div className="text-xs text-muted-foreground">{item.freshness_policy_version}</div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={stateVariant[item.state]}>{label(item.state)}</Badge>
                    </TableCell>
                    <TableCell className="max-w-80">
                      <div>{item.reason}</div>
                      {item.reason_code ? (
                        <div className="mt-1 font-mono text-xs text-muted-foreground">{item.reason_code}</div>
                      ) : (
                        <div className="mt-1 flex items-center gap-1 text-xs text-emerald-700">
                          <CheckCircle2 className="h-3 w-3" /> Evidence ready
                        </div>
                      )}
                    </TableCell>
                    <TableCell>{item.next_action ? label(item.next_action) : 'No action'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="rounded-xl border border-dashed p-10 text-center">
              <div className="font-medium">Empty coverage queue</div>
              <p className="mt-1 text-sm text-muted-foreground">
                Add a Watchlist stock or evaluate a current Oracle&apos;s Lens candidate universe.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
