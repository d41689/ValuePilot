'use client';

import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Clock3, RefreshCw } from 'lucide-react';

import apiClient from '@/lib/api/client';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

type CoveragePayload = {
  priority_policy_version: string;
  summary: {
    total: number;
    by_state: Record<string, number>;
    by_kind: Record<string, number>;
  };
};

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

  const unresolved = Math.max(
    (payload?.summary.total ?? 0) - (payload?.summary.by_state.ready ?? 0),
    0,
  );
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
          <CardTitle>Aggregate only</CardTitle>
          <CardDescription>
            Policy {payload?.priority_policy_version ?? '—'} · operational counts intentionally exclude users,
            stocks, cases, requirements, and source details.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="py-12 text-center text-sm text-muted-foreground">Loading aggregate coverage health…</div>
          ) : payload && payload.summary.total > 0 ? (
            <div className="grid gap-6 md:grid-cols-2">
              <div className="space-y-3">
                <div className="text-sm font-medium">By state</div>
                {Object.entries(payload.summary.by_state).map(([state, count]) => (
                  <div key={state} className="flex items-center justify-between rounded-lg border px-4 py-3 text-sm">
                    <span>{label(state)}</span>
                    <Badge variant="secondary">{count}</Badge>
                  </div>
                ))}
              </div>
              <div className="space-y-3">
                <div className="text-sm font-medium">By requirement type</div>
                {Object.entries(payload.summary.by_kind).map(([kind, count]) => (
                  <div key={kind} className="flex items-center justify-between rounded-lg border px-4 py-3 text-sm">
                    <span>{label(kind)}</span>
                    <Badge variant="secondary">{count}</Badge>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-dashed p-10 text-center">
              <div className="font-medium">No current requirements</div>
              <p className="mt-1 text-sm text-muted-foreground">
                Run the current aggregate evaluation after research priorities exist.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
