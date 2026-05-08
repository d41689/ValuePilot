'use client';

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  FolderClock,
  History,
  Loader2,
  Play,
  RefreshCw,
  ShieldAlert,
  Settings,
  X,
} from 'lucide-react';
import type { ComponentProps, ReactNode } from 'react';

import apiClient from '@/lib/api/client';
import thirteenfAdmin from '@/lib/thirteenfAdmin';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
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
  freshnessLine,
  jobPreviewRows,
  managerCikReviewDefaults,
  normalizeAmendments,
  normalizeQualityReports,
  normalizeQuarters,
  normalizeReadiness,
  normalizeTasks,
  normalizeWorkers,
  operationsHealth,
  taskPrimaryAction,
  visibleWorkerRows,
} = thirteenfAdmin;

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

function formatInteger(value: unknown) {
  if (typeof value !== 'number') return '—';
  return value.toLocaleString('en-US');
}

function formatJson(value: unknown) {
  if (!value || typeof value !== 'object') return '—';
  return JSON.stringify(value, null, 2);
}

function SectionLabel({ children }: { children: ReactNode }) {
  return <div className="text-xs font-semibold uppercase text-muted-foreground">{children}</div>;
}

function MetricTile({
  label,
  value,
  detail,
}: {
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <div className="rounded-md border border-border/70 p-3">
      <div className="text-xs uppercase text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
      {detail ? <div className="text-xs text-muted-foreground">{detail}</div> : null}
    </div>
  );
}

