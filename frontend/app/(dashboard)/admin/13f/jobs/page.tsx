'use client';

/**
 * MVP6-06: Jobs page — PRD §11.1 / §11.3 / §12.1.
 *
 * Five Cards + a Job Detail drawer + the two shared dialogs:
 *
 *   1. Job Runs — filters (status / job_type / startedFrom /
 *      startedTo / syncDate / quarter) + table + Review.
 *   2. Worker Heartbeat — workers table with show-history toggle.
 *   3. EDGAR Rate Limit — request budget MetricTiles + pause banner.
 *   4. Historical Backfill — quarter range preview + enqueue
 *      (MVP3-08 surface).
 *   5. Batch Reparse — per-quarter reparse preview + enqueue.
 *
 * The Job Detail drawer surfaces Lock / Worker / Started /
 * Finished tiles, error block, stale-lock release affordance,
 * Retry Targets, Pipeline Stages, Timeline, Input / Summary
 * JSON dumps.
 *
 * Per MVP6-06 SR5 the page owns its own copies of pendingJob /
 * triggerJob / runJob / pendingStaleReleaseJobId helpers. The
 * index page keeps its own copies because the Tasks Card +
 * Manual Triggers still call `runJob`.
 */

import Link from 'next/link';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
} from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  AlertTriangle,
  FolderClock,
  History,
  Loader2,
  RefreshCw,
} from 'lucide-react';

import apiClient from '@/lib/api/client';
import thirteenfAdmin from '@/lib/thirteenfAdmin';
import { AdminPageLayout } from '@/components/admin13f/AdminPageLayout';
import { DrawerShell, MetricTile } from '@/components/admin13f/Admin13FPrimitives';
import {
  JobPendingDialog,
  type PendingJob,
} from '@/components/admin13f/JobPendingDialog';
import { ReleaseStaleLockDialog } from '@/components/admin13f/ReleaseStaleLockDialog';
import {
  useEdgarRateLimitQuery,
  useJobDetailQuery,
  useJobsQuery,
  useWorkersQuery,
} from '@/lib/admin13f/queries';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/components/ui/use-toast';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

const {
  formatPercent,
  normalizeEdgarRateLimit,
  normalizeWorkers,
  visibleWorkerRows,
} = thirteenfAdmin as {
  formatPercent: (value: number) => string;
  normalizeEdgarRateLimit: (data: unknown) => {
    mode: string;
    tone: string;
    recentRequestCount: number;
    windowSeconds: number;
    remainingEstimatedCapacity: number;
    estimatedCapacity: number;
    requestDelayS: number;
    maxRetries: number;
    usageRatio: number | null;
    globalPauseUntil: string | null;
  };
  normalizeWorkers: (items: unknown[]) => Array<{
    workerId: string;
    hostname: string;
    processId: number | null;
    status: string;
    statusTone: string;
    currentJobId: number | null;
    lastHeartbeatAt: string | null;
  }>;
  visibleWorkerRows: (
    workers: ReturnType<typeof normalizeWorkers>,
    showHistory: boolean,
  ) => {
    rows: ReturnType<typeof normalizeWorkers>;
    hiddenCount: number;
    stoppedHiddenCount: number;
    overflowHiddenCount: number;
  };
};

type BadgeVariant = ComponentProps<typeof Badge>['variant'];

function badgeVariant(value: string): BadgeVariant {
  if (
    value === 'default' ||
    value === 'secondary' ||
    value === 'outline' ||
    value === 'success' ||
    value === 'warning' ||
    value === 'danger'
  ) {
    return value;
  }
  return 'secondary';
}

function formatInteger(value: unknown): string {
  if (typeof value !== 'number') return '—';
  return value.toLocaleString('en-US');
}

function formatJson(value: unknown): string {
  if (!value || typeof value !== 'object') return '—';
  return JSON.stringify(value, null, 2);
}

