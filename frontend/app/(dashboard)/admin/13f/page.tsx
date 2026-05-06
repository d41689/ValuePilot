'use client';

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  History,
  Loader2,
  Play,
  RefreshCw,
  ShieldAlert,
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
  normalizeQuarters,
  normalizeReadiness,
  normalizeTasks,
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

export default function Admin13FPage() {
  const queryClient = useQueryClient();
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
      ]);
    },
  });
  const confirmManager = useMutation({
    mutationFn: async ({ managerId, cik }: { managerId: number; cik: string | null }) =>
      (await apiClient.post(`/admin/13f/managers/${managerId}/confirm-cik`, { cik })).data,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['admin-13f-readiness'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-tasks'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-managers'] }),
      ]);
    },
  });
  const rejectManager = useMutation({
    mutationFn: async (managerId: number) =>
      (await apiClient.post(`/admin/13f/managers/${managerId}/reject-cik`, {})).data,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['admin-13f-readiness'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-tasks'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-managers'] }),
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
  const managers = managersQuery.data?.items ?? [];
  const jobs = jobsQuery.data?.items ?? [];
  const isLoading =
    readinessQuery.isLoading ||
    quartersQuery.isLoading ||
    tasksQuery.isLoading ||
    managersQuery.isLoading ||
    jobsQuery.isLoading;

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
    const currentCik = typeof manager.cik === 'string' ? manager.cik : '';
    const cik =
      currentCik ||
      (typeof window !== 'undefined'
        ? window.prompt('Enter the SEC CIK to confirm for this manager')
        : null);
    if (!cik) return;
    if (
      typeof window !== 'undefined' &&
      !window.confirm(`Confirm CIK ${cik} for ${String(manager.legal_name ?? 'this manager')}?`)
    ) {
      return;
    }
    confirmManager.mutate({ managerId, cik });
  }

  function handleRejectManager(manager: Record<string, unknown>) {
    const managerId = Number(manager.id);
    if (!Number.isFinite(managerId)) return;
    if (
      typeof window !== 'undefined' &&
      !window.confirm(`Reject CIK candidate for ${String(manager.legal_name ?? 'this manager')}?`)
    ) {
      return;
    }
    rejectManager.mutate(managerId);
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
                  </TableRow>
                ))}
                {quarters.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
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
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {managers.slice(0, 12).map((manager: Record<string, unknown>) => (
                  <TableRow key={String(manager.id)}>
                    <TableCell className="font-medium">{String(manager.legal_name ?? '—')}</TableCell>
                    <TableCell>{String(manager.cik ?? '—')}</TableCell>
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
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
                {managers.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="py-8 text-center text-muted-foreground">
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
                  </TableRow>
                ))}
                {jobs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="py-8 text-center text-muted-foreground">
                      No job history available.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