function DrawerShell({
  title,
  description,
  closeLabel,
  labelledBy,
  maxWidthClassName,
  onClose,
  children,
}: {
  title: string;
  description?: ReactNode;
  closeLabel: string;
  labelledBy: string;
  maxWidthClassName: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 bg-background/60 backdrop-blur-sm">
      <div aria-hidden="true" className="absolute inset-0 cursor-default" onClick={onClose} />
      <Card
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        className={`fixed inset-y-0 right-0 flex h-dvh max-h-dvh w-full flex-col overflow-hidden rounded-none border-y-0 border-r-0 shadow-xl ${maxWidthClassName}`}
      >
        <CardHeader className="shrink-0 border-b border-border/70 pb-3">
          <CardTitle className="flex items-center justify-between gap-2 text-base">
            <span id={labelledBy}>{title}</span>
            <Button type="button" variant="ghost" size="icon" aria-label={closeLabel} onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </CardTitle>
          {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
        </CardHeader>
        <CardContent className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">{children}</CardContent>
      </Card>
    </div>
  );
}

export default function Admin13FPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const [selectedAmendmentAccession, setSelectedAmendmentAccession] = useState<string | null>(null);
  const [selectedQuarter, setSelectedQuarter] = useState<string | null>(null);
  const readinessQuery = useQuery({
    queryKey: ['admin-13f-readiness'],
    queryFn: async () => (await apiClient.get('/admin/13f/readiness')).data,
  });
  const quartersQuery = useQuery({
    queryKey: ['admin-13f-quarters'],
    queryFn: async () => (await apiClient.get('/admin/13f/quarters')).data,
  });
  const tasksQuery = useQuery({
    queryKey: ['admin-13f-tasks'],
    queryFn: async () => (await apiClient.get('/admin/13f/tasks')).data,
  });
  const managersQuery = useQuery({
    queryKey: ['admin-13f-managers'],
    queryFn: async () => (await apiClient.get('/admin/13f/managers')).data,
  });
  const jobsQuery = useQuery({
    queryKey: ['admin-13f-jobs'],
    queryFn: async () => (await apiClient.get('/admin/13f/jobs')).data,
    refetchInterval: 5000,
  });
  const qualityQuery = useQuery({
    queryKey: ['admin-13f-quality'],
    queryFn: async () => (await apiClient.get('/admin/13f/quality')).data,
  });
  const amendmentsQuery = useQuery({
    queryKey: ['admin-13f-amendments'],
    queryFn: async () => (await apiClient.get('/admin/13f/amendments')).data,
  });
  const workersQuery = useQuery({
    queryKey: ['admin-13f-workers'],
    queryFn: async () => (await apiClient.get('/admin/13f/workers')).data,
    refetchInterval: 5000,
  });
  const jobDetailQuery = useQuery({
    queryKey: ['admin-13f-job-detail', selectedJobId],
    queryFn: async () => (await apiClient.get(`/admin/13f/jobs/${selectedJobId}`)).data,
    enabled: selectedJobId !== null,
    refetchInterval: selectedJobId === null ? false : 5000,
  });
  const amendmentDetailQuery = useQuery({
    queryKey: ['admin-13f-amendment-detail', selectedAmendmentAccession],
    queryFn: async () => (await apiClient.get(`/admin/13f/amendments/${selectedAmendmentAccession}`)).data,
    enabled: selectedAmendmentAccession !== null,
  });
  const quarterDetailQuery = useQuery({
    queryKey: ['admin-13f-quarter-detail', selectedQuarter],
    queryFn: async () => (await apiClient.get(`/admin/13f/quarters/${selectedQuarter}/detail`)).data,
    enabled: selectedQuarter !== null,
  });
  const [manualQuarter, setManualQuarter] = useState('');
  const [backfillQuarters, setBackfillQuarters] = useState('4');
  const [backfillStartQuarter, setBackfillStartQuarter] = useState('');
  const [accessionNo, setAccessionNo] = useState('');
  const [pendingJob, setPendingJob] = useState<{
    label: string;
    payload: Record<string, unknown>;
    preview: Record<string, unknown>;
    previewFailed?: boolean;
  } | null>(null);
  const [pendingStaleReleaseJobId, setPendingStaleReleaseJobId] = useState<number | null>(null);
  const [showWorkerHistory, setShowWorkerHistory] = useState(false);
  const [pendingConfirmManager, setPendingConfirmManager] = useState<Record<string, unknown> | null>(null);
  const [confirmCik, setConfirmCik] = useState('');
  const [confirmNote, setConfirmNote] = useState('');
  const [pendingRejectManager, setPendingRejectManager] = useState<Record<string, unknown> | null>(null);
  const [rejectNote, setRejectNote] = useState('');
  const [pendingRevokeManager, setPendingRevokeManager] = useState<Record<string, unknown> | null>(null);
  const [revokeNote, setRevokeNote] = useState('');
  async function refreshAdminData() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['admin-13f-readiness'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-quarters'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-tasks'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-jobs'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-quality'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-amendments'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-quarter-detail'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-workers'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-job-detail'] }),
    ]);
  }
  const triggerJob = useMutation({
    mutationFn: async (payload: Record<string, unknown>) =>
      (await apiClient.post('/admin/13f/jobs', payload)).data,
    onSuccess: refreshAdminData,
  });
  const releaseStaleLock = useMutation({
    mutationFn: async (jobId: number) =>
      (await apiClient.post(`/admin/13f/jobs/${jobId}/release-stale-lock`)).data,
    onSuccess: refreshAdminData,
  });
  const confirmManager = useMutation({
    mutationFn: async ({
      managerId,
      cik,
      note,
    }: {
      managerId: number;
      cik: string | null;
      note: string | null;
    }) => (await apiClient.post(`/admin/13f/managers/${managerId}/confirm-cik`, { cik, note })).data,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['admin-13f-readiness'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-tasks'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-managers'] }),
      ]);
    },
  });
  const rejectManager = useMutation({
    mutationFn: async ({ managerId, note }: { managerId: number; note: string | null }) =>
      (await apiClient.post(`/admin/13f/managers/${managerId}/reject-cik`, { note })).data,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['admin-13f-readiness'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-tasks'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-managers'] }),
      ]);
    },
  });
  const revokeManager = useMutation({
    mutationFn: async ({ managerId, note }: { managerId: number; note: string }) =>
      (await apiClient.post(`/admin/13f/managers/${managerId}/revoke-cik`, { note })).data,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['admin-13f-readiness'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-tasks'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-managers'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-quarters'] }),
      ]);
    },
  });

  const readiness = useMemo(
    () => normalizeReadiness(readinessQuery.data ?? {}),
    [readinessQuery.data]
  );
  const quarters = useMemo(
    () => normalizeQuarters(quartersQuery.data?.items ?? []),
    [quartersQuery.data]
  );
  const tasks = useMemo(() => normalizeTasks(tasksQuery.data?.items ?? []), [tasksQuery.data]);
  const qualityReports = useMemo(
    () => normalizeQualityReports(qualityQuery.data?.items ?? []),
    [qualityQuery.data]
  );
  const amendments = useMemo(
    () => normalizeAmendments(amendmentsQuery.data?.items ?? []),
    [amendmentsQuery.data]
  );
  const workers = useMemo(
    () => normalizeWorkers(workersQuery.data?.items ?? []),
    [workersQuery.data]
  );
  const hasAvailableWorker = workers.some((worker) => worker.status === 'idle' || worker.status === 'running');
  const workerRows = useMemo(
    () => visibleWorkerRows(workers, showWorkerHistory),
    [workers, showWorkerHistory]
  );
  const managers = useMemo(
    () => (Array.isArray(managersQuery.data?.items) ? managersQuery.data.items : []),
    [managersQuery.data]
  );
  const jobs = useMemo(
    () => (Array.isArray(jobsQuery.data?.items) ? jobsQuery.data.items : []),
    [jobsQuery.data]
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
  const selectedAmendment = amendmentDetailQuery.data ?? null;
  const selectedQuarterDetail = quarterDetailQuery.data ?? null;
  const isLoading =
    readinessQuery.isLoading ||
    quartersQuery.isLoading ||
    tasksQuery.isLoading ||
    managersQuery.isLoading ||
    jobsQuery.isLoading ||
    qualityQuery.isLoading ||
    amendmentsQuery.isLoading ||
    workersQuery.isLoading;

  const latestQuarter = readiness.latestUsableQuarter === '—' ? undefined : readiness.latestUsableQuarter;
  const targetQuarter = manualQuarter.trim() || latestQuarter;
  const targetAccession = accessionNo.trim();
  const operationalHealth = useMemo(
    () =>
      operationsHealth(readiness, tasks, hasAvailableWorker, {
        workersIndeterminate: workersQuery.isError,
      }),
    [readiness, tasks, hasAvailableWorker, workersQuery.isError]
  );

  function lockKeyForPayload(payload: Record<string, unknown>) {
    const jobType = String(payload.job_type ?? '');
    if (jobType === 'fetch_quarter_index') return `fetch_quarter_index:${String(payload.quarter ?? '')}`;
    if (jobType === 'ingest_holdings') return `ingest_holdings:${String(payload.quarter ?? '')}`;
    if (jobType === 'quality_check') return `quality_check:${String(payload.quarter ?? '')}`;
    if (jobType === 'enrich_cusip') return `enrich_cusip:${String(payload.quarter ?? 'global')}`;
    if (jobType === 'enrich_metadata') return `enrich_metadata:${String(payload.quarter ?? 'global')}`;
    if (jobType === 'ingest_accession') return `ingest_accession:${String(payload.accession_no ?? '')}`;
    if (jobType === 'reprocess_amendment') return `reprocess_amendment:${String(payload.accession_no ?? '')}`;
    if (jobType === 'backfill_quarters') {
      return `backfill_quarters:${String(payload.start_quarter ?? 'latest')}:${String(payload.quarters ?? '')}`;
    }
    if (jobType === 'bootstrap_whitelist') return 'bootstrap_whitelist';
    if (jobType === 'match_cik') return 'match_cik';
    if (jobType === 'bootstrap_stocks') return 'bootstrap_stocks';
    if (jobType === 'enrich_stocks_edgar') return 'enrich_stocks_edgar';
    return null;
  }

  function isJobActive(payload: Record<string, unknown>) {
    const lockKey = lockKeyForPayload(payload);
    return Boolean(lockKey && activeLockKeys.has(lockKey));
  }

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
      const dryRun = (await apiClient.post('/admin/13f/jobs', { ...payload, dry_run: true })).data;
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
          rate_limit_warning: 'Preview failed; the backend will still enforce locks before queueing.',
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

  function handleConfirmManager(manager: Record<string, unknown>) {
    const managerId = Number(manager.id);
    if (!Number.isFinite(managerId)) return;
    const defaults = managerCikReviewDefaults(manager);
    setConfirmCik(String(defaults.defaultCik ?? ''));
    setConfirmNote('');
    setPendingConfirmManager(manager);
  }

  function handleRejectManager(manager: Record<string, unknown>) {
    const managerId = Number(manager.id);
    if (!Number.isFinite(managerId)) return;
    setRejectNote('');
    setPendingRejectManager(manager);
  }

  function handleRevokeManager(manager: Record<string, unknown>) {
    const managerId = Number(manager.id);
    if (!Number.isFinite(managerId)) return;
    setRevokeNote('');
    setPendingRevokeManager(manager);
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase text-muted-foreground">
            Admin Data Operations
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">13F Operations</h1>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            Readiness, quarter health, admin tasks, manager review, and safe ingestion jobs.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            queryClient.invalidateQueries({ queryKey: ['admin-13f-readiness'] });
            queryClient.invalidateQueries({ queryKey: ['admin-13f-quarters'] });
            queryClient.invalidateQueries({ queryKey: ['admin-13f-tasks'] });
            queryClient.invalidateQueries({ queryKey: ['admin-13f-managers'] });
            queryClient.invalidateQueries({ queryKey: ['admin-13f-jobs'] });
            queryClient.invalidateQueries({ queryKey: ['admin-13f-quality'] });
            queryClient.invalidateQueries({ queryKey: ['admin-13f-amendments'] });
            queryClient.invalidateQueries({ queryKey: ['admin-13f-quarter-detail'] });
            queryClient.invalidateQueries({ queryKey: ['admin-13f-workers'] });
          }}
        >
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
            <span>Data Readiness & Operations Health</span>
            <span className="flex flex-wrap gap-2">
              <Badge variant={badgeVariant(readiness.readinessTone)}>
                Data {readiness.readinessLevel.replaceAll('_', ' ')}
              </Badge>
              <Badge variant={badgeVariant(isLoading ? 'secondary' : operationalHealth.tone)}>
                {isLoading ? 'operations loading' : operationalHealth.label}
              </Badge>
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading 13F operations state...
            </div>
          ) : null}
          <div className="grid gap-3 md:grid-cols-4">
            <MetricTile label="Latest usable" value={readiness.latestUsableQuarter} />
            <MetricTile
              label="Current quarter"
              value={readiness.currentQuarter}
              detail={readiness.currentPhase}
            />
            <MetricTile label="Historical depth" value={`${readiness.historicalDepth} quarters`} />
            <MetricTile
              label="Managers"
              value={`${formatInteger(readiness.counts.confirmed_managers)} confirmed`}
            />
          </div>
          <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
            {freshnessLine(readiness)}
          </div>
          {!isLoading ? (
            <div
              className={`rounded-md border px-3 py-2 text-sm ${
                operationalHealth.level === 'healthy'
                  ? 'border-emerald-300/70 bg-emerald-50 text-emerald-950'
                  : operationalHealth.level === 'blocked'
                    ? 'border-rose-300/70 bg-rose-50 text-rose-950'
                    : operationalHealth.level === 'unknown'
                      ? 'border-border/70 bg-muted/30 text-foreground'
                      : 'border-amber-300/70 bg-amber-50 text-amber-950'
              }`}
            >
              <div className="font-medium">
                {operationalHealth.level === 'healthy'
                  ? 'Operations are clear'
                  : operationalHealth.level === 'blocked'
                    ? 'Operations need intervention'
                    : operationalHealth.level === 'unknown'
                      ? 'Operations health unknown'
                      : 'Operations need attention'}
              </div>
              <div className="mt-1">{operationalHealth.summary}</div>
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2 text-sm">
            <Badge variant={readiness.schedulerEnabled ? 'success' : 'danger'}>
              Scheduler {readiness.schedulerEnabled ? 'enabled' : 'disabled'}
            </Badge>
            <Badge variant={readiness.smartRetryEnabled ? 'success' : 'warning'}>
              Smart retry {readiness.smartRetryEnabled ? 'enabled' : 'disabled'}
            </Badge>
            <Badge variant={hasAvailableWorker ? 'success' : 'warning'}>
              Workers {hasAvailableWorker ? 'available' : 'not active'}
            </Badge>
          </div>
          <div className="grid gap-3 lg:grid-cols-[280px_minmax(0,1fr)]">
            <div className="rounded-md border border-border/70 p-3">
              <div className="text-xs font-semibold uppercase text-muted-foreground">
                Current Quarter
              </div>
              <div className="mt-2 flex items-center justify-between gap-2">
                <div className="text-lg font-semibold">{readiness.currentQuarter}</div>
                <Badge variant={badgeVariant(
                  readiness.currentHealth === 'complete'
                    ? 'success'
                    : readiness.currentHealth === 'setup_required' || readiness.currentHealth === 'needs_review'
                      ? 'danger'
                      : 'warning'
                )}>
                  {readiness.currentHealth.replaceAll('_', ' ')}
                </Badge>
              </div>
              <div className="mt-2 text-sm text-muted-foreground">
                Phase: {readiness.currentPhase.replaceAll('_', ' ')}
              </div>
              <div className="mt-1 text-sm text-muted-foreground">
                Filing deadline: {readiness.filingDeadline ?? '—'}
              </div>
            </div>
            <div className="rounded-md border border-border/70 p-3">
              <div className="mb-3 text-xs font-semibold uppercase text-muted-foreground">
                Setup Checklist
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                {readiness.setupChecklist.map((item: Record<string, string>) => (
                  <div key={item.code} className="rounded-md border border-border/70 bg-muted/20 p-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-medium">{item.label}</div>
                      <Badge variant={badgeVariant(item.statusTone)}>
                        {item.status.replaceAll('_', ' ')}
                      </Badge>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">{item.completeWhen}</div>
                    {item.status !== 'complete' ? (
                      <div className="mt-1 text-xs text-foreground">{item.adminAction}</div>
                    ) : null}
                  </div>
                ))}
                {readiness.setupChecklist.length === 0 ? (
                  <div className="text-sm text-muted-foreground">No setup checklist returned.</div>
                ) : null}
              </div>
            </div>
          </div>
          {readiness.topTask ? (
            <div className="flex items-start gap-2 rounded-md border border-rose-300/70 bg-rose-50 px-3 py-2 text-sm text-rose-950">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <div className="font-medium">{readiness.topTask.title}</div>
                <div>{readiness.topTask.recommended_action}</div>
              </div>
            </div>
          ) : !isLoading && operationalHealth.level === 'healthy' ? (
            <div className="flex items-center gap-2 rounded-md border border-emerald-300/70 bg-emerald-50 px-3 py-2 text-sm text-emerald-950">
              <CheckCircle2 className="h-4 w-4" />
              No blocking admin task detected.
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldAlert className="h-4 w-4" />
            Quality Reports
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Quarter</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Issues</TableHead>
                <TableHead>Checked</TableHead>
                <TableHead>Summary</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {qualityReports.map((report) => (
                <TableRow key={String(report.id)}>
                  <TableCell className="font-medium">{report.quarter}</TableCell>
                  <TableCell>
                    <Badge variant={badgeVariant(report.statusTone)}>
                      {report.status.replaceAll('_', ' ')}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {formatInteger(report.errorCount)} errors · {formatInteger(report.warningCount)} warnings
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {report.checkedAt ?? '—'}
                  </TableCell>
                  <TableCell className="max-w-[360px] truncate text-sm text-muted-foreground">
                    {report.summary || '—'}
                  </TableCell>
                </TableRow>
              ))}
              {qualityReports.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                    No persisted quality report yet. Run a quality check to populate this section.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <AlertTriangle className="h-4 w-4" />
            Amendment Accessions
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Accession</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Manager</TableHead>
                <TableHead>Supersedes</TableHead>
                <TableHead>Raw InfoTable</TableHead>
                <TableHead>Holdings</TableHead>
                <TableHead>Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {amendments.slice(0, 12).map((amendment) => (
                <TableRow key={amendment.accessionNo}>
                  <TableCell>
                    <div className="font-mono text-xs">{amendment.accessionNo}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {amendment.quarter} · filed {amendment.filedAt ?? '—'}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={badgeVariant(amendment.statusTone)}>
                      {amendment.status.replaceAll('_', ' ')}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">{amendment.managerName}</div>
                    <div className="mt-1 font-mono text-xs text-muted-foreground">
                      {amendment.managerCik}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {amendment.supersedesAccessionNo ?? '—'}
                  </TableCell>
                  <TableCell>
                    <div className="text-sm">
                      {String(amendment.rawInfotable.parse_status ?? 'missing')}
                    </div>
                    {amendment.rawInfotable.error_message ? (
                      <div className="mt-1 max-w-[260px] truncate text-xs text-rose-700">
                        {String(amendment.rawInfotable.error_message)}
                      </div>
                    ) : null}
                  </TableCell>
                  <TableCell>{formatInteger(amendment.holdingsCount)}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setSelectedAmendmentAccession(amendment.accessionNo)}
                      >
                        Review
                      </Button>
                      {amendment.recommendedJob ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          disabled={isJobActive(amendment.recommendedJob)}
                          onClick={() =>
                            runJob(amendment.recommendedJob, `Reprocess ${amendment.accessionNo}`)
                          }
                        >
                          Reprocess
                        </Button>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {amendments.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                    No 13F/A amendments recorded yet.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

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
                  : workerRows.stoppedHiddenCount > 0 && workerRows.overflowHiddenCount > 0
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

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card className="rounded-md">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Database className="h-4 w-4" />
              Quarters
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Quarter</TableHead>
                  <TableHead>Phase</TableHead>
                  <TableHead>Health</TableHead>
                  <TableHead>Filed</TableHead>
                  <TableHead>Holdings</TableHead>
                  <TableHead>Linked</TableHead>
                  <TableHead>Amendments</TableHead>
                  <TableHead>Detail</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {quarters.map((quarter) => (
                  <TableRow key={quarter.quarter}>
                    <TableCell className="font-medium">{quarter.quarter}</TableCell>
                    <TableCell>{quarter.phase}</TableCell>
                    <TableCell>
                      <Badge variant={badgeVariant(quarter.healthTone)}>
                        {quarter.health?.replaceAll('_', ' ')}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {formatInteger(quarter.filedManagers)} / {formatInteger(quarter.trackedManagers)}
                    </TableCell>
                    <TableCell>{formatInteger(quarter.holdingsCount)}</TableCell>
                    <TableCell>
                      <div>{formatPercent(quarter.linkedRatio)}</div>
                      {quarter.linkedUnavailableReason ? (
                        <div className="mt-1 text-xs text-muted-foreground">
                          {quarter.linkedUnavailableReason}
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell>{quarter.amendmentStatus?.replaceAll('_', ' ')}</TableCell>
                    <TableCell>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setSelectedQuarter(quarter.quarter)}
                      >
                        Review
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {quarters.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="py-8 text-center text-muted-foreground">
                      No quarter data available.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card className="rounded-md">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4" />
              Admin Tasks
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {tasks.map((task) => {
              const primaryAction = taskPrimaryAction(task, latestQuarter);
              return (
                <div key={task.code} className="rounded-md border border-border/70 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="font-medium">{task.title}</div>
                      <div className="mt-2 text-sm text-muted-foreground">
                        {task.recommendedAction}
                      </div>
                    </div>
                    <Badge variant={badgeVariant(task.priorityTone)}>{task.priority}</Badge>
                  </div>
                  {primaryAction ? (
                    <div className="mt-3">
                      {primaryAction.kind === 'job' ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={!primaryAction.payload || isJobActive(primaryAction.payload)}
                          onClick={() => {
                            if (!primaryAction.payload) return;
                            runJob(primaryAction.payload, primaryAction.label);
                          }}
                        >
                          {primaryAction.label}
                        </Button>
                      ) : primaryAction.kind === 'anchor' ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            document.getElementById(String(primaryAction.target))?.scrollIntoView({
                              behavior: 'smooth',
                              block: 'start',
                            })
                          }
                        >
                          {primaryAction.label}
                        </Button>
                      ) : (
                        <Badge variant="outline">
                          <Settings className="mr-1 h-3 w-3" />
                          {primaryAction.label}
                        </Badge>
                      )}
                    </div>
                  ) : null}
                  {task.metadata && typeof task.metadata === 'object' ? (
                  <div className="mt-3 grid gap-2 rounded-md border border-border/70 bg-muted/30 p-2 text-xs text-muted-foreground">
                    {'manager_name' in task.metadata ? (
                      <div>
                        Manager:{' '}
                        <span className="font-medium text-foreground">
                          {String(task.metadata.manager_name ?? '—')}
                        </span>
                      </div>
                    ) : null}
                    {'old_cik' in task.metadata ? (
                      <div>
                        Prior CIK:{' '}
                        <span className="font-mono text-foreground">
                          {String(task.metadata.old_cik ?? '—')}
                        </span>
                      </div>
                    ) : null}
                    {'affected_filings_count' in task.metadata ? (
                      <div>
                        Affected filings:{' '}
                        <span className="font-medium text-foreground">
                          {formatInteger(Number(task.metadata.affected_filings_count ?? 0))}
                        </span>
                      </div>
                    ) : null}
                    {'job_id' in task.metadata ? (
                      <div>
                        Job:{' '}
                        <span className="font-medium text-foreground">
                          #{String(task.metadata.job_id ?? '—')} · {String(task.metadata.job_type ?? '—')} ·{' '}
                          {String(task.metadata.status ?? '—')}
                        </span>
                      </div>
                    ) : null}
                    {'stale_job_id' in task.metadata ? (
                      <div className="space-y-1">
                        <div>
                          Stale job:{' '}
                          <span className="font-medium text-foreground">
                            #{String(task.metadata.stale_job_id ?? '—')} ·{' '}
                            {String(task.metadata.stale_job_type ?? '—')}
                          </span>
                        </div>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="h-6 text-xs"
                          disabled={releaseStaleLock.isPending}
                          onClick={() => requestStaleJobLockRelease(task.metadata?.stale_job_id)}
                        >
                          Release stale lock
                        </Button>
                      </div>
                    ) : null}
                    {'quarter' in task.metadata && task.metadata.quarter ? (
                      <div>
                        Quarter:{' '}
                        <span className="font-medium text-foreground">
                          {String(task.metadata.quarter)}
                        </span>
                      </div>
                    ) : null}
                    {'failed_accessions_count' in task.metadata ? (
                      <div>
                        Failed accessions:{' '}
                        <span className="font-medium text-foreground">
                          {formatInteger(Number(task.metadata.failed_accessions_count ?? 0))}
                        </span>
                      </div>
                    ) : null}
                    {Array.isArray(task.metadata.retry_targets) &&
                    task.metadata.retry_targets.length > 0 ? (
                      <div className="space-y-1">
                        <div className="text-muted-foreground">Retry targets:</div>
                        <div className="flex flex-wrap gap-1">
                          {(task.metadata.retry_targets as Record<string, unknown>[]).map((target, i) => (
                            <Button
                              key={`${String(target.job_type ?? '')}-${String(target.quarter ?? target.accession_no ?? 'target')}-${i}`}
                              type="button"
                              variant="outline"
                              size="sm"
                              className="h-6 text-xs"
                              disabled={isJobActive({
                                job_type: target.job_type,
                                accession_no: target.accession_no,
                                quarter: target.quarter,
                              })}
                              onClick={() =>
                                runJob(
                                  {
                                    job_type: target.job_type,
                                    accession_no: target.accession_no,
                                    quarter: target.quarter,
                                  },
                                  String(target.label ?? target.accession_no ?? 'Retry')
                                )
                              }
                            >
                              {String(target.label ?? target.accession_no ?? 'Retry')}
                            </Button>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {'error_message' in task.metadata && task.metadata.error_message ? (
                      <div className="text-rose-700">
                        Error: {String(task.metadata.error_message)}
                      </div>
                    ) : null}
                    {'queued_jobs_count' in task.metadata ? (
                      <div>
                        Queued jobs:{' '}
                        <span className="font-medium text-foreground">
                          {formatInteger(Number(task.metadata.queued_jobs_count ?? 0))}
                        </span>
                      </div>
                    ) : null}
                    {'oldest_queued_job_id' in task.metadata ? (
                      <div>
                        Oldest queued:{' '}
                        <span className="font-medium text-foreground">
                          #{String(task.metadata.oldest_queued_job_id ?? '—')} ·{' '}
                          {String(task.metadata.oldest_queued_job_type ?? '—')}
                        </span>
                      </div>
                    ) : null}
                    {'oldest_queued_seconds' in task.metadata ? (
                      <div>
                        Queue age:{' '}
                        <span className="font-medium text-foreground">
                          {formatInteger(Number(task.metadata.oldest_queued_seconds ?? 0))}s
                        </span>
                      </div>
                    ) : null}
                    {'active_worker_count' in task.metadata ? (
                      <div>
                        Workers:{' '}
                        <span className="font-medium text-foreground">
                          {formatInteger(Number(task.metadata.active_worker_count ?? 0))} active /{' '}
                          {formatInteger(Number(task.metadata.worker_count ?? 0))} seen
                        </span>
                      </div>
                    ) : null}
                    {Array.isArray(task.metadata.affected_quarters) &&
                    task.metadata.affected_quarters.length > 0 ? (
                      <div>
                        Quarters:{' '}
                        <span className="text-foreground">
                          {task.metadata.affected_quarters.slice(0, 5).join(', ')}
                        </span>
                      </div>
                    ) : null}
                  </div>
                  ) : null}
                </div>
              );
            })}
            {tasks.length === 0 ? (
              <div className="text-sm text-muted-foreground">No admin tasks.</div>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Play className="h-4 w-4" />
            Manual Controls
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-[1fr_1fr_1fr]">
            <div>
              <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="manual-quarter">
                Target quarter
              </label>
              <Input
                id="manual-quarter"
                className="mt-2"
                placeholder={latestQuarter ?? 'YYYY-Qn'}
                value={manualQuarter}
                onChange={(event) => setManualQuarter(event.target.value)}
              />
            </div>
            <div>
              <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="backfill-quarters">
                Backfill quarters
              </label>
              <Input
                id="backfill-quarters"
                className="mt-2"
                type="number"
                min="1"
                max="40"
                value={backfillQuarters}
                onChange={(event) => setBackfillQuarters(event.target.value)}
              />
            </div>
            <div>
              <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="accession-no">
                Accession no.
              </label>
              <Input
                id="accession-no"
                className="mt-2"
                placeholder="0000000000-00-000000"
                value={accessionNo}
                onChange={(event) => setAccessionNo(event.target.value)}
              />
            </div>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            <div className="rounded-md border border-border/70 p-3">
              <div className="text-xs font-semibold uppercase text-muted-foreground">Setup</div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={isJobActive({ job_type: 'bootstrap_whitelist' })}
                  onClick={() => runJob({ job_type: 'bootstrap_whitelist' }, 'Bootstrap whitelist')}
                >
                  Bootstrap whitelist
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={isJobActive({ job_type: 'match_cik' })}
                  onClick={() => runJob({ job_type: 'match_cik' }, 'Match CIK')}
                >
                  Match CIK
                </Button>
              </div>
            </div>
            <div className="rounded-md border border-border/70 p-3">
              <div className="text-xs font-semibold uppercase text-muted-foreground">Stock Reference Data</div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={isJobActive({ job_type: 'bootstrap_stocks' })}
                  onClick={() => runJob({ job_type: 'bootstrap_stocks' }, 'Bootstrap stocks')}
                >
                  Bootstrap stocks
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={isJobActive({ job_type: 'enrich_stocks_edgar' })}
                  onClick={() => runJob({ job_type: 'enrich_stocks_edgar' }, 'Enrich stocks from EDGAR')}
                >
                  Enrich stocks from EDGAR
                </Button>
              </div>
            </div>
            <div className="rounded-md border border-border/70 p-3">
              <div className="text-xs font-semibold uppercase text-muted-foreground">Quarter Pipeline</div>
              <div className="mt-2 text-xs text-muted-foreground">
                Uses target quarter {targetQuarter ? `(${targetQuarter})` : 'after a quarter is entered'}.
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={!targetQuarter || isJobActive({ job_type: 'fetch_quarter_index', quarter: targetQuarter })}
                  onClick={() =>
                    runJob({ job_type: 'fetch_quarter_index', quarter: targetQuarter }, 'Fetch quarter index')
                  }
                >
                  Fetch quarter index
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!targetQuarter || isJobActive({ job_type: 'ingest_holdings', quarter: targetQuarter })}
                  onClick={() =>
                    runJob({ job_type: 'ingest_holdings', quarter: targetQuarter }, 'Ingest holdings')
                  }
                >
                  Ingest holdings
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!targetQuarter || isJobActive({ job_type: 'enrich_metadata', quarter: targetQuarter })}
                  onClick={() =>
                    runJob({ job_type: 'enrich_metadata', quarter: targetQuarter }, 'Retry Enrichment')
                  }
                >
                  Retry Enrichment
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!targetQuarter || isJobActive({ job_type: 'quality_check', quarter: targetQuarter })}
                  onClick={() =>
                    runJob({ job_type: 'quality_check', quarter: targetQuarter }, 'Quality check')
                  }
                >
                  Quality check
                </Button>
              </div>
            </div>
            <div className="rounded-md border border-border/70 p-3">
              <div className="text-xs font-semibold uppercase text-muted-foreground">Backfill</div>
              <div className="mt-3">
                <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="backfill-start-quarter">
                  Optional start quarter
                </label>
                <Input
                  id="backfill-start-quarter"
                  className="mt-2"
                  placeholder="Defaults to latest usable"
                  value={backfillStartQuarter}
                  onChange={(event) => setBackfillStartQuarter(event.target.value)}
                />
              </div>
              <Button
                type="button"
                variant="outline"
                className="mt-3"
                disabled={isJobActive({
                  job_type: 'backfill_quarters',
                  quarters: Number(backfillQuarters || '4'),
                  start_quarter: backfillStartQuarter.trim() || undefined,
                })}
                onClick={() =>
                  runJob(
                    {
                      job_type: 'backfill_quarters',
                      quarters: Number(backfillQuarters || '4'),
                      start_quarter: backfillStartQuarter.trim() || undefined,
                    },
                    'Backfill quarters'
                  )
                }
              >
                Backfill
              </Button>
            </div>
            <div className="rounded-md border border-border/70 p-3 lg:col-span-2">
              <div className="text-xs font-semibold uppercase text-muted-foreground">Accession / Amendment Repair</div>
              <div className="mt-2 text-xs text-muted-foreground">
                Enter an accession number to enable single-filing repair actions.
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={!targetAccession || isJobActive({ job_type: 'ingest_accession', accession_no: targetAccession })}
                  onClick={() =>
                    runJob({ job_type: 'ingest_accession', accession_no: targetAccession }, 'Retry accession')
                  }
                >
                  Retry accession
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={!targetAccession || isJobActive({ job_type: 'reprocess_amendment', accession_no: targetAccession })}
                  onClick={() =>
                    runJob(
                      { job_type: 'reprocess_amendment', accession_no: targetAccession },
                      'Reprocess amendment'
                    )
                  }
                >
                  Reprocess amendment
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <div id="managers" className="grid scroll-mt-6 gap-4 xl:grid-cols-2">
        <Card className="rounded-md">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Managers</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>CIK</TableHead>
                  <TableHead>Candidate Evidence</TableHead>
                  <TableHead>Latest Audit</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {managers.slice(0, 12).map((manager: Record<string, unknown>) => {
                  const latestEvent =
                    manager.latest_cik_review_event &&
                    typeof manager.latest_cik_review_event === 'object'
                      ? (manager.latest_cik_review_event as Record<string, unknown>)
                      : null;
                  const affectedQuarters = Array.isArray(latestEvent?.affected_quarters)
                    ? latestEvent.affected_quarters
                    : [];
                  return (
                    <TableRow key={String(manager.id)}>
                      <TableCell className="font-medium">{String(manager.legal_name ?? '—')}</TableCell>
                      <TableCell>{String(manager.cik ?? '—')}</TableCell>
                      <TableCell>
                        <div className="space-y-1 text-sm">
                          <div>{String(manager.candidate_legal_name ?? '—')}</div>
                          <div className="text-xs text-muted-foreground">
                            CIK {String(manager.candidate_cik ?? '—')} · score{' '}
                            {typeof manager.candidate_similarity_score === 'number'
                              ? manager.candidate_similarity_score.toFixed(2)
                              : '—'}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {String(manager.candidate_source ?? 'No candidate source')}
                          </div>
                          {typeof manager.candidate_evidence_url === 'string' ? (
                            <Button asChild variant="link" size="sm" className="h-auto p-0 text-xs">
                              <a href={manager.candidate_evidence_url} target="_blank" rel="noreferrer">
                                Open evidence
                              </a>
                            </Button>
                          ) : null}
                          {typeof manager.review_note === 'string' && manager.review_note ? (
                            <div className="text-xs text-muted-foreground">
                              Review note: {manager.review_note}
                            </div>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        {latestEvent ? (
                          <div className="space-y-1 text-xs">
                            <div className="font-medium">
                              {String(latestEvent.event_type ?? '—').replaceAll('_', ' ')}
                            </div>
                            <div className="text-muted-foreground">
                              {String(latestEvent.old_cik ?? '—')} → {String(latestEvent.new_cik ?? '—')}
                            </div>
                            {latestEvent.requires_downstream_review ? (
                              <div className="text-rose-700">
                                Downstream review · {String(latestEvent.affected_filings_count ?? 0)} filings
                              </div>
                            ) : null}
                            {affectedQuarters.length > 0 ? (
                              <div className="text-muted-foreground">
                                {affectedQuarters.slice(0, 3).join(', ')}
                              </div>
                            ) : null}
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">No CIK review event</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-2">
                          <span>{String(manager.match_status ?? '—')}</span>
                          {manager.match_status === 'candidate' || manager.match_status === 'seeded' ? (
                            <>
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                onClick={() => handleConfirmManager(manager)}
                              >
                                Confirm
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => handleRejectManager(manager)}
                              >
                                Reject
                              </Button>
                            </>
                          ) : null}
                          {manager.match_status === 'confirmed' && manager.cik ? (
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={() => handleRevokeManager(manager)}
                            >
                              Revoke CIK
                            </Button>
                          ) : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
                {managers.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                      No managers seeded.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card className="rounded-md">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <History className="h-4 w-4" />
              Job Runs
            </CardTitle>
          </CardHeader>
          <CardContent>
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
                {jobs.slice(0, 12).map((job: Record<string, unknown>) => (
                  <TableRow key={String(job.id)}>
                    <TableCell className="font-medium">{String(job.job_type ?? '—')}</TableCell>
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

      <Dialog open={pendingJob !== null} onOpenChange={(open) => !open && setPendingJob(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm Job</DialogTitle>
            <DialogDescription>
              Review the dry-run preview before queueing this operation.
            </DialogDescription>
          </DialogHeader>
          {pendingJob ? (
            <div className="space-y-4">
              <div className="rounded-md border border-border/70 p-3">
                <div className="text-xs uppercase text-muted-foreground">Action</div>
                <div className="mt-1 font-medium">{pendingJob.label}</div>
                <div className="mt-1 font-mono text-xs text-muted-foreground">
                  {String(pendingJob.payload.job_type ?? '—')}
                </div>
              </div>
              {pendingJob.previewFailed ? (
                <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
                  Preview failed. The backend will still enforce locks before queueing.
                </div>
              ) : null}
              <div>
                <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                  Impact Summary
                </div>
                <div className="grid gap-2 text-sm">
                {jobPreviewRows(pendingJob.preview).map(({ label, value }: { label: string; value: unknown }) => (
                  <div
                    key={String(label)}
                    className="flex justify-between gap-4 rounded-md border border-border/70 px-3 py-2"
                  >
                    <span className="text-muted-foreground">{String(label)}</span>
                    <span className="break-all text-right font-medium">{String(value)}</span>
                  </div>
                ))}
                </div>
              </div>
              {pendingJob.preview.rate_limit_warning ? (
                <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
                  {String(pendingJob.preview.rate_limit_warning)}
                </div>
              ) : null}
            </div>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setPendingJob(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!pendingJob || triggerJob.isPending}
              onClick={() => {
                if (!pendingJob) return;
                triggerJob.mutate({ ...pendingJob.payload, dry_run: false });
                setPendingJob(null);
              }}
            >
              Queue job
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={pendingStaleReleaseJobId !== null} onOpenChange={(open) => !open && setPendingStaleReleaseJobId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Release Stale Lock</DialogTitle>
            <DialogDescription>
              This marks a stale running job as failed and releases its active lock.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
              Only continue after confirming the worker is no longer running this job.
            </div>
            <div className="rounded-md border border-border/70 p-3 text-sm">
              <div className="text-xs uppercase text-muted-foreground">Job ID</div>
              <div className="mt-1 font-medium">#{pendingStaleReleaseJobId ?? '—'}</div>
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setPendingStaleReleaseJobId(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={pendingStaleReleaseJobId === null || releaseStaleLock.isPending}
              onClick={() => {
                if (pendingStaleReleaseJobId === null) return;
                releaseStaleLock.mutate(pendingStaleReleaseJobId);
                setPendingStaleReleaseJobId(null);
              }}
            >
              Release lock
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={pendingConfirmManager !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingConfirmManager(null);
            setConfirmCik('');
            setConfirmNote('');
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm Manager CIK</DialogTitle>
            <DialogDescription>
              {pendingConfirmManager
                ? managerCikReviewDefaults(pendingConfirmManager).confirmDescription
                : 'Confirm the SEC CIK for this manager.'}
            </DialogDescription>
          </DialogHeader>
          {pendingConfirmManager ? (
            <div className="space-y-4">
              <div className="rounded-md border border-border/70 p-3 text-sm">
                <SectionLabel>Manager</SectionLabel>
                <div className="mt-1 font-medium">
                  {String(managerCikReviewDefaults(pendingConfirmManager).managerName)}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Candidate: {String(managerCikReviewDefaults(pendingConfirmManager).candidateName)}
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="confirm-cik">
                  SEC CIK
                </label>
                <Input
                  id="confirm-cik"
                  className="mt-2"
                  value={confirmCik}
                  onChange={(event) => setConfirmCik(event.target.value)}
                  placeholder="0000000000"
                />
              </div>
              <div>
                <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="confirm-note">
                  Optional note
                </label>
                <Textarea
                  id="confirm-note"
                  className="mt-2"
                  value={confirmNote}
                  onChange={(event) => setConfirmNote(event.target.value)}
                  placeholder="Why is this CIK correct?"
                />
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setPendingConfirmManager(null);
                setConfirmCik('');
                setConfirmNote('');
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!pendingConfirmManager || !confirmCik.trim() || confirmManager.isPending}
              onClick={() => {
                if (!pendingConfirmManager) return;
                const managerId = Number(pendingConfirmManager.id);
                if (!Number.isFinite(managerId)) return;
                confirmManager.mutate({
                  managerId,
                  cik: confirmCik.trim(),
                  note: confirmNote.trim() || null,
                });
                setPendingConfirmManager(null);
                setConfirmCik('');
                setConfirmNote('');
              }}
            >
              Confirm CIK
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={pendingRejectManager !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingRejectManager(null);
            setRejectNote('');
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject Manager CIK</DialogTitle>
            <DialogDescription>
              {pendingRejectManager
                ? managerCikReviewDefaults(pendingRejectManager).rejectDescription
                : 'Reject this CIK candidate.'}
            </DialogDescription>
          </DialogHeader>
          {pendingRejectManager ? (
            <div className="space-y-4">
              <div className="rounded-md border border-border/70 p-3 text-sm">
                <SectionLabel>Manager</SectionLabel>
                <div className="mt-1 font-medium">
                  {String(managerCikReviewDefaults(pendingRejectManager).managerName)}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Candidate CIK {String(pendingRejectManager.candidate_cik ?? '—')}
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="reject-note">
                  Optional note
                </label>
                <Textarea
                  id="reject-note"
                  className="mt-2"
                  value={rejectNote}
                  onChange={(event) => setRejectNote(event.target.value)}
                  placeholder="Why is this candidate wrong?"
                />
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setPendingRejectManager(null);
                setRejectNote('');
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={!pendingRejectManager || rejectManager.isPending}
              onClick={() => {
                if (!pendingRejectManager) return;
                const managerId = Number(pendingRejectManager.id);
                if (!Number.isFinite(managerId)) return;
                rejectManager.mutate({ managerId, note: rejectNote.trim() || null });
                setPendingRejectManager(null);
                setRejectNote('');
              }}
            >
              Reject CIK
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={pendingRevokeManager !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingRevokeManager(null);
            setRevokeNote('');
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke Confirmed CIK</DialogTitle>
            <DialogDescription>
              This excludes the manager from future 13F ingestion until a correct CIK is confirmed.
            </DialogDescription>
          </DialogHeader>
          {pendingRevokeManager ? (
            <div className="space-y-4">
              <div className="rounded-md border border-border/70 p-3 text-sm">
                <SectionLabel>Manager</SectionLabel>
                <div className="mt-1 font-medium">
                  {String(pendingRevokeManager.legal_name ?? 'this manager')}
                </div>
                <div className="mt-1 font-mono text-xs text-muted-foreground">
                  CIK {String(pendingRevokeManager.cik ?? '—')}
                </div>
              </div>
              {(() => {
                const latestEvent =
                  pendingRevokeManager.latest_cik_review_event &&
                  typeof pendingRevokeManager.latest_cik_review_event === 'object'
                    ? (pendingRevokeManager.latest_cik_review_event as Record<string, unknown>)
                    : null;
                return latestEvent?.requires_downstream_review ? (
                  <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
                    Existing filings already require downstream review for this manager.
                  </div>
                ) : null;
              })()}
              <div>
                <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="revoke-note">
                  Required note
                </label>
                <Textarea
                  id="revoke-note"
                  className="mt-2"
                  value={revokeNote}
                  onChange={(event) => setRevokeNote(event.target.value)}
                  placeholder="Why is this confirmed CIK wrong?"
                />
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setPendingRevokeManager(null);
                setRevokeNote('');
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={!pendingRevokeManager || !revokeNote.trim() || revokeManager.isPending}
              onClick={() => {
                if (!pendingRevokeManager) return;
                const managerId = Number(pendingRevokeManager.id);
                if (!Number.isFinite(managerId)) return;
                revokeManager.mutate({ managerId, note: revokeNote.trim() });
                setPendingRevokeManager(null);
                setRevokeNote('');
              }}
            >
              Revoke CIK
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {selectedQuarter !== null ? (
        <DrawerShell
          title="Quarter Detail"
          description={
            selectedQuarterDetail?.summary
              ? `${selectedQuarterDetail.summary.quarter_phase} · ${selectedQuarterDetail.summary.quarter_health}`
              : selectedQuarter
          }
          closeLabel="Close quarter detail"
          labelledBy="quarter-detail-title"
          maxWidthClassName="max-w-[640px]"
          onClose={() => setSelectedQuarter(null)}
        >
              {selectedQuarterDetail ? (
                <>
                  <div className="grid gap-3 md:grid-cols-3">
                    <MetricTile
                      label="Filings"
                      value={formatInteger(selectedQuarterDetail.summary?.filings_count)}
                    />
                    <MetricTile
                      label="Holdings"
                      value={formatInteger(selectedQuarterDetail.summary?.holdings_count)}
                    />
                    <MetricTile
                      label="Linked"
                      value={formatPercent(selectedQuarterDetail.summary?.linked_holding_ratio)}
                      detail={
                        selectedQuarterDetail.summary?.linked_holding_unavailable_reason
                          ? String(selectedQuarterDetail.summary.linked_holding_unavailable_reason)
                          : undefined
                      }
                    />
                  </div>
                  {selectedQuarterDetail.summary?.active_job_id ? (
                    <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
                      Active job #{String(selectedQuarterDetail.summary.active_job_id)} ·{' '}
                      {String(selectedQuarterDetail.summary.active_job_type ?? 'job')}
                    </div>
                  ) : null}

                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                      Suggested Actions
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {(selectedQuarterDetail.suggested_actions ?? []).map(
                        (action: Record<string, unknown>, index: number) => (
                          <Button
                            key={`${String(action.job_type ?? 'action')}-${index}`}
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={isJobActive(action)}
                            onClick={() => runJob(action, String(action.label ?? action.job_type ?? 'Run action'))}
                          >
                            {String(action.label ?? action.job_type ?? 'Run action')}
                          </Button>
                        )
                      )}
                      {(selectedQuarterDetail.suggested_actions ?? []).length === 0 ? (
                        <div className="text-sm text-muted-foreground">
                          No suggested action for this quarter.
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                      Pending Filings
                    </div>
                    <div className="space-y-2">
                      {(selectedQuarterDetail.pending_filings ?? []).map((filing: Record<string, unknown>) => (
                        <div key={String(filing.accession_no)} className="rounded-md border border-border/70 p-3">
                          <div className="font-mono text-xs">{String(filing.accession_no ?? '—')}</div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            {String((filing.manager as Record<string, unknown> | undefined)?.legal_name ?? '—')} ·{' '}
                            {String(filing.form_type ?? '—')}
                          </div>
                        </div>
                      ))}
                      {(selectedQuarterDetail.pending_filings ?? []).length === 0 ? (
                        <div className="text-sm text-muted-foreground">No pending filings.</div>
                      ) : null}
                    </div>
                  </div>

                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                      Failed Filings
                    </div>
                    <div className="space-y-2">
                      {(selectedQuarterDetail.failed_filings ?? []).map((filing: Record<string, unknown>) => {
                        const infotable =
                          filing.raw_infotable && typeof filing.raw_infotable === 'object'
                            ? (filing.raw_infotable as Record<string, unknown>)
                            : {};
                        return (
                          <div key={String(filing.accession_no)} className="rounded-md border border-rose-300/70 bg-rose-50 p-3 text-rose-950">
                            <div className="font-mono text-xs">{String(filing.accession_no ?? '—')}</div>
                            <div className="mt-1 text-xs">
                              {String(infotable.error_message ?? 'Parse failed')}
                            </div>
                          </div>
                        );
                      })}
                      {(selectedQuarterDetail.failed_filings ?? []).length === 0 ? (
                        <div className="text-sm text-muted-foreground">No failed filings.</div>
                      ) : null}
                    </div>
                  </div>

                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                      Amendments
                    </div>
                    <div className="space-y-2">
                      {(selectedQuarterDetail.amendments ?? []).map((amendment: Record<string, unknown>) => (
                        <div key={String(amendment.accession_no)} className="rounded-md border border-border/70 p-3">
                          <div className="flex items-center justify-between gap-2">
                            <div className="font-mono text-xs">{String(amendment.accession_no ?? '—')}</div>
                            <Badge variant={badgeVariant(
                              amendment.status === 'failed'
                                ? 'danger'
                                : amendment.status === 'pending'
                                  ? 'warning'
                                  : amendment.status === 'applied'
                                    ? 'success'
                                    : 'secondary'
                            )}>
                              {String(amendment.status ?? 'unknown').replaceAll('_', ' ')}
                            </Badge>
                          </div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            Supersedes {String(amendment.supersedes_accession_no ?? '—')}
                          </div>
                        </div>
                      ))}
                      {(selectedQuarterDetail.amendments ?? []).length === 0 ? (
                        <div className="text-sm text-muted-foreground">No amendments for this quarter.</div>
                      ) : null}
                    </div>
                  </div>

                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                      Quality Report
                    </div>
                    {selectedQuarterDetail.quality_report ? (
                      <div className="rounded-md border border-border/70 bg-muted/40 p-3">
                        <div className="flex items-center justify-between gap-2">
                          <div className="font-medium">
                            {String(selectedQuarterDetail.quality_report.status ?? 'unknown').replaceAll('_', ' ')}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {String(selectedQuarterDetail.quality_report.checked_at ?? '—')}
                          </div>
                        </div>
                        <div className="mt-2 max-h-44 overflow-auto rounded-md border border-border/70 bg-background p-3 font-mono text-xs">
                          {formatJson(selectedQuarterDetail.quality_report.issues)}
                        </div>
                      </div>
                    ) : (
                      <div className="text-sm text-muted-foreground">No quality report for this quarter.</div>
                    )}
                  </div>
                </>
              ) : (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading quarter detail...
                </div>
              )}
        </DrawerShell>
      ) : null}
      {selectedAmendmentAccession !== null ? (
        <DrawerShell
          title="Amendment Detail"
          description={<span className="font-mono text-xs">{selectedAmendmentAccession}</span>}
          closeLabel="Close amendment detail"
          labelledBy="amendment-detail-title"
          maxWidthClassName="max-w-[560px]"
          onClose={() => setSelectedAmendmentAccession(null)}
        >
              {selectedAmendment ? (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={badgeVariant(
                      selectedAmendment.status === 'failed'
                        ? 'danger'
                        : selectedAmendment.status === 'pending'
                          ? 'warning'
                          : selectedAmendment.status === 'applied'
                            ? 'success'
                            : 'secondary'
                    )}>
                      {String(selectedAmendment.status ?? 'unknown').replaceAll('_', ' ')}
                    </Badge>
                    <span className="text-sm text-muted-foreground">
                      {selectedAmendment.form_type} · {selectedAmendment.quarter}
                    </span>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-md border border-border/70 p-3">
                      <div className="text-xs uppercase text-muted-foreground">Manager</div>
                      <div className="mt-1 text-sm font-medium">
                        {selectedAmendment.manager?.display_name ??
                          selectedAmendment.manager?.legal_name ??
                          '—'}
                      </div>
                      <div className="mt-1 font-mono text-xs text-muted-foreground">
                        {selectedAmendment.manager?.cik ?? '—'}
                      </div>
                    </div>
                    <div className="rounded-md border border-border/70 p-3">
                      <div className="text-xs uppercase text-muted-foreground">Holdings</div>
                      <div className="mt-1 text-sm">
                        {formatInteger(selectedAmendment.holdings_count)}
                      </div>
                    </div>
                    <div className="rounded-md border border-border/70 p-3">
                      <div className="text-xs uppercase text-muted-foreground">Supersedes</div>
                      <div className="mt-1 break-all font-mono text-xs">
                        {selectedAmendment.supersedes_accession_no ?? '—'}
                      </div>
                    </div>
                    <div className="rounded-md border border-border/70 p-3">
                      <div className="text-xs uppercase text-muted-foreground">Latest Effective</div>
                      <div className="mt-1 break-all font-mono text-xs">
                        {selectedAmendment.latest_effective_accession_no ?? '—'}
                      </div>
                    </div>
                  </div>
                  {selectedAmendment.recommended_job ? (
                    <Button
                      type="button"
                      variant="outline"
                      disabled={isJobActive(selectedAmendment.recommended_job)}
                      onClick={() =>
                        runJob(
                          selectedAmendment.recommended_job,
                          `Reprocess ${selectedAmendment.accession_no}`
                        )
                      }
                    >
                      Reprocess amendment
                    </Button>
                  ) : null}
                  <div>
                    <div className="text-xs font-semibold uppercase text-muted-foreground">
                      Raw primary document
                    </div>
                    <div className="mt-2 max-h-56 overflow-auto rounded-md border border-border/70 bg-muted/40 p-3 font-mono text-xs">
                      {formatJson(selectedAmendment.raw_primary)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-semibold uppercase text-muted-foreground">
                      Raw InfoTable document
                    </div>
                    <div className="mt-2 max-h-56 overflow-auto rounded-md border border-border/70 bg-muted/40 p-3 font-mono text-xs">
                      {formatJson(selectedAmendment.raw_infotable)}
                    </div>
                  </div>
                </>
              ) : (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading amendment detail...
                </div>
              )}
        </DrawerShell>
      ) : null}
      {selectedJobId !== null ? (
        <DrawerShell
          title="Job Detail"
          description={selectedJob ? `${selectedJob.job_type} · ${selectedJob.status}` : 'Loading job detail...'}
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
                      <div className="mt-1 break-all font-mono text-xs">{selectedJob.lock_key ?? '—'}</div>
                    </div>
                    <div className="rounded-md border border-border/70 p-3">
                      <div className="text-xs uppercase text-muted-foreground">Worker</div>
                      <div className="mt-1 break-all font-mono text-xs">{selectedJob.worker_id ?? '—'}</div>
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
                  {(selectedJob.error_message ||
                    (typeof selectedJob.summary_json === 'object' &&
                      selectedJob.summary_json !== null &&
                      (selectedJob.summary_json as Record<string, unknown>).pipeline_error)) ? (
                    <div className="rounded-md border border-rose-300/70 bg-rose-50 px-3 py-2 text-sm text-rose-950">
                      {selectedJob.error_message ??
                        String((selectedJob.summary_json as Record<string, unknown>).pipeline_error ?? '')}
                    </div>
                  ) : null}
                  {selectedJob.can_release_stale_lock ? (
                    <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-3 text-sm text-amber-950">
                      <div className="font-medium">This running job lock appears stale.</div>
                      <div className="mt-1">
                        Last heartbeat age: {formatInteger(Number(selectedJob.stale_seconds ?? 0))}s.
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
                      {(selectedJob.retry_targets ?? []).map((target: Record<string, unknown>, index: number) => (
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
                              String(target.label ?? target.accession_no ?? 'Retry target')
                            )
                          }
                        >
                          {String(target.label ?? target.accession_no ?? 'Retry target')}
                        </Button>
                      ))}
                      {(selectedJob.retry_targets ?? []).length === 0 ? (
                        <div className="text-sm text-muted-foreground">No retry target detected.</div>
                      ) : null}
                    </div>
                  </div>
                  {Array.isArray((selectedJob.summary_json as Record<string, unknown> | null)?.stages) &&
                  ((selectedJob.summary_json as Record<string, unknown>).stages as unknown[]).length > 0 ? (
                    <div>
                      <div className="text-xs font-semibold uppercase text-muted-foreground">
                        Pipeline Stages
                      </div>
                      <div className="mt-2 space-y-2">
                        {((selectedJob.summary_json as Record<string, unknown>).stages as Record<string, unknown>[]).map(
                          (stage, index) => (
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
                                          : 'secondary'
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
                          )
                        )}
                      </div>
                    </div>
                  ) : null}
                  <div>
                    <div className="text-xs font-semibold uppercase text-muted-foreground">
                      Timeline
                    </div>
                    <div className="mt-2 space-y-2">
                      {(selectedJob.events ?? []).map((event: Record<string, unknown>, index: number) => (
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
                                    : 'secondary'
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
                            {event.accession_no ? <span>{String(event.accession_no)}</span> : null}
                            {event.worker_id ? <span>{String(event.worker_id)}</span> : null}
                          </div>
                        </div>
                      ))}
                      {(selectedJob.events ?? []).length === 0 ? (
                        <div className="text-sm text-muted-foreground">No timeline events recorded.</div>
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
    </div>
  );
}