function lockKeyForPayload(payload: Record<string, unknown>): string | null {
  const jobType = String(payload.job_type ?? '');
  if (jobType === 'fetch_quarter_index')
    return `fetch_quarter_index:${String(payload.quarter ?? '')}`;
  if (jobType === 'ingest_holdings')
    return `ingest_holdings:${String(payload.quarter ?? '')}`;
  if (jobType === 'quality_check')
    return `quality_check:${String(payload.quarter ?? '')}`;
  if (jobType === 'enrich_cusip')
    return `enrich_cusip:${String(payload.quarter ?? 'global')}`;
  if (jobType === 'enrich_metadata')
    return `enrich_metadata:${String(payload.quarter ?? 'global')}`;
  if (jobType === 'ingest_accession')
    return `ingest_accession:${String(payload.accession_no ?? '')}`;
  if (jobType === 'reprocess_amendment')
    return `reprocess_amendment:${String(payload.accession_no ?? '')}`;
  if (jobType === 'backfill_quarters') {
    return `backfill_quarters:${String(payload.start_quarter ?? 'latest')}:${String(
      payload.quarters ?? '',
    )}`;
  }
  if (jobType === 'bootstrap_whitelist') return 'bootstrap_whitelist';
  if (jobType === 'match_cik') return 'match_cik';
  if (jobType === 'bootstrap_stocks') return 'bootstrap_stocks';
  if (jobType === 'enrich_stocks_edgar') return 'enrich_stocks_edgar';
  return null;
}

