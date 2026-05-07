'use client';

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  History,
  Loader2,
  Play,
  RefreshCw,
  ShieldAlert,
  X,
} from 'lucide-react';
import type { ComponentProps } from 'react';

import apiClient from '@/lib/api/client';
import thirteenfAdmin from '@/lib/thirteenfAdmin';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
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
  normalizeAmendments,
  normalizeQualityReports,
  normalizeQuarters,
  normalizeReadiness,
  normalizeTasks,
  normalizeWorkers,
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

export default function Admin13FPage() {
  const queryClient = useQueryClient();
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
  const triggerJob = useMutation({
    mutationFn: async (payload: Record<string, unknown>) =>
      (await apiClient.post('/admin/13f/jobs', payload)).data,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['admin-13f-readiness'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-quarters'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-tasks'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-jobs'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-quality'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-amendments'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-quarter-detail'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-workers'] }),
      ]);
    },
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
  const managers = managersQuery.data?.items ?? [];
  const jobs = jobsQuery.data?.items ?? [];
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

  function runJob(payload: Record<string, unknown>, label: string) {
    if (typeof window !== 'undefined' && !window.confirm(`Run ${label}?`)) return;
    triggerJob.mutate(payload);
  }

  function handleConfirmManager(manager: Record<string, unknown>) {
    const managerId = Number(manager.id);
    if (!Number.isFinite(managerId)) return;
    const currentCik =
      (typeof manager.candidate_cik === 'string' ? manager.candidate_cik : '') ||
      (typeof manager.cik === 'string' ? manager.cik : '');
    const cik =
      currentCik ||
      (typeof window !== 'undefined'
        ? window.prompt('Enter the SEC CIK to confirm for this manager')
        : null);
    if (!cik) return;
    const note =
      typeof window !== 'undefined'
        ? window.prompt('Optional review note for this CIK confirmation') || null
        : null;
    if (
      typeof window !== 'undefined' &&
      !window.confirm(`Confirm CIK ${cik} for ${String(manager.legal_name ?? 'this manager')}?`)
    ) {
      return;
    }
    confirmManager.mutate({ managerId, cik, note });
  }

  function handleRejectManager(manager: Record<string, unknown>) {
    const managerId = Number(manager.id);
    if (!Number.isFinite(managerId)) return;
    const note =
      typeof window !== 'undefined'
        ? window.prompt('Optional review note for this CIK rejection') || null
        : null;
    if (
      typeof window !== 'undefined' &&
      !window.confirm(`Reject CIK candidate for ${String(manager.legal_name ?? 'this manager')}?`)
    ) {
      return;
    }
    rejectManager.mutate({ managerId, note });
  }

  function handleRevokeManager(manager: Record<string, unknown>) {
    const managerId = Number(manager.id);
    if (!Number.isFinite(managerId)) return;
    const note =
      typeof window !== 'undefined'
        ? window.prompt('Required note: why is this confirmed CIK wrong?')
        : null;
    if (!note?.trim()) return;
    const affectedEvent =
      manager.latest_cik_review_event && typeof manager.latest_cik_review_event === 'object'
        ? (manager.latest_cik_review_event as Record<string, unknown>)
        : null;
    const warning = affectedEvent?.requires_downstream_review
      ? ' Existing filings already require downstream review.'
      : '';
    if (
      typeof window !== 'undefined' &&
      !window.confirm(
        `Revoke CIK ${String(manager.cik ?? '—')} for ${String(
          manager.legal_name ?? 'this manager'
        )}? The manager will be excluded from future 13F ingestion until reconfirmed.${warning}`
      )
    ) {
      return;
    }
    revokeManager.mutate({ managerId, note: note.trim() });
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
          <CardTitle className="flex items-center justify-between gap-3 text-base">
            <span>Readiness</span>
            <Badge variant={badgeVariant(readiness.readinessTone)}>
              {readiness.readinessLevel.replaceAll('_', ' ')}
            </Badge>
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
            <div className="rounded-md border border-border/70 p-3">
              <div className="text-xs uppercase text-muted-foreground">Latest usable</div>
              <div className="mt-1 text-lg font-semibold">{readiness.latestUsableQuarter}</div>
            </div>
            <div className="rounded-md border border-border/70 p-3">
              <div className="text-xs uppercase text-muted-foreground">Current quarter</div>
              <div className="mt-1 text-lg font-semibold">{readiness.currentQuarter}</div>
              <div className="text-xs text-muted-foreground">{readiness.currentPhase}</div>
            </div>
            <div className="rounded-md border border-border/70 p-3">
              <div className="text-xs uppercase text-muted-foreground">Historical depth</div>
              <div className="mt-1 text-lg font-semibold">{readiness.historicalDepth} quarters</div>
            </div>
            <div className="rounded-md border border-border/70 p-3">
              <div className="text-xs uppercase text-muted-foreground">Managers</div>
              <div className="mt-1 text-lg font-semibold">
                {formatInteger(readiness.counts.confirmed_managers)} confirmed
              </div>
            </div>
          </div>
          <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
            {freshnessLine(readiness)}
          </div>
          {readiness.topTask ? (
            <div className="flex items-start gap-2 rounded-md border border-rose-300/70 bg-rose-50 px-3 py-2 text-sm text-rose-950">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <div className="font-medium">{readiness.topTask.title}</div>
                <div>{readiness.topTask.recommended_action}</div>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2 rounded-md border border-emerald-300/70 bg-emerald-50 px-3 py-2 text-sm text-emerald-950">
              <CheckCircle2 className="h-4 w-4" />
              No blocking admin task detected.
            </div>
          )}
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
          <CardTitle className="flex items-center gap-2 text-base">
            <Activity className="h-4 w-4" />
            Worker Heartbeat
          </CardTitle>
        </CardHeader>
        <CardContent>
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
              {workers.map((worker) => (
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
              {workers.length === 0 ? (
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
                    <TableCell>{formatPercent(quarter.linkedRatio)}</TableCell>
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
            {tasks.map((task) => (
              <div key={task.code} className="rounded-md border border-border/70 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="font-medium">{task.title}</div>
                  <Badge variant={badgeVariant(task.priorityTone)}>{task.priority}</Badge>
                </div>
                <div className="mt-2 text-sm text-muted-foreground">{task.recommendedAction}</div>
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
                      <div>
                        Retry target:{' '}
                        <span className="font-mono text-foreground">
                          {String(task.metadata.retry_targets[0]?.accession_no ?? '—')}
                        </span>
                      </div>
                    ) : null}
                    {'error_message' in task.metadata && task.metadata.error_message ? (
                      <div className="text-rose-700">
                        Error: {String(task.metadata.error_message)}
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
            ))}
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
          <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => runJob({ job_type: 'bootstrap_whitelist' }, 'Bootstrap whitelist')}
          >
            Bootstrap whitelist
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => runJob({ job_type: 'match_cik' }, 'Match CIK')}
          >
            Match CIK
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={!targetQuarter}
            onClick={() =>
              runJob({ job_type: 'fetch_quarter_index', quarter: targetQuarter }, 'Fetch quarter index')
            }
          >
            Fetch quarter index
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={!targetQuarter}
            onClick={() =>
              runJob({ job_type: 'ingest_holdings', quarter: targetQuarter }, 'Ingest holdings')
            }
          >
            Ingest holdings
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={!targetQuarter}
            onClick={() =>
              runJob({ job_type: 'quality_check', quarter: targetQuarter }, 'Quality check')
            }
          >
            Quality check
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={!targetQuarter}
            onClick={() =>
              runJob({ job_type: 'enrich_cusip', quarter: targetQuarter }, 'Enrich CUSIP mappings')
            }
          >
            Enrich CUSIP
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => runJob({ job_type: 'bootstrap_stocks' }, 'Bootstrap stocks')}
          >
            Bootstrap stocks
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => runJob({ job_type: 'enrich_stocks_edgar' }, 'Enrich stocks from EDGAR')}
          >
            Enrich stocks from EDGAR
          </Button>
          <Button
            type="button"
            variant="outline"
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
          <Button
            type="button"
            variant="outline"
            disabled={!targetAccession}
            onClick={() =>
              runJob({ job_type: 'ingest_accession', accession_no: targetAccession }, 'Retry accession')
            }
          >
            Retry accession
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={!targetAccession}
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
          <div>
            <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="backfill-start-quarter">
              Optional backfill start quarter
            </label>
            <Input
              id="backfill-start-quarter"
              className="mt-2 max-w-sm"
              placeholder="Defaults to latest usable"
              value={backfillStartQuarter}
              onChange={(event) => setBackfillStartQuarter(event.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
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
      {selectedQuarter !== null ? (
        <div className="fixed inset-0 z-50 flex justify-end bg-background/60 backdrop-blur-sm">
          <div
            aria-hidden="true"
            className="absolute inset-0 cursor-default"
            onClick={() => setSelectedQuarter(null)}
          />
          <Card className="relative h-full w-full max-w-[640px] overflow-hidden rounded-none border-y-0 border-r-0 shadow-xl">
            <CardHeader className="border-b border-border/70 pb-3">
              <CardTitle className="flex items-center justify-between gap-2 text-base">
                <span>Quarter Detail</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label="Close quarter detail"
                  onClick={() => setSelectedQuarter(null)}
                >
                  <X className="h-4 w-4" />
                </Button>
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                {selectedQuarterDetail?.summary
                  ? `${selectedQuarterDetail.summary.quarter_phase} · ${selectedQuarterDetail.summary.quarter_health}`
                  : selectedQuarter}
              </p>
            </CardHeader>
            <CardContent className="h-[calc(100%-84px)] space-y-5 overflow-y-auto p-5">
              {selectedQuarterDetail ? (
                <>
                  <div className="grid gap-3 md:grid-cols-3">
                    <div className="rounded-md border border-border/70 p-3">
                      <div className="text-xs uppercase text-muted-foreground">Filings</div>
                      <div className="mt-1 text-lg font-semibold">
                        {formatInteger(selectedQuarterDetail.summary?.filings_count)}
                      </div>
                    </div>
                    <div className="rounded-md border border-border/70 p-3">
                      <div className="text-xs uppercase text-muted-foreground">Holdings</div>
                      <div className="mt-1 text-lg font-semibold">
                        {formatInteger(selectedQuarterDetail.summary?.holdings_count)}
                      </div>
                    </div>
                    <div className="rounded-md border border-border/70 p-3">
                      <div className="text-xs uppercase text-muted-foreground">Linked</div>
                      <div className="mt-1 text-lg font-semibold">
                        {formatPercent(selectedQuarterDetail.summary?.linked_holding_ratio)}
                      </div>
                    </div>
                  </div>

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
            </CardContent>
          </Card>
        </div>
      ) : null}
      {selectedAmendmentAccession !== null ? (
        <div className="fixed inset-0 z-50 flex justify-end bg-background/60 backdrop-blur-sm">
          <div
            aria-hidden="true"
            className="absolute inset-0 cursor-default"
            onClick={() => setSelectedAmendmentAccession(null)}
          />
          <Card className="relative h-full w-full max-w-[560px] overflow-hidden rounded-none border-y-0 border-r-0 shadow-xl">
            <CardHeader className="border-b border-border/70 pb-3">
              <CardTitle className="flex items-center justify-between gap-2 text-base">
                <span>Amendment Detail</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label="Close amendment detail"
                  onClick={() => setSelectedAmendmentAccession(null)}
                >
                  <X className="h-4 w-4" />
                </Button>
              </CardTitle>
              <p className="font-mono text-xs text-muted-foreground">
                {selectedAmendmentAccession}
              </p>
            </CardHeader>
            <CardContent className="h-[calc(100%-84px)] space-y-5 overflow-y-auto p-5">
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
            </CardContent>
          </Card>
        </div>
      ) : null}
      {selectedJobId !== null ? (
        <div className="fixed inset-0 z-50 flex justify-end bg-background/60 backdrop-blur-sm">
          <div
            aria-hidden="true"
            className="absolute inset-0 cursor-default"
            onClick={() => setSelectedJobId(null)}
          />
          <Card className="relative h-full w-full max-w-[520px] overflow-hidden rounded-none border-y-0 border-r-0 shadow-xl">
            <CardHeader className="border-b border-border/70 pb-3">
              <CardTitle className="flex items-center justify-between gap-2 text-base">
                <span>Job Detail</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label="Close job detail"
                  onClick={() => setSelectedJobId(null)}
                >
                  <X className="h-4 w-4" />
                </Button>
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                {selectedJob ? `${selectedJob.job_type} · ${selectedJob.status}` : 'Loading job detail...'}
              </p>
            </CardHeader>
            <CardContent className="h-[calc(100%-84px)] space-y-5 overflow-y-auto p-5">
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
                  {selectedJob.error_message ? (
                    <div className="rounded-md border border-rose-300/70 bg-rose-50 px-3 py-2 text-sm text-rose-950">
                      {selectedJob.error_message}
                    </div>
                  ) : null}
                  <div>
                    <div className="text-xs font-semibold uppercase text-muted-foreground">
                      Retry Targets
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {(selectedJob.retry_targets ?? []).map((target: Record<string, unknown>, index: number) => (
                        <Button
                          key={`${String(target.accession_no ?? 'target')}-${index}`}
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            runJob(
                              {
                                job_type: target.job_type,
                                accession_no: target.accession_no,
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
            </CardContent>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
