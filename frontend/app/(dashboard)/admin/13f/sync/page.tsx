'use client';

/**
 * MVP6-03: dedicated Daily Sync route.
 *
 * PRD §11.1 "Daily Sync" surface. Three sections:
 *
 *   1. EDGAR rate-limit panel (existing
 *      ``useEdgarRateLimitQuery`` + ``normalizeEdgarRateLimit``
 *      helper from ``thirteenfAdmin``).
 *   2. Recent daily-sync activity (existing ``useJobsQuery``
 *      filtered to ``fetch_daily_index`` +
 *      ``backfill_daily_indexes`` per SR1 — no dedicated
 *      ``edgar_sync_status`` GET endpoint yet).
 *   3. No-index calendar CRUD (list / add / deactivate).
 *
 * Failed-sync retry stays on the Jobs page per SR2.
 */
import Link from 'next/link';
import { useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import apiClient from '@/lib/api/client';
import { AdminPageLayout } from '@/components/admin13f/AdminPageLayout';
import { AdminLoadingState } from '@/components/admin13f/AdminLoadingState';
import { AdminEmptyState } from '@/components/admin13f/AdminEmptyState';
import { AdminErrorState } from '@/components/admin13f/AdminErrorState';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
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
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/components/ui/use-toast';
import thirteenfAdmin from '@/lib/thirteenfAdmin';
import {
  useEdgarRateLimitQuery,
  useJobsQuery,
  useNoIndexDatesQuery,
} from '@/lib/admin13f/queries';

const { normalizeEdgarRateLimit } = thirteenfAdmin as {
  normalizeEdgarRateLimit: (payload: unknown) => {
    mode: string;
    requestDelayS: number;
    maxRetries: number;
    windowSeconds: number;
    recentRequestCount: number;
    estimatedCapacity: number;
    remainingEstimatedCapacity: number;
    globalPauseUntil: string | null;
    usageRatio: number | null;
    tone: string;
  };
};

const NO_INDEX_REASONS = [
  { value: 'weekend', label: 'Weekend' },
  { value: 'federal_holiday', label: 'Federal holiday' },
  { value: 'edgar_special_closure', label: 'EDGAR special closure' },
  { value: 'other', label: 'Other' },
];

const SYNC_JOB_TYPES = new Set(['fetch_daily_index', 'backfill_daily_indexes']);

function formatTimestamp(value: unknown): string {
  if (typeof value !== 'string') return '—';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function jobStatusVariant(status: string): 'success' | 'warning' | 'danger' | 'secondary' {
  if (status === 'succeeded') return 'success';
  if (status === 'failed' || status === 'canceled') return 'danger';
  if (status === 'running' || status === 'queued' || status === 'cancel_requested') return 'warning';
  return 'secondary';
}

export default function DailySyncPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const edgarRateLimitQuery = useEdgarRateLimitQuery();
  const rateLimit = useMemo(
    () => normalizeEdgarRateLimit(edgarRateLimitQuery.data ?? {}),
    [edgarRateLimitQuery.data],
  );

  // Sync activity via jobs endpoint with status filter passthrough.
  const [syncStatusFilter, setSyncStatusFilter] = useState('all');
  const jobsQuery = useJobsQuery({
    status: syncStatusFilter,
    jobType: 'all', // we filter to the two sync job_types client-side
    startedFrom: '',
    startedTo: '',
    syncDate: '',
    quarter: '',
  });
  const syncJobs = useMemo(() => {
    const items = jobsQuery.data?.items;
    if (!Array.isArray(items)) return [];
    return (items as Record<string, unknown>[]).filter((job) =>
      SYNC_JOB_TYPES.has(String(job.job_type ?? '')),
    );
  }, [jobsQuery.data]);

  // No-index calendar. Capture the current year at mount so the
  // ``yearOptions`` memo doesn't churn on every render.
  const currentYear = useMemo(() => new Date().getFullYear(), []);
  const [yearFilter, setYearFilter] = useState<number>(currentYear);
  const noIndexQuery = useNoIndexDatesQuery(yearFilter);

  const [newDate, setNewDate] = useState<string>('');
  const [newReason, setNewReason] = useState<string>('federal_holiday');
  const [newHolidayName, setNewHolidayName] = useState<string>('');
  const [newNote, setNewNote] = useState<string>('');

  const createNoIndex = useMutation({
    mutationFn: async (payload: {
      date: string;
      reason: string;
      holiday_name: string | null;
      note: string | null;
    }) => (await apiClient.post('/admin/13f/no-index-dates', payload)).data,
    onSuccess: () => {
      toast({ title: 'No-index date added' });
      queryClient.invalidateQueries({ queryKey: ['admin-13f-no-index-dates'] });
      setNewDate('');
      setNewHolidayName('');
      setNewNote('');
    },
    onError: (error: unknown) => {
      const message =
        error && typeof error === 'object' && 'message' in error
          ? String((error as { message?: unknown }).message)
          : 'Failed to add no-index date';
      toast({ title: message, variant: 'destructive' });
    },
  });

  const deactivateNoIndex = useMutation({
    mutationFn: async (expectedDate: string) =>
      (
        await apiClient.patch(`/admin/13f/no-index-dates/${expectedDate}`, {
          active: false,
        })
      ).data,
    onSuccess: () => {
      toast({ title: 'No-index date deactivated' });
      queryClient.invalidateQueries({ queryKey: ['admin-13f-no-index-dates'] });
    },
    onError: (error: unknown) => {
      const message =
        error && typeof error === 'object' && 'message' in error
          ? String((error as { message?: unknown }).message)
          : 'Failed to deactivate no-index date';
      toast({ title: message, variant: 'destructive' });
    },
  });

  const noIndexItems = useMemo(() => {
    const items = noIndexQuery.data?.items;
    return Array.isArray(items) ? (items as Record<string, unknown>[]) : [];
  }, [noIndexQuery.data]);

  const yearOptions = useMemo(
    () => [currentYear - 1, currentYear, currentYear + 1],
    [currentYear],
  );

  return (
    <AdminPageLayout
      title="Daily Sync"
      description="EDGAR rate limit, recent daily sync runs, and the no-index expected-date calendar."
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href="/admin/13f">← Back to Overview</Link>
        </Button>
      }
    >
      {/* EDGAR rate limit */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
            <span>EDGAR rate limit</span>
            <Badge
              variant={
                edgarRateLimitQuery.isError
                  ? 'warning'
                  : rateLimit.tone === 'success'
                    ? 'success'
                    : 'warning'
              }
            >
              {edgarRateLimitQuery.isError ? 'unavailable' : rateLimit.mode}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {edgarRateLimitQuery.isPending ? (
            <AdminLoadingState variant="compact" />
          ) : edgarRateLimitQuery.isError ? (
            <AdminErrorState
              error={edgarRateLimitQuery.error}
              onRetry={() => edgarRateLimitQuery.refetch()}
            />
          ) : (
            <div className="grid gap-3 text-sm md:grid-cols-3">
              <div>
                <div className="text-xs uppercase text-muted-foreground">Mode</div>
                <div className="mt-1 font-medium">{rateLimit.mode}</div>
              </div>
              <div>
                <div className="text-xs uppercase text-muted-foreground">Request delay (s)</div>
                <div className="mt-1 font-medium">{rateLimit.requestDelayS}</div>
              </div>
              <div>
                <div className="text-xs uppercase text-muted-foreground">Max retries</div>
                <div className="mt-1 font-medium">{rateLimit.maxRetries}</div>
              </div>
              <div>
                <div className="text-xs uppercase text-muted-foreground">Window (s)</div>
                <div className="mt-1 font-medium">{rateLimit.windowSeconds}</div>
              </div>
              <div>
                <div className="text-xs uppercase text-muted-foreground">Recent requests</div>
                <div className="mt-1 font-medium">{rateLimit.recentRequestCount} / {rateLimit.estimatedCapacity}</div>
              </div>
              <div>
                <div className="text-xs uppercase text-muted-foreground">Remaining capacity</div>
                <div className="mt-1 font-medium">{rateLimit.remainingEstimatedCapacity}</div>
              </div>
              {rateLimit.globalPauseUntil ? (
                <div className="md:col-span-3 rounded-md border border-amber-300/70 bg-amber-50 p-2 text-xs text-amber-950">
                  Global pause until {formatTimestamp(rateLimit.globalPauseUntil)}.
                </div>
              ) : null}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recent daily sync activity */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
            <span>Recent daily sync activity</span>
            <Select value={syncStatusFilter} onValueChange={setSyncStatusFilter}>
              <SelectTrigger className="w-[180px]" aria-label="Filter sync runs by status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectItem value="queued">Queued</SelectItem>
                <SelectItem value="running">Running</SelectItem>
                <SelectItem value="succeeded">Succeeded</SelectItem>
                <SelectItem value="partial_success">Partial success</SelectItem>
                <SelectItem value="failed">Failed</SelectItem>
              </SelectContent>
            </Select>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-3 text-xs text-muted-foreground">
            Showing <code className="font-mono">fetch_daily_index</code> +{' '}
            <code className="font-mono">backfill_daily_indexes</code> job runs.
            Use the{' '}
            <Link href="/admin/13f#jobs" className="text-foreground hover:underline">
              Jobs page
            </Link>{' '}
            to retry failed runs.
          </p>
          {jobsQuery.isPending ? (
            <AdminLoadingState />
          ) : jobsQuery.isError ? (
            <AdminErrorState
              error={jobsQuery.error}
              onRetry={() => jobsQuery.refetch()}
            />
          ) : syncJobs.length === 0 ? (
            <AdminEmptyState reason="pipeline-not-run" />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Started</TableHead>
                    <TableHead>Job type</TableHead>
                    <TableHead>Sync date</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Error</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {syncJobs.slice(0, 50).map((job) => (
                    <TableRow key={String(job.id)}>
                      <TableCell className="font-mono text-xs">
                        {formatTimestamp(job.started_at)}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {String(job.job_type ?? '—')}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {String((job.input_json as Record<string, unknown> | null)?.sync_date ?? '—')}
                      </TableCell>
                      <TableCell>
                        <Badge variant={jobStatusVariant(String(job.status ?? ''))}>
                          {String(job.status ?? '—')}
                        </Badge>
                      </TableCell>
                      <TableCell className="max-w-[280px] truncate text-xs text-muted-foreground">
                        {String(job.error_message ?? '')}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* No-index calendar */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
            <span>No-index expected dates</span>
            <Select
              value={String(yearFilter)}
              onValueChange={(value) => setYearFilter(Number(value))}
            >
              <SelectTrigger className="w-[120px]" aria-label="Filter no-index dates by year">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {yearOptions.map((y) => (
                  <SelectItem key={y} value={String(y)}>
                    {y}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-md border border-border/70 p-3">
            <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
              Add no-index date
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground" htmlFor="mvp6-03-date">
                  Date
                </label>
                <Input
                  id="mvp6-03-date"
                  type="date"
                  value={newDate}
                  onChange={(e) => setNewDate(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground" htmlFor="mvp6-03-reason">
                  Reason
                </label>
                <Select value={newReason} onValueChange={setNewReason}>
                  <SelectTrigger id="mvp6-03-reason">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {NO_INDEX_REASONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground" htmlFor="mvp6-03-holiday">
                  Holiday name (optional)
                </label>
                <Input
                  id="mvp6-03-holiday"
                  placeholder="e.g. Independence Day"
                  value={newHolidayName}
                  onChange={(e) => setNewHolidayName(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground" htmlFor="mvp6-03-note">
                  Note (optional)
                </label>
                <Textarea
                  id="mvp6-03-note"
                  rows={2}
                  value={newNote}
                  onChange={(e) => setNewNote(e.target.value)}
                />
              </div>
            </div>
            <div className="mt-3">
              <Button
                type="button"
                size="sm"
                disabled={!newDate.trim() || createNoIndex.isPending}
                onClick={() =>
                  createNoIndex.mutate({
                    date: newDate,
                    reason: newReason,
                    holiday_name: newHolidayName.trim() || null,
                    note: newNote.trim() || null,
                  })
                }
              >
                {createNoIndex.isPending ? 'Adding…' : 'Add'}
              </Button>
            </div>
          </div>

          {noIndexQuery.isPending ? (
            <AdminLoadingState />
          ) : noIndexQuery.isError ? (
            <AdminErrorState
              error={noIndexQuery.error}
              onRetry={() => noIndexQuery.refetch()}
            />
          ) : noIndexItems.length === 0 ? (
            <AdminEmptyState reason="filter-empty" />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Reason</TableHead>
                    <TableHead>Holiday</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead>Active</TableHead>
                    <TableHead>Note</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {noIndexItems.map((entry) => {
                    const dateStr = String(entry.date ?? '');
                    const isActive = Boolean(entry.active);
                    return (
                      <TableRow key={dateStr}>
                        <TableCell className="font-mono text-xs">{dateStr}</TableCell>
                        <TableCell>
                          {String(entry.reason ?? '—').replaceAll('_', ' ')}
                        </TableCell>
                        <TableCell>{String(entry.holiday_name ?? '—')}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {String(entry.source ?? '—').replaceAll('_', ' ')}
                        </TableCell>
                        <TableCell>
                          <Badge variant={isActive ? 'success' : 'secondary'}>
                            {isActive ? 'active' : 'inactive'}
                          </Badge>
                        </TableCell>
                        <TableCell className="max-w-[240px] truncate text-xs text-muted-foreground">
                          {String(entry.note ?? '')}
                        </TableCell>
                        <TableCell className="text-right">
                          {isActive ? (
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={deactivateNoIndex.isPending}
                              onClick={() => deactivateNoIndex.mutate(dateStr)}
                            >
                              Deactivate
                            </Button>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </AdminPageLayout>
  );
}