export default function JobsAdminPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  // Filter state.
  const [jobStatusFilter, setJobStatusFilter] = useState('all');
  const [jobTypeFilter, setJobTypeFilter] = useState('all');
  const [jobStartedFrom, setJobStartedFrom] = useState('');
  const [jobStartedTo, setJobStartedTo] = useState('');
  const [jobSyncDate, setJobSyncDate] = useState('');
  const [jobQuarter, setJobQuarter] = useState('');
  // Drawer + dialog state.
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const [pendingJob, setPendingJob] = useState<PendingJob | null>(null);
  const [pendingStaleReleaseJobId, setPendingStaleReleaseJobId] = useState<number | null>(
    null,
  );
  const [showWorkerHistory, setShowWorkerHistory] = useState(false);
  // MVP3-08 Historical Backfill state.
  const [hbStartQ, setHbStartQ] = useState('');
  const [hbEndQ, setHbEndQ] = useState('');
  const [hbDryRun, setHbDryRun] = useState(false);
  const [hbPreview, setHbPreview] = useState<Record<string, unknown> | null>(null);
  // MVP3-08 Batch Reparse state.
  const [brQuarter, setBrQuarter] = useState('');
  const [brPreview, setBrPreview] = useState<Record<string, unknown> | null>(null);

  // Queries.
  const jobsQuery = useJobsQuery({
    status: jobStatusFilter,
    jobType: jobTypeFilter,
    startedFrom: jobStartedFrom,
    startedTo: jobStartedTo,
    syncDate: jobSyncDate,
    quarter: jobQuarter,
  });
  const jobDetailQuery = useJobDetailQuery(selectedJobId);
  const workersQuery = useWorkersQuery();
  const edgarRateLimitQuery = useEdgarRateLimitQuery();

  // Memos.
  const jobs = useMemo(
    () => (Array.isArray(jobsQuery.data?.items) ? jobsQuery.data.items : []),
    [jobsQuery.data],
  );
  const workers = useMemo(
    () => normalizeWorkers(workersQuery.data?.items ?? []),
    [workersQuery.data],
  );
  const workerRows = useMemo(
    () => visibleWorkerRows(workers, showWorkerHistory),
    [workers, showWorkerHistory],
  );
  const edgarRateLimit = useMemo(
    () => normalizeEdgarRateLimit(edgarRateLimitQuery.data ?? {}),
    [edgarRateLimitQuery.data],
  );
  const activeLockKeys = useMemo(() => {
    const keys = new Set<string>();
    jobs.forEach((job: Record<string, unknown>) => {
      if (
        typeof job.lock_key === 'string' &&
        ['queued', 'running', 'cancel_requested'].includes(String(job.status ?? ''))
      ) {
        keys.add(job.lock_key);
      }
    });
    return keys;
  }, [jobs]);

  const selectedJob = jobDetailQuery.data ?? null;

  // Refresh.
  const refreshJobsData = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['admin-13f-jobs'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-job-detail'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-workers'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-edgar-rate-limit'] }),
    ]);
  }, [queryClient]);

  // Auto-refresh on completed jobs.
  const prevActiveKeys = useRef(new Set<string>());
  useEffect(() => {
    const currentKeys = activeLockKeys;
    const wasActive = prevActiveKeys.current;
    const someJobFinished = Array.from(wasActive).some((key) => !currentKeys.has(key));
    if (someJobFinished) {
      refreshJobsData();
    }
    prevActiveKeys.current = currentKeys;
  }, [activeLockKeys, refreshJobsData]);

  // Mutations.
  const triggerJob = useMutation({
    mutationFn: async (payload: Record<string, unknown>) =>
      (await apiClient.post('/admin/13f/jobs', payload)).data,
    onSuccess: refreshJobsData,
  });
  const releaseStaleLock = useMutation({
    mutationFn: async (jobId: number) =>
      (await apiClient.post(`/admin/13f/jobs/${jobId}/release-stale-lock`)).data,
    onSuccess: refreshJobsData,
  });
  const hbPreviewMutation = useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      (await apiClient.post('/admin/13f/backfill/preview', body)).data,
    onSuccess: (data) => setHbPreview(data),
  });
  const hbEnqueueMutation = useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      (await apiClient.post('/admin/13f/backfill/enqueue', body)).data,
    onSuccess: async () => {
      setHbPreview(null);
      toast({ title: 'Backfill job queued', description: 'Historical backfill enqueued.' });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['admin-13f-jobs'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-backfill-needs-validation'] }),
      ]);
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Enqueue failed.';
      toast({ title: 'Backfill error', description: msg, variant: 'destructive' });
    },
  });
  const brPreviewMutation = useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      (await apiClient.post('/admin/13f/jobs/reparse-by-quarter/preview', body)).data,
    onSuccess: (data) => setBrPreview(data),
  });
  const brEnqueueMutation = useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      (await apiClient.post('/admin/13f/jobs/reparse-by-quarter/enqueue', body)).data,
    onSuccess: async () => {
      setBrPreview(null);
      toast({
        title: 'Batch reparse queued',
        description: `Quarter ${brQuarter} reparse enqueued.`,
      });
      await queryClient.invalidateQueries({ queryKey: ['admin-13f-jobs'] });
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Enqueue failed.';
      toast({ title: 'Reparse error', description: msg, variant: 'destructive' });
    },
  });

  // runJob — dry-run preview then open JobPendingDialog.
  async function runJob(payload: Record<string, unknown>, label: string) {
    const lockKey = lockKeyForPayload(payload);
    if (lockKey && activeLockKeys.has(lockKey)) {
      toast({
        appType: 'warning',
        title: 'Job already active',
        description: `A job with lock ${lockKey} is already queued or running.`,
      });
      return;
    }
    try {
      const dryRun = (
        await apiClient.post('/admin/13f/jobs', { ...payload, dry_run: true })
      ).data;
      if (dryRun.conflict) {
        toast({
          appType: 'warning',
          title: 'Job already active',
          description: `A job with lock ${dryRun.lock_key ?? lockKey ?? 'this action'} is already active.`,
        });
        return;
      }
      setPendingJob({
        label,
        payload,
        preview: (dryRun.preview ?? dryRun) as Record<string, unknown>,
      });
    } catch {
      setPendingJob({
        label,
        payload,
        preview: {
          lock_key: lockKey,
          rate_limit_warning:
            'Preview failed; the backend will still enforce locks before queueing.',
        },
        previewFailed: true,
      });
    }
  }

  function requestStaleJobLockRelease(jobId: unknown) {
    const parsedJobId = Number(jobId);
    if (!Number.isFinite(parsedJobId)) return;
    setPendingStaleReleaseJobId(parsedJobId);
  }

  return (
    <AdminPageLayout
      title="Jobs"
      description="Job runs, worker heartbeat, EDGAR rate-limit budget, and ad-hoc backfill triggers."
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href="/admin/13f">← Back to Overview</Link>
        </Button>
      }
    >
      {/* Job Runs */}
      <div id="jobs" className="grid grid-cols-1 scroll-mt-6 gap-4">
        <Card className="rounded-md">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <History className="h-4 w-4" />
              Job Runs
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
              <Select value={jobStatusFilter} onValueChange={setJobStatusFilter}>
                <SelectTrigger aria-label="Filter jobs by status">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="queued">Queued</SelectItem>
                  <SelectItem value="running">Running</SelectItem>
                  <SelectItem value="succeeded">Succeeded</SelectItem>
                  <SelectItem value="partial_success">Partial success</SelectItem>
                  <SelectItem value="failed">Failed</SelectItem>
                  <SelectItem value="cancel_requested">Cancel requested</SelectItem>
                  <SelectItem value="canceled">Canceled</SelectItem>
                  <SelectItem value="skipped">Skipped</SelectItem>
                </SelectContent>
              </Select>
              <Select value={jobTypeFilter} onValueChange={setJobTypeFilter}>
                <SelectTrigger aria-label="Filter jobs by type">
                  <SelectValue placeholder="Job type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All job types</SelectItem>
                  <SelectItem value="backfill_daily_indexes">Backfill daily indexes</SelectItem>
                  <SelectItem value="backfill_quarters">Backfill quarters</SelectItem>
                  <SelectItem value="bootstrap_stocks">Bootstrap stocks</SelectItem>
                  <SelectItem value="bootstrap_whitelist">Bootstrap whitelist</SelectItem>
                  <SelectItem value="enrich_cusip">Enrich CUSIP</SelectItem>
                  <SelectItem value="enrich_metadata">Enrich metadata</SelectItem>
                  <SelectItem value="enrich_stocks_edgar">Enrich stocks EDGAR</SelectItem>
                  <SelectItem value="fetch_quarter_index">Fetch quarter index</SelectItem>
                  <SelectItem value="fetch_daily_index">Fetch daily index</SelectItem>
                  <SelectItem value="ingest_accession">Ingest accession</SelectItem>
                  <SelectItem value="ingest_holdings">Ingest holdings</SelectItem>
                  <SelectItem value="ingest_holdings_for_quarter">
                    Ingest holdings for quarter
                  </SelectItem>
                  <SelectItem value="match_cik">Match CIK</SelectItem>
                  <SelectItem value="quality_check">Quality check</SelectItem>
                  <SelectItem value="reprocess_amendment">Reprocess amendment</SelectItem>
                  <SelectItem value="retry_failed_filings">Retry failed filings</SelectItem>
                </SelectContent>
              </Select>
              <Input
                type="date"
                aria-label="Started from"
                value={jobStartedFrom}
                onChange={(event) => setJobStartedFrom(event.target.value)}
              />
              <Input
                type="date"
                aria-label="Started to"
                value={jobStartedTo}
                onChange={(event) => setJobStartedTo(event.target.value)}
              />
              <Input
                type="date"
                aria-label="Sync date"
                value={jobSyncDate}
                onChange={(event) => setJobSyncDate(event.target.value)}
              />
              <Input
                aria-label="Job quarter"
                placeholder="2026-Q1"
                value={jobQuarter}
                onChange={(event) => setJobQuarter(event.target.value)}
              />
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Job</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Lock</TableHead>
                  <TableHead>Worker</TableHead>
                  <TableHead>Detail</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.slice(0, 50).map((job: Record<string, unknown>) => (
                  <TableRow key={String(job.id)}>
                    <TableCell className="font-medium">
                      {String(job.job_type ?? '—')}
                    </TableCell>
                    <TableCell>{String(job.status ?? '—')}</TableCell>
                    <TableCell className="max-w-[240px] truncate text-xs text-muted-foreground">
                      {String(job.lock_key ?? '—')}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {String(job.worker_id ?? '—')}
                    </TableCell>
                    <TableCell>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setSelectedJobId(Number(job.id))}
                      >
                        Review
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {jobs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                      No job history available.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      {/* Worker Heartbeat */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
            <span className="flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Worker Heartbeat
            </span>
            {workers.length > 0 && (showWorkerHistory || workerRows.hiddenCount > 0) ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setShowWorkerHistory((value) => !value)}
              >
                <FolderClock className="mr-2 h-4 w-4" />
                {showWorkerHistory
                  ? 'Hide history'
                  : workerRows.stoppedHiddenCount > 0 &&
                      workerRows.overflowHiddenCount > 0
                    ? `Show all (${workerRows.hiddenCount})`
                    : workerRows.stoppedHiddenCount > 0
                      ? `Show history (${workerRows.stoppedHiddenCount})`
                      : `Show more (${workerRows.overflowHiddenCount})`}
              </Button>
            ) : null}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {workerRows.hiddenCount > 0 && !showWorkerHistory ? (
            <div className="mb-3 rounded-md border border-border/70 bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
              Showing active and stale worker heartbeats.
              {workerRows.stoppedHiddenCount > 0
                ? ` ${workerRows.stoppedHiddenCount} stopped historical worker${
                    workerRows.stoppedHiddenCount === 1 ? '' : 's'
                  } hidden.`
                : ''}
              {workerRows.overflowHiddenCount > 0
                ? ` ${workerRows.overflowHiddenCount} additional non-stopped worker${
                    workerRows.overflowHiddenCount === 1 ? '' : 's'
                  } hidden by the display limit.`
                : ''}
            </div>
          ) : null}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Worker</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Current Job</TableHead>
                <TableHead>Last Heartbeat</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {workerRows.rows.map((worker) => (
                <TableRow key={worker.workerId}>
                  <TableCell>
                    <div className="font-medium">{worker.workerId}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {worker.hostname} · pid {worker.processId ?? '—'}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={badgeVariant(worker.statusTone)}>
                      {worker.status.replaceAll('_', ' ')}
                    </Badge>
                  </TableCell>
                  <TableCell>{worker.currentJobId ?? '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {worker.lastHeartbeatAt ?? '—'}
                  </TableCell>
                </TableRow>
              ))}
              {workerRows.rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
                    No worker heartbeat recorded yet. The API worker records one after it starts.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* EDGAR Rate Limit */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
            <span className="flex items-center gap-2">
              <Activity className="h-4 w-4" />
              EDGAR Rate Limit
            </span>
            <Badge
              variant={badgeVariant(
                edgarRateLimitQuery.isError ? 'warning' : edgarRateLimit.tone,
              )}
            >
              {edgarRateLimitQuery.isError ? 'unavailable' : String(edgarRateLimit.mode)}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {edgarRateLimitQuery.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading EDGAR request budget...
            </div>
          ) : edgarRateLimitQuery.isError ? (
            <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
              EDGAR budget is unavailable. Job previews still enforce lock and rate-limit safeguards.
            </div>
          ) : (
            <>
              <div className="grid gap-3 md:grid-cols-4">
                <MetricTile
                  label="Recent requests"
                  value={formatInteger(edgarRateLimit.recentRequestCount)}
                  detail={`${formatInteger(edgarRateLimit.windowSeconds)}s window`}
                />
                <MetricTile
                  label="Remaining capacity"
                  value={formatInteger(edgarRateLimit.remainingEstimatedCapacity)}
                  detail={`of ${formatInteger(edgarRateLimit.estimatedCapacity)}`}
                />
                <MetricTile
                  label="Request delay"
                  value={`${edgarRateLimit.requestDelayS}s`}
                  detail={`${formatInteger(edgarRateLimit.maxRetries)} retries`}
                />
                <MetricTile
                  label="Usage"
                  value={
                    edgarRateLimit.usageRatio === null
                      ? '—'
                      : formatPercent(edgarRateLimit.usageRatio)
                  }
                />
              </div>
              {edgarRateLimit.globalPauseUntil ? (
                <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
                  EDGAR requests are paused until {String(edgarRateLimit.globalPauseUntil)}.
                </div>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>

      {/* Historical Backfill */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <History className="h-4 w-4" />
            Historical Backfill
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <div>
              <label
                className="text-xs font-semibold uppercase text-muted-foreground"
                htmlFor="hb-start-q"
              >
                Start quarter
              </label>
              <Input
                id="hb-start-q"
                className="mt-2"
                placeholder="2023-Q1 (default)"
                value={hbStartQ}
                onChange={(e) => {
                  setHbStartQ(e.target.value);
                  setHbPreview(null);
                }}
              />
            </div>
            <div>
              <label
                className="text-xs font-semibold uppercase text-muted-foreground"
                htmlFor="hb-end-q"
              >
                End quarter
              </label>
              <Input
                id="hb-end-q"
                className="mt-2"
                placeholder="latest (default)"
                value={hbEndQ}
                onChange={(e) => {
                  setHbEndQ(e.target.value);
                  setHbPreview(null);
                }}
              />
            </div>
            <div className="flex flex-col justify-end gap-2">
              <label className="flex items-center gap-2 text-xs font-semibold uppercase text-muted-foreground">
                <input
                  type="checkbox"
                  checked={hbDryRun}
                  onChange={(e) => setHbDryRun(e.target.checked)}
                  className="h-3.5 w-3.5"
                />
                Dry run (required for pre-2023)
              </label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={hbPreviewMutation.isPending}
                onClick={() =>
                  hbPreviewMutation.mutate({
                    start_quarter: hbStartQ.trim() || undefined,
                    end_quarter: hbEndQ.trim() || undefined,
                  })
                }
              >
                {hbPreviewMutation.isPending ? (
                  <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                ) : null}
                Preview scope
              </Button>
            </div>
          </div>
          {hbPreview ? (
            <div className="space-y-2">
              {hbPreview['value_unit_risk_warning'] ? (
                <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
                  <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
                  Pre-2023 range detected — value-unit parsing risk. Enable{' '}
                  <strong>Dry run</strong> before enqueueing.
                </div>
              ) : null}
              <div className="rounded-md border border-border/70 p-3 text-sm">
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <div className="text-xs text-muted-foreground">Range</div>
                    <div className="font-mono text-xs">
                      {String(hbPreview['start_quarter'])} →{' '}
                      {String(hbPreview['end_quarter'])}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Quarters</div>
                    <div className="font-semibold">
                      {(hbPreview['quarters'] as unknown[])?.length ?? 0}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">Managers in scope</div>
                    <div className="font-semibold">
                      {String(hbPreview['manager_count'])}
                    </div>
                  </div>
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                disabled={
                  hbEnqueueMutation.isPending ||
                  (!!hbPreview['requires_dry_run'] && !hbDryRun)
                }
                onClick={() =>
                  hbEnqueueMutation.mutate({
                    start_quarter: hbStartQ.trim() || undefined,
                    end_quarter: hbEndQ.trim() || undefined,
                    dry_run: hbDryRun,
                  })
                }
              >
                {hbEnqueueMutation.isPending ? (
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                ) : null}
                Enqueue backfill{hbDryRun ? ' (dry run)' : ''}
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* Batch Reparse */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <RefreshCw className="h-4 w-4" />
            Batch Reparse
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-md border border-border/70 p-3">
              <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                By Quarter
              </div>
              <label className="text-xs text-muted-foreground" htmlFor="br-quarter">
                Target quarter
              </label>
              <Input
                id="br-quarter"
                className="mt-1"
                placeholder="YYYY-Qn"
                value={brQuarter}
                onChange={(e) => {
                  setBrQuarter(e.target.value);
                  setBrPreview(null);
                }}
              />
              <div className="mt-3 flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!brQuarter.trim() || brPreviewMutation.isPending}
                  onClick={() => brPreviewMutation.mutate({ quarter: brQuarter.trim() })}
                >
                  {brPreviewMutation.isPending ? (
                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  ) : null}
                  Preview
                </Button>
              </div>
              {brPreview ? (
                <div className="mt-3 space-y-2">
                  <div className="rounded-md border border-border/70 p-2 text-sm">
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <div className="text-xs text-muted-foreground">Candidates</div>
                        <div className="font-semibold">
                          {String(
                            (brPreview['estimated_scope'] as Record<string, unknown>)?.[
                              'candidate_count'
                            ] ?? 0,
                          )}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs text-muted-foreground">
                          Missing raw infotable
                        </div>
                        <div className="font-semibold">
                          {String(
                            (brPreview['estimated_scope'] as Record<string, unknown>)?.[
                              'missing_raw_infotable_count'
                            ] ?? 0,
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                  {(brPreview['warnings'] as string[] | undefined)?.map((w, i) => (
                    <div
                      key={i}
                      className="rounded-md border border-amber-300/70 bg-amber-50 px-2 py-1 text-xs text-amber-950"
                    >
                      {w}
                    </div>
                  ))}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={brEnqueueMutation.isPending}
                    onClick={() =>
                      brEnqueueMutation.mutate({ quarter: brQuarter.trim() })
                    }
                  >
                    {brEnqueueMutation.isPending ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : null}
                    Enqueue reparse
                  </Button>
                </div>
              ) : null}
            </div>
            <div className="rounded-md border border-border/40 p-3 opacity-50">
              <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                By Manager
              </div>
              <div className="text-xs text-muted-foreground">
                Coming soon — D3: quarter scope ships first in admin UI.
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Job Detail Drawer */}
      {selectedJobId !== null ? (
        <DrawerShell
          title="Job Detail"
          description={
            selectedJob
              ? `${selectedJob.job_type} · ${selectedJob.status}`
              : 'Loading job detail...'
          }
          closeLabel="Close job detail"
          labelledBy="job-detail-title"
          maxWidthClassName="max-w-[520px]"
          onClose={() => setSelectedJobId(null)}
        >
          {selectedJob ? (
            <>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-md border border-border/70 p-3">
                  <div className="text-xs uppercase text-muted-foreground">Lock key</div>
                  <div className="mt-1 break-all font-mono text-xs">
                    {selectedJob.lock_key ?? '—'}
                  </div>
                </div>
                <div className="rounded-md border border-border/70 p-3">
                  <div className="text-xs uppercase text-muted-foreground">Worker</div>
                  <div className="mt-1 break-all font-mono text-xs">
                    {selectedJob.worker_id ?? '—'}
                  </div>
                </div>
                <div className="rounded-md border border-border/70 p-3">
                  <div className="text-xs uppercase text-muted-foreground">Started</div>
                  <div className="mt-1 text-sm">{selectedJob.started_at ?? '—'}</div>
                </div>
                <div className="rounded-md border border-border/70 p-3">
                  <div className="text-xs uppercase text-muted-foreground">Finished</div>
                  <div className="mt-1 text-sm">{selectedJob.finished_at ?? '—'}</div>
                </div>
              </div>
              {selectedJob.error_message ||
              (typeof selectedJob.summary_json === 'object' &&
                selectedJob.summary_json !== null &&
                (selectedJob.summary_json as Record<string, unknown>).pipeline_error) ? (
                <div className="rounded-md border border-rose-300/70 bg-rose-50 px-3 py-2 text-sm text-rose-950">
                  {selectedJob.error_message ??
                    String(
                      (selectedJob.summary_json as Record<string, unknown>)
                        .pipeline_error ?? '',
                    )}
                </div>
              ) : null}
              {selectedJob.can_release_stale_lock ? (
                <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-3 text-sm text-amber-950">
                  <div className="font-medium">This running job lock appears stale.</div>
                  <div className="mt-1">
                    Last heartbeat age:{' '}
                    {formatInteger(Number(selectedJob.stale_seconds ?? 0))}s.
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="mt-3 bg-background"
                    disabled={releaseStaleLock.isPending}
                    onClick={() => requestStaleJobLockRelease(selectedJob.id)}
                  >
                    Release stale lock
                  </Button>
                </div>
              ) : null}
              <div>
                <div className="text-xs font-semibold uppercase text-muted-foreground">
                  Retry Targets
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {(selectedJob.retry_targets ?? []).map(
                    (target: Record<string, unknown>, index: number) => (
                      <Button
                        key={`${String(target.job_type ?? '')}-${String(target.quarter ?? target.accession_no ?? 'target')}-${index}`}
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          runJob(
                            {
                              job_type: target.job_type,
                              accession_no: target.accession_no,
                              quarter: target.quarter,
                            },
                            String(target.label ?? target.accession_no ?? 'Retry target'),
                          )
                        }
                      >
                        {String(target.label ?? target.accession_no ?? 'Retry target')}
                      </Button>
                    ),
                  )}
                  {(selectedJob.retry_targets ?? []).length === 0 ? (
                    <div className="text-sm text-muted-foreground">
                      No retry target detected.
                    </div>
                  ) : null}
                </div>
              </div>
              {Array.isArray(
                (selectedJob.summary_json as Record<string, unknown> | null)?.stages,
              ) &&
              ((selectedJob.summary_json as Record<string, unknown>).stages as unknown[])
                .length > 0 ? (
                <div>
                  <div className="text-xs font-semibold uppercase text-muted-foreground">
                    Pipeline Stages
                  </div>
                  <div className="mt-2 space-y-2">
                    {(
                      (selectedJob.summary_json as Record<string, unknown>)
                        .stages as Record<string, unknown>[]
                    ).map((stage, index) => (
                      <div
                        key={`${String(stage.job_type ?? 'stage')}-${index}`}
                        className="flex items-center justify-between rounded-md border border-border/70 px-3 py-2"
                      >
                        <div className="flex items-center gap-2">
                          <Badge
                            variant={badgeVariant(
                              stage.status === 'succeeded'
                                ? 'success'
                                : stage.status === 'partial_success'
                                  ? 'warning'
                                  : stage.status === 'failed' || stage.status === 'conflict'
                                    ? 'danger'
                                    : 'secondary',
                            )}
                          >
                            {String(stage.status ?? 'unknown').replaceAll('_', ' ')}
                          </Badge>
                          <span className="text-sm">
                            {String(stage.job_type ?? '—').replaceAll('_', ' ')}
                          </span>
                        </div>
                        {stage.job_id != null ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => setSelectedJobId(Number(stage.job_id))}
                          >
                            Open
                          </Button>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              <div>
                <div className="text-xs font-semibold uppercase text-muted-foreground">
                  Timeline
                </div>
                <div className="mt-2 space-y-2">
                  {(selectedJob.events ?? []).map(
                    (event: Record<string, unknown>, index: number) => (
                      <div
                        key={`${String(event.event_type ?? 'event')}-${index}`}
                        className="rounded-md border border-border/70 p-3"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="font-medium">
                            {String(event.event_type ?? 'event').replaceAll('_', ' ')}
                          </div>
                          <Badge
                            variant={badgeVariant(
                              event.severity === 'error'
                                ? 'danger'
                                : event.severity === 'warning'
                                  ? 'warning'
                                  : 'secondary',
                            )}
                          >
                            {String(event.severity ?? 'info')}
                          </Badge>
                        </div>
                        <div className="mt-1 text-sm text-muted-foreground">
                          {String(event.message ?? '—')}
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2 font-mono text-xs text-muted-foreground">
                          <span>{String(event.at ?? '—')}</span>
                          {event.accession_no ? (
                            <span>{String(event.accession_no)}</span>
                          ) : null}
                          {event.worker_id ? <span>{String(event.worker_id)}</span> : null}
                        </div>
                      </div>
                    ),
                  )}
                  {(selectedJob.events ?? []).length === 0 ? (
                    <div className="text-sm text-muted-foreground">
                      No timeline events recorded.
                    </div>
                  ) : null}
                </div>
              </div>
              <div>
                <div className="text-xs font-semibold uppercase text-muted-foreground">
                  Input
                </div>
                <div className="mt-2 max-h-64 overflow-auto rounded-md border border-border/70 bg-muted/40 p-3 font-mono text-xs">
                  {formatJson(selectedJob.input_json)}
                </div>
              </div>
              <div>
                <div className="text-xs font-semibold uppercase text-muted-foreground">
                  Summary
                </div>
                <div className="mt-2 max-h-64 overflow-auto rounded-md border border-border/70 bg-muted/40 p-3 font-mono text-xs">
                  {formatJson(selectedJob.summary_json)}
                </div>
              </div>
            </>
          ) : (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading job detail...
            </div>
          )}
        </DrawerShell>
      ) : null}

      <JobPendingDialog
        pendingJob={pendingJob}
        triggerJobPending={triggerJob.isPending}
        onCancel={() => setPendingJob(null)}
        onConfirm={() => {
          if (!pendingJob) return;
          triggerJob.mutate({ ...pendingJob.payload, dry_run: false });
          setPendingJob(null);
        }}
      />

      <ReleaseStaleLockDialog
        pendingJobId={pendingStaleReleaseJobId}
        releasePending={releaseStaleLock.isPending}
        onCancel={() => setPendingStaleReleaseJobId(null)}
        onConfirm={() => {
          if (pendingStaleReleaseJobId === null) return;
          releaseStaleLock.mutate(pendingStaleReleaseJobId);
          setPendingStaleReleaseJobId(null);
        }}
      />
    </AdminPageLayout>
  );
}
