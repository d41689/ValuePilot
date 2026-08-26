'use client';

import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  Inbox,
  LoaderCircle,
  RefreshCcw,
  X,
} from 'lucide-react';

import apiClient from '@/lib/api/client';
import TickerSearchBox from '@/components/TickerSearchBox';
import { OpenResearchCaseButton } from '@/components/research/OpenResearchCaseButton';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

type InboxAction = {
  id: number;
  logical_key: string;
  action_family: string;
  source_version: string;
  matched_rule: string;
  priority_rank: number;
  reason: string;
  target_case_id: number | null;
  stock_id: number | null;
  ticker: string | null;
  company_name: string | null;
  evidence: Record<string, unknown>;
};

function sevenDaysFromNow() {
  const next = new Date();
  next.setUTCDate(next.getUTCDate() + 7);
  return next.toISOString().slice(0, 10);
}

function actionLabel(family: string) {
  return {
    review_due: 'Review due',
    continue_research: 'Continue research',
    start_research: 'Start research',
    coverage_gap: 'Coverage gap',
    candidate_discovery: 'New candidate',
    manager_activity: 'Manager activity',
  }[family] ?? family.replaceAll('_', ' ');
}

export default function HomePage() {
  const queryClient = useQueryClient();
  const inboxQuery = useQuery({
    queryKey: ['research-inbox'],
    queryFn: async () => {
      await apiClient.post('/research/inbox/regenerate');
      const response = await apiClient.get('/research/inbox');
      return response.data as { items: InboxAction[]; total: number };
    },
  });

  const actionMutation = useMutation({
    mutationFn: async ({ id, operation }: { id: number; operation: 'snooze' | 'dismiss' | 'complete' }) => {
      if (operation === 'snooze') {
        return apiClient.post(`/research/inbox/${id}/snooze`, {
          snoozed_until: sevenDaysFromNow(),
        });
      }
      return apiClient.post(`/research/inbox/${id}/${operation}`);
    },
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['research-inbox'] }),
  });

  const items = inboxQuery.data?.items ?? [];

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-border/60 bg-background/70 p-6 shadow-sm md:p-8">
        <div className="flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
          <div className="max-w-2xl space-y-3">
            <div className="flex items-center gap-2 text-sm font-medium text-primary">
              <Inbox className="h-4 w-4" aria-hidden="true" />
              Research Inbox
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">What deserves your attention next?</h1>
            <p className="text-sm text-muted-foreground">
              Actions are ranked by your decisions and review obligations before filing-derived discovery.
              A 13F signal is a research prompt, never a recommendation.
            </p>
          </div>
          <div className="w-full max-w-xl">
            <TickerSearchBox />
          </div>
        </div>
      </section>

      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Open actions</h2>
          <p className="text-sm text-muted-foreground">Every item states why it is here.</p>
        </div>
        <Button
          type="button"
          variant="outline"
          disabled={inboxQuery.isFetching}
          onClick={() => void inboxQuery.refetch()}
        >
          <RefreshCcw className={inboxQuery.isFetching ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
          Refresh actions
        </Button>
      </div>

      {inboxQuery.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
            <LoaderCircle className="h-4 w-4 animate-spin" /> Loading your research obligations…
          </CardContent>
        </Card>
      ) : inboxQuery.isError ? (
        <Card className="border-destructive/40">
          <CardContent className="space-y-4 p-8">
            <div className="flex items-center gap-2 font-medium text-destructive">
              <AlertCircle className="h-4 w-4" /> Unable to load your Research Inbox
            </div>
            <p className="text-sm text-muted-foreground">
              No action state was changed. Retry to rebuild the queue from durable evidence.
            </p>
            <Button type="button" variant="outline" onClick={() => void inboxQuery.refetch()}>
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 p-10 text-center">
            <CheckCircle2 className="h-8 w-8 text-emerald-600" />
            <div className="font-medium">No open research actions</div>
            <p className="max-w-lg text-sm text-muted-foreground">
              Add a company to a Watchlist, open a Lens candidate, or search for a ticker to begin a research cycle.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {items.map((item, index) => {
            const informational = ['candidate_discovery', 'manager_activity'].includes(item.action_family);
            const lensSignalId =
              typeof item.evidence.signal_id === 'number' ? item.evidence.signal_id : undefined;
            return (
              <Card key={item.id} className={index < 3 ? 'border-primary/30' : undefined}>
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={index < 3 ? 'default' : 'secondary'}>#{index + 1}</Badge>
                        <Badge variant="outline">{actionLabel(item.action_family)}</Badge>
                      </div>
                      <CardTitle className="mt-3 text-base">
                        {item.ticker ?? 'Research action'}
                        {item.company_name ? ` · ${item.company_name}` : ''}
                      </CardTitle>
                    </div>
                    {item.action_family === 'review_due' ? (
                      <Clock3 className="h-5 w-5 text-amber-600" aria-hidden="true" />
                    ) : null}
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <p className="text-sm leading-6">{item.reason}</p>
                  <div className="rounded-lg bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
                    Rule: <span className="font-mono">{item.matched_rule}</span> · Policy rank{' '}
                    {item.priority_rank}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {item.target_case_id ? (
                      <Button asChild size="sm">
                        <Link href={`/research/cases/${item.target_case_id}`}>
                          Open case <ArrowRight className="h-3.5 w-3.5" />
                        </Link>
                      </Button>
                    ) : item.stock_id ? (
                      <OpenResearchCaseButton
                        stockId={item.stock_id}
                        originType={lensSignalId ? 'oracle_lens' : 'watchlist'}
                        originKey={item.logical_key}
                        sourceVersion={item.source_version}
                        sourceRef={lensSignalId ? { signal_id: lensSignalId } : {}}
                        label="Create case"
                      />
                    ) : null}
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={actionMutation.isPending}
                      onClick={() => actionMutation.mutate({ id: item.id, operation: 'snooze' })}
                    >
                      <Clock3 className="h-3.5 w-3.5" /> Snooze 7 days
                    </Button>
                    {informational ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={actionMutation.isPending}
                        onClick={() => actionMutation.mutate({ id: item.id, operation: 'dismiss' })}
                      >
                        <X className="h-3.5 w-3.5" /> Dismiss
                      </Button>
                    ) : null}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
