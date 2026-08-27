'use client';

import { useQuery } from '@tanstack/react-query';
import { BellRing, LoaderCircle } from 'lucide-react';

import apiClient from '@/lib/api/client';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

type Operations = {
  configuration_readiness: Record<string, boolean>;
  backlog: Record<string, number>;
  oldest_pending_at: string | null;
  last_success_at: string | null;
  failures_by_class: Record<string, number>;
  destinations_by_status: Record<string, number>;
  latest_secret_rotation: null | {
    job_id: number;
    status: string;
    created_at: string;
    finished_at: string | null;
    summary: Record<string, number> | null;
    error_class: string | null;
  };
};

function label(value: string) {
  return value.replaceAll('_', ' ');
}

export default function NotificationOperationsPage() {
  const query = useQuery({
    queryKey: ['notification-operations'],
    queryFn: async () => {
      const response = await apiClient.get('/notifications/admin/operations');
      return response.data as Operations;
    },
    refetchInterval: 60_000,
  });

  if (query.isLoading) return <div className="flex items-center gap-2 text-sm text-muted-foreground"><LoaderCircle className="h-4 w-4 animate-spin" /> Loading notification operations…</div>;
  if (query.isError || !query.data) return <div className="rounded-lg border border-destructive/40 p-6 text-sm text-destructive">Notification operations are unavailable or this account is not authorized.</div>;
  const data = query.data;
  const pending = Object.values(data.backlog).reduce((sum, value) => sum + value, 0);

  return (
    <div className="space-y-6">
      <div><div className="flex items-center gap-2 text-sm font-medium text-primary"><BellRing className="h-4 w-4" /> Notification Ops</div><h1 className="mt-2 font-display text-3xl font-semibold">Delivery operations</h1><p className="mt-2 text-sm text-muted-foreground">Aggregate readiness, backlog, age, failures, and rotation health. No user content or destination credentials are exposed.</p></div>
      <div className="grid gap-4 md:grid-cols-4">{Object.entries(data.configuration_readiness).map(([key, ready]) => <Card key={key}><CardHeader><CardDescription>{label(key)}</CardDescription><CardTitle><Badge variant={ready ? 'success' : 'warning'}>{ready ? 'ready' : 'blocked'}</Badge></CardTitle></CardHeader></Card>)}</div>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card><CardHeader><CardTitle>Outbox backlog · {pending}</CardTitle><CardDescription>Oldest pending: {data.oldest_pending_at ? new Date(data.oldest_pending_at).toLocaleString() : 'none'} · last success: {data.last_success_at ? new Date(data.last_success_at).toLocaleString() : 'none'}</CardDescription></CardHeader><CardContent className="space-y-2">{Object.entries(data.backlog).map(([key, count]) => <div key={key} className="flex justify-between rounded-lg border p-3 text-sm"><span>{label(key)}</span><span className="font-medium">{count}</span></div>)}</CardContent></Card>
        <Card><CardHeader><CardTitle>Failure classes</CardTitle><CardDescription>Typed provider outcomes; no message bodies or destination labels.</CardDescription></CardHeader><CardContent className="space-y-2">{Object.keys(data.failures_by_class).length === 0 ? <div className="text-sm text-muted-foreground">No recorded failures.</div> : Object.entries(data.failures_by_class).map(([key, count]) => <div key={key} className="flex justify-between rounded-lg border p-3 text-sm"><span>{label(key)}</span><span className="font-medium">{count}</span></div>)}</CardContent></Card>
        <Card><CardHeader><CardTitle>Destination readiness</CardTitle></CardHeader><CardContent className="space-y-2">{Object.keys(data.destinations_by_status).length === 0 ? <div className="text-sm text-muted-foreground">No configured destinations.</div> : Object.entries(data.destinations_by_status).map(([key, count]) => <div key={key} className="flex justify-between rounded-lg border p-3 text-sm"><span>{label(key)}</span><span className="font-medium">{count}</span></div>)}</CardContent></Card>
        <Card><CardHeader><CardTitle>Secret rotation</CardTitle><CardDescription>Bounded re-encryption job audit.</CardDescription></CardHeader><CardContent>{data.latest_secret_rotation ? <div className="space-y-2 text-sm"><Badge variant={data.latest_secret_rotation.status === 'succeeded' ? 'success' : 'danger'}>{label(data.latest_secret_rotation.status)}</Badge><div>Job #{data.latest_secret_rotation.job_id} · {new Date(data.latest_secret_rotation.created_at).toLocaleString()}</div>{data.latest_secret_rotation.error_class ? <div className="text-destructive">{label(data.latest_secret_rotation.error_class)}</div> : null}</div> : <div className="text-sm text-muted-foreground">No rotation run recorded.</div>}</CardContent></Card>
      </div>
    </div>
  );
}
