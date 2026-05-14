'use client';

/**
 * MVP6-07: Readiness + Quality Findings page — PRD §11.1.
 *
 * Five Cards + Quarter Detail drawer + JobPendingDialog mount:
 *
 *   1. Data Readiness & Operations Health — readiness level,
 *      operations health summary, MetricTiles, status badges,
 *      Current Quarter + Setup Checklist grid, Top Task banner.
 *   2. Quality Reports — persisted quality_reports table.
 *   3. Needs Validation — per-quarter open-findings counts.
 *   4. Unknown Manager Type Priority — MVP4-07b classification
 *      priority queue with deep-link to /admin/13f/managers/{id}.
 *   5. Quarters — per-quarter health + Review drill-through.
 *
 * The Quarter Detail drawer surfaces filings paging + counts +
 * pending / failed / amendments / quality report sub-sections.
 * Its "Suggested Actions" buttons + retry triggers fire through
 * this route's own ``runJob`` + ``JobPendingDialog`` (the index
 * page keeps its own copies for Tasks Card + Manual Controls
 * per MVP6-06 SR5).
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
  CheckCircle2,
  Database,
  Loader2,
  ShieldAlert,
  UserSearch,
} from 'lucide-react';

import apiClient from '@/lib/api/client';
import thirteenfAdmin from '@/lib/thirteenfAdmin';
import { AdminPageLayout } from '@/components/admin13f/AdminPageLayout';
import { AdminErrorState } from '@/components/admin13f/AdminErrorState';
import { AdminLoadingState } from '@/components/admin13f/AdminLoadingState';
import { DrawerShell, MetricTile } from '@/components/admin13f/Admin13FPrimitives';
import {
  JobPendingDialog,
  type PendingJob,
} from '@/components/admin13f/JobPendingDialog';
import {
  useJobsQuery,
  useNeedsValidationQuery,
  useQualityQuery,
  useQuarterDetailQuery,
  useQuartersQuery,
  useReadinessQuery,
  useUnknownManagerPriorityQuery,
  useWorkersQuery,
} from '@/lib/admin13f/queries';
import { lockKeyForPayload } from '@/lib/admin13f/lockKey';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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
  freshnessLine,
  normalizeQualityReports,
  normalizeQuarters,
  normalizeReadiness,
  normalizeWorkers,
  operationsHealth,
} = thirteenfAdmin as {
  formatPercent: (value: number) => string;
  freshnessLine: (readiness: Record<string, unknown>) => string;
  normalizeQualityReports: (items: unknown[]) => Array<{
    id: number;
    quarter: string;
    status: string;
    statusTone: string;
    errorCount: number;
    warningCount: number;
    checkedAt: string | null;
    summary: string | null;
  }>;
  normalizeQuarters: (items: unknown[]) => Array<{
    quarter: string;
    phase: string;
    health: string | null;
    healthTone: string;
    filedManagers: number;
    trackedManagers: number;
    holdingsCount: number;
    linkedRatio: number | null;
    linkedUnavailableReason: string | null;
    amendmentStatus: string | null;
  }>;
  normalizeReadiness: (data: unknown) => Record<string, unknown> & {
    readinessLevel: string;
    readinessTone: string;
    latestUsableQuarter: string;
    currentQuarter: string;
    currentPhase: string;
    currentHealth: string;
    historicalDepth: number;
    counts: Record<string, number>;
    schedulerEnabled: boolean;
    smartRetryEnabled: boolean;
    setupChecklist: Array<Record<string, string>>;
    topTask: { title: string; recommended_action: string } | null;
    filingDeadline: string | null;
    thresholds: Record<string, unknown>;
  };
  normalizeWorkers: (items: unknown[]) => Array<{ status: string }>;
  operationsHealth: (args: {
    readiness: ReturnType<typeof normalizeReadiness>;
    tasks: unknown[];
    hasAvailableWorker: boolean;
    workersIndeterminate?: boolean;
  }) => {
    level: 'healthy' | 'blocked' | 'warning' | 'unknown';
    label: string;
    summary: string;
    tone: string;
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


// MVP6-08 follow-up: lockKeyForPayload moved to lib/admin13f/lockKey.ts.

export default function ReadinessAdminPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [selectedQuarter, setSelectedQuarter] = useState<string | null>(null);
  const [quarterFilingStatus, setQuarterFilingStatus] = useState('all');
  const [quarterFilingOffset, setQuarterFilingOffset] = useState(0);
  const [pendingJob, setPendingJob] = useState<PendingJob | null>(null);

  // Queries.
  const readinessQuery = useReadinessQuery();
  const quartersQuery = useQuartersQuery();
  const qualityQuery = useQualityQuery();
  const needsValidationQuery = useNeedsValidationQuery();
  const unknownManagerPriorityQuery = useUnknownManagerPriorityQuery();
  const quarterDetailQuery = useQuarterDetailQuery({
    selectedQuarter,
    quarterFilingStatus,
    quarterFilingOffset,
  });
  const workersQuery = useWorkersQuery();
  // jobsQuery feeds the activeLockKeys set so retry-target /
  // suggested-action buttons can suppress conflicting triggers.
  const jobsQuery = useJobsQuery({
    status: 'all',
    jobType: 'all',
    startedFrom: '',
    startedTo: '',
    syncDate: '',
    quarter: '',
  });

  // Memos.
  const readiness = useMemo(
    () => normalizeReadiness(readinessQuery.data ?? {}),
    [readinessQuery.data],
  );
  const readinessThresholds = readiness.thresholds as Record<string, unknown>;
  const quarters = useMemo(
    () => normalizeQuarters(quartersQuery.data?.items ?? []),
    [quartersQuery.data],
  );
  const qualityReports = useMemo(
    () => normalizeQualityReports(qualityQuery.data?.items ?? []),
    [qualityQuery.data],
  );
  const workers = useMemo(
    () => normalizeWorkers(workersQuery.data?.items ?? []),
    [workersQuery.data],
  );
  const hasAvailableWorker = workers.some(
    (worker) => worker.status === 'idle' || worker.status === 'running',
  );
  const jobs = useMemo(
    () => (Array.isArray(jobsQuery.data?.items) ? jobsQuery.data.items : []),
    [jobsQuery.data],
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

  const operationalHealth = useMemo(
    () =>
      operationsHealth({
        readiness,
        tasks: [],
        hasAvailableWorker,
        workersIndeterminate: workersQuery.isError,
      }),
    [readiness, hasAvailableWorker, workersQuery.isError],
  );

  const isLoading =
    readinessQuery.isLoading ||
    quartersQuery.isLoading ||
    qualityQuery.isLoading ||
    workersQuery.isLoading;

  const selectedQuarterDetail = quarterDetailQuery.data ?? null;

  // Refresh.
  const refreshReadinessData = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['admin-13f-readiness'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-quarters'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-quality'] }),
      queryClient.invalidateQueries({
        queryKey: ['admin-13f-backfill-needs-validation'],
      }),
      queryClient.invalidateQueries({
        queryKey: ['admin-13f-oracles-lens-unknown-manager-priority'],
      }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-quarter-detail'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-jobs'] }),
    ]);
  }, [queryClient]);

  // Auto-refresh on completed jobs.
  const prevActiveKeys = useRef(new Set<string>());
  useEffect(() => {
    const currentKeys = activeLockKeys;
    const wasActive = prevActiveKeys.current;
    const someJobFinished = Array.from(wasActive).some((key) => !currentKeys.has(key));
    if (someJobFinished) {
      refreshReadinessData();
    }
    prevActiveKeys.current = currentKeys;
  }, [activeLockKeys, refreshReadinessData]);

  // Mutations.
  const triggerJob = useMutation({
    mutationFn: async (payload: Record<string, unknown>) =>
      (await apiClient.post('/admin/13f/jobs', payload)).data,
    onSuccess: refreshReadinessData,
  });

  // runJob — dry-run preview then open JobPendingDialog.
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

  function openQuarterDetail(quarter: string) {
    setSelectedQuarter(quarter);
    setQuarterFilingStatus('all');
    setQuarterFilingOffset(0);
  }

  return (
    <AdminPageLayout
      title="Readiness"
      description="Readiness level, blockers, quality findings, needs-validation queue, and per-quarter drill-through."
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href="/admin/13f">← Back to Overview</Link>
        </Button>
      }
    >
      {/* Data Readiness & Operations Health */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
            <span>Data Readiness &amp; Operations Health</span>
            <span className="flex flex-wrap gap-2">
              <Badge variant={badgeVariant(readiness.readinessTone)}>
                Data {readiness.readinessLevel.replaceAll('_', ' ')}
              </Badge>
              <Badge
                variant={badgeVariant(
                  isLoading ? 'secondary' : operationalHealth.tone,
                )}
              >
                {isLoading ? 'operations loading' : operationalHealth.label}
              </Badge>
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {isLoading ? (
            <AdminLoadingState
              variant="compact"
              label="Loading 13F operations state..."
            />
          ) : null}
          <div className="grid gap-3 md:grid-cols-5">
            <MetricTile label="Latest usable" value={readiness.latestUsableQuarter} />
            <MetricTile
              label="Current quarter"
              value={readiness.currentQuarter}
              detail={readiness.currentPhase}
            />
            <MetricTile
              label="Historical depth"
              value={`${readiness.historicalDepth} quarters`}
            />
            <MetricTile
              label="Managers"
              value={`${formatInteger(readiness.counts.confirmed_managers)} confirmed`}
            />
            <MetricTile
              label="NT filers"
              value={formatInteger(
                readiness.counts.nt_filer_count ?? readiness.counts.nt_filers,
              )}
              detail="NT-HR amendment expected"
            />
          </div>
          <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
            {freshnessLine(readiness as Record<string, unknown>)}
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
            <Badge variant="outline">
              Ready link{' '}
              {formatPercent(Number(readinessThresholds.ready_link_ratio ?? 0.8))}
            </Badge>
            <Badge variant="outline">
              Warning link{' '}
              {formatPercent(Number(readinessThresholds.warning_link_ratio ?? 0.5))}
            </Badge>
            <Badge variant="outline">
              History target{' '}
              {formatInteger(readinessThresholds.ready_historical_depth ?? 4)}Q
            </Badge>
          </div>
          <div className="grid gap-3 lg:grid-cols-[280px_minmax(0,1fr)]">
            <div className="rounded-md border border-border/70 p-3">
              <div className="text-xs font-semibold uppercase text-muted-foreground">
                Current Quarter
              </div>
              <div className="mt-2 flex items-center justify-between gap-2">
                <div className="text-lg font-semibold">{readiness.currentQuarter}</div>
                <Badge
                  variant={badgeVariant(
                    readiness.currentHealth === 'complete'
                      ? 'success'
                      : readiness.currentHealth === 'setup_required' ||
                          readiness.currentHealth === 'needs_review'
                        ? 'danger'
                        : 'warning',
                  )}
                >
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
                {readiness.setupChecklist.map((item) => (
                  <div
                    key={item.code}
                    className="rounded-md border border-border/70 bg-muted/20 p-2"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-medium">{item.label}</div>
                      <Badge variant={badgeVariant(item.statusTone)}>
                        {item.status.replaceAll('_', ' ')}
                      </Badge>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {item.completeWhen}
                    </div>
                    {item.status !== 'complete' ? (
                      <div className="mt-1 text-xs text-foreground">{item.adminAction}</div>
                    ) : null}
                  </div>
                ))}
                {readiness.setupChecklist.length === 0 ? (
                  <div className="text-sm text-muted-foreground">
                    No setup checklist returned.
                  </div>
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

      {/* Quality Reports */}
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
                    {formatInteger(report.errorCount)} errors ·{' '}
                    {formatInteger(report.warningCount)} warnings
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

      {/* Needs Validation */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldAlert className="h-4 w-4" />
            Needs Validation
            {needsValidationQuery.data?.quarters?.length ? (
              <Badge variant="warning">
                {(needsValidationQuery.data.quarters as unknown[]).length} quarter
                {(needsValidationQuery.data.quarters as unknown[]).length !== 1 ? 's' : ''}
              </Badge>
            ) : null}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {needsValidationQuery.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          ) : !needsValidationQuery.data?.quarters?.length ? (
            <div className="text-sm text-muted-foreground">
              No quarters awaiting validation.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Quarter</TableHead>
                  <TableHead>Open findings</TableHead>
                  <TableHead>Quality report IDs</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(
                  needsValidationQuery.data.quarters as Array<{
                    quarter: string;
                    open_count: number;
                    quality_report_ids: number[];
                  }>
                ).map((row) => (
                  <TableRow key={row.quarter}>
                    <TableCell className="font-mono text-xs">{row.quarter}</TableCell>
                    <TableCell>
                      <Badge variant="warning">{row.open_count}</Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {row.quality_report_ids.join(', ')}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Unknown Manager Type Priority */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
            <span className="flex items-center gap-2">
              <UserSearch className="h-4 w-4" />
              Unknown Manager Type Priority
              {unknownManagerPriorityQuery.data?.items?.length ? (
                <Badge variant="warning">
                  {(unknownManagerPriorityQuery.data.items as unknown[]).length} pending
                </Badge>
              ) : null}
            </span>
            {unknownManagerPriorityQuery.data?.quarter ? (
              <span className="text-xs font-mono text-muted-foreground">
                {unknownManagerPriorityQuery.data.quarter}
                {unknownManagerPriorityQuery.data.score_version ? (
                  <> · {unknownManagerPriorityQuery.data.score_version}</>
                ) : null}
              </span>
            ) : null}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {unknownManagerPriorityQuery.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          ) : !unknownManagerPriorityQuery.data?.quarter ? (
            <div className="text-sm text-muted-foreground">
              No Oracle&apos;s Lens scores computed yet. Use the Historical Backfill
              section on{' '}
              <Link href="/admin/13f/jobs" className="font-medium text-foreground hover:underline">
                /admin/13f/jobs
              </Link>{' '}
              to score a quarter, then return here to prioritize manager classification.
            </div>
          ) : !unknownManagerPriorityQuery.data.items?.length ? (
            <div className="text-sm text-muted-foreground">
              All contributing managers are typed for{' '}
              {String(unknownManagerPriorityQuery.data.quarter)}. Signal weights are
              fully resolved — no classification debt for this quarter.
            </div>
          ) : (
            <>
              <p className="mb-3 text-xs text-muted-foreground">
                Managers with{' '}
                <code className="font-mono">manager_type=unknown</code> ranked by how
                many of the latest persisted Oracle&apos;s Lens scores they contribute
                to. Classifying the top rows lifts the most
                <code className="font-mono"> score_confidence</code>.
              </p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Manager</TableHead>
                      <TableHead>Affected signals</TableHead>
                      <TableHead>Worst score_confidence</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(
                      unknownManagerPriorityQuery.data.items as Array<{
                        manager_id: number;
                        canonical_name: string;
                        affected_signal_count: number;
                        worst_score_confidence_observed: string;
                      }>
                    ).map((row) => (
                      <TableRow key={row.manager_id}>
                        <TableCell>
                          <Link
                            href={`/admin/13f/managers/${row.manager_id}`}
                            className="font-medium hover:underline"
                          >
                            {row.canonical_name}
                          </Link>
                          <div className="font-mono text-xs text-muted-foreground">
                            #{row.manager_id}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant="warning">{row.affected_signal_count}</Badge>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={
                              row.worst_score_confidence_observed === 'high_confidence'
                                ? 'success'
                                : row.worst_score_confidence_observed ===
                                    'medium_confidence'
                                  ? 'warning'
                                  : 'danger'
                            }
                          >
                            {row.worst_score_confidence_observed}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Quarters */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Database className="h-4 w-4" />
            Quarters
          </CardTitle>
        </CardHeader>
        <CardContent>
          {quartersQuery.isError ? (
            <AdminErrorState
              error={quartersQuery.error}
              onRetry={() => quartersQuery.refetch()}
              title="Failed to load quarters"
            />
          ) : null}
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
                    {formatInteger(quarter.filedManagers)} /{' '}
                    {formatInteger(quarter.trackedManagers)}
                  </TableCell>
                  <TableCell>{formatInteger(quarter.holdingsCount)}</TableCell>
                  <TableCell>
                    <div>
                      {quarter.linkedRatio === null
                        ? '—'
                        : formatPercent(quarter.linkedRatio)}
                    </div>
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
                      onClick={() => openQuarterDetail(quarter.quarter)}
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

      {/* Quarter Detail Drawer */}
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
                  value={formatPercent(
                    selectedQuarterDetail.summary?.linked_holding_ratio,
                  )}
                  detail={
                    selectedQuarterDetail.summary?.linked_holding_unavailable_reason
                      ? String(
                          selectedQuarterDetail.summary.linked_holding_unavailable_reason,
                        )
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
              {selectedQuarterDetail.summary?.revoked_cik_review_required ? (
                <div className="rounded-md border border-rose-300/70 bg-rose-50 px-3 py-2 text-sm text-rose-950">
                  This quarter includes filings from a manager whose CIK was revoked.
                  Reconfirm the manager CIK before relying on downstream analytics.
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
                        onClick={() =>
                          runJob(
                            action,
                            String(action.label ?? action.job_type ?? 'Run action'),
                          )
                        }
                      >
                        {String(action.label ?? action.job_type ?? 'Run action')}
                      </Button>
                    ),
                  )}
                  {(selectedQuarterDetail.suggested_actions ?? []).length === 0 ? (
                    <div className="text-sm text-muted-foreground">
                      No suggested action for this quarter.
                    </div>
                  ) : null}
                </div>
              </div>

              <div>
                <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="text-xs font-semibold uppercase text-muted-foreground">
                    Filing Rows
                  </div>
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                    <Select
                      value={quarterFilingStatus}
                      onValueChange={(value) => {
                        setQuarterFilingStatus(value);
                        setQuarterFilingOffset(0);
                      }}
                    >
                      <SelectTrigger className="w-full sm:w-[190px]">
                        <SelectValue placeholder="All filing statuses" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All statuses</SelectItem>
                        <SelectItem value="pending">Pending</SelectItem>
                        <SelectItem value="failed">Failed</SelectItem>
                        <SelectItem value="parsed_no_holdings">
                          Parsed, no holdings
                        </SelectItem>
                        <SelectItem value="parsed">Parsed</SelectItem>
                      </SelectContent>
                    </Select>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={quarterFilingOffset === 0}
                        onClick={() =>
                          setQuarterFilingOffset((value) => Math.max(value - 25, 0))
                        }
                      >
                        Prev
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={
                          !selectedQuarterDetail.filings_page ||
                          Number(selectedQuarterDetail.filings_page.offset ?? 0) +
                            Number(selectedQuarterDetail.filings_page.limit ?? 25) >=
                            Number(selectedQuarterDetail.filings_page.total ?? 0)
                        }
                        onClick={() => setQuarterFilingOffset((value) => value + 25)}
                      >
                        Next
                      </Button>
                    </div>
                  </div>
                </div>
                <div className="rounded-md border border-border/70">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Accession</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Manager</TableHead>
                        <TableHead>Holdings</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(selectedQuarterDetail.filings_page?.items ?? []).map(
                        (filing: Record<string, unknown>) => (
                          <TableRow key={String(filing.accession_no)}>
                            <TableCell className="font-mono text-xs">
                              {String(filing.accession_no ?? '—')}
                            </TableCell>
                            <TableCell>
                              <Badge
                                variant={badgeVariant(
                                  filing.status === 'failed'
                                    ? 'danger'
                                    : filing.status === 'pending' ||
                                        filing.status === 'parsed_no_holdings'
                                      ? 'warning'
                                      : 'success',
                                )}
                              >
                                {String(filing.status ?? 'unknown').replaceAll('_', ' ')}
                              </Badge>
                            </TableCell>
                            <TableCell>
                              {String(
                                (filing.manager as Record<string, unknown> | undefined)
                                  ?.legal_name ?? '—',
                              )}
                            </TableCell>
                            <TableCell>{formatInteger(filing.holdings_count)}</TableCell>
                          </TableRow>
                        ),
                      )}
                      {(selectedQuarterDetail.filings_page?.items ?? []).length === 0 ? (
                        <TableRow>
                          <TableCell
                            colSpan={4}
                            className="py-6 text-center text-muted-foreground"
                          >
                            No filings match this filter.
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </TableBody>
                  </Table>
                </div>
                <div className="mt-2 text-xs text-muted-foreground">
                  Showing{' '}
                  {formatInteger(
                    (selectedQuarterDetail.filings_page?.items ?? []).length,
                  )}{' '}
                  of {formatInteger(selectedQuarterDetail.filings_page?.total)} matching
                  filings. Counts: pending{' '}
                  {formatInteger(
                    selectedQuarterDetail.filing_counts_by_status?.pending,
                  )}
                  , failed{' '}
                  {formatInteger(selectedQuarterDetail.filing_counts_by_status?.failed)},
                  parsed{' '}
                  {formatInteger(selectedQuarterDetail.filing_counts_by_status?.parsed)}.
                </div>
              </div>

              <div>
                <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                  Pending Filings
                </div>
                <div className="space-y-2">
                  {(selectedQuarterDetail.pending_filings ?? []).map(
                    (filing: Record<string, unknown>) => (
                      <div
                        key={String(filing.accession_no)}
                        className="rounded-md border border-border/70 p-3"
                      >
                        <div className="font-mono text-xs">
                          {String(filing.accession_no ?? '—')}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {String(
                            (filing.manager as Record<string, unknown> | undefined)
                              ?.legal_name ?? '—',
                          )}{' '}
                          · {String(filing.form_type ?? '—')}
                        </div>
                      </div>
                    ),
                  )}
                  {(selectedQuarterDetail.pending_filings ?? []).length === 0 ? (
                    <div className="text-sm text-muted-foreground">
                      No pending filings.
                    </div>
                  ) : null}
                </div>
              </div>

              <div>
                <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                  Failed Filings
                </div>
                <div className="space-y-2">
                  {(selectedQuarterDetail.failed_filings ?? []).map(
                    (filing: Record<string, unknown>) => {
                      const infotable =
                        filing.raw_infotable && typeof filing.raw_infotable === 'object'
                          ? (filing.raw_infotable as Record<string, unknown>)
                          : {};
                      return (
                        <div
                          key={String(filing.accession_no)}
                          className="rounded-md border border-rose-300/70 bg-rose-50 p-3 text-rose-950"
                        >
                          <div className="font-mono text-xs">
                            {String(filing.accession_no ?? '—')}
                          </div>
                          <div className="mt-1 text-xs">
                            {String(infotable.error_message ?? 'Parse failed')}
                          </div>
                        </div>
                      );
                    },
                  )}
                  {(selectedQuarterDetail.failed_filings ?? []).length === 0 ? (
                    <div className="text-sm text-muted-foreground">
                      No failed filings.
                    </div>
                  ) : null}
                </div>
              </div>

              <div>
                <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                  Amendments
                </div>
                <div className="space-y-2">
                  {(selectedQuarterDetail.amendments ?? []).map(
                    (amendment: Record<string, unknown>) => (
                      <div
                        key={String(amendment.accession_no)}
                        className="rounded-md border border-border/70 p-3"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="font-mono text-xs">
                            {String(amendment.accession_no ?? '—')}
                          </div>
                          <Badge
                            variant={badgeVariant(
                              amendment.status === 'failed'
                                ? 'danger'
                                : amendment.status === 'pending'
                                  ? 'warning'
                                  : amendment.status === 'applied'
                                    ? 'success'
                                    : 'secondary',
                            )}
                          >
                            {String(amendment.status ?? 'unknown').replaceAll('_', ' ')}
                          </Badge>
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          Supersedes {String(amendment.supersedes_accession_no ?? '—')}
                        </div>
                      </div>
                    ),
                  )}
                  {(selectedQuarterDetail.amendments ?? []).length === 0 ? (
                    <div className="text-sm text-muted-foreground">
                      No amendments for this quarter.
                    </div>
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
                        {String(
                          selectedQuarterDetail.quality_report.status ?? 'unknown',
                        ).replaceAll('_', ' ')}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {String(selectedQuarterDetail.quality_report.checked_at ?? '—')}
                      </div>
                    </div>
                    <div className="mt-2 max-h-60 overflow-auto space-y-1.5">
                      {(() => {
                        type QIssue = {
                          check: string;
                          severity: string;
                          accession_no?: string;
                          detail?: string;
                        };
                        const issues = selectedQuarterDetail.quality_report.issues as
                          | QIssue[]
                          | undefined;
                        return issues?.length ? (
                          issues.map((issue, i) => (
                            <div
                              key={i}
                              className="rounded-md border border-border/70 bg-background px-2.5 py-2 text-xs"
                            >
                              <div className="flex items-center gap-2">
                                <Badge
                                  variant={
                                    issue.severity === 'error'
                                      ? 'danger'
                                      : issue.severity === 'warning'
                                        ? 'warning'
                                        : 'secondary'
                                  }
                                  className="shrink-0 text-[10px]"
                                >
                                  {issue.severity}
                                </Badge>
                                <span className="font-mono">{issue.check}</span>
                                {issue.accession_no ? (
                                  <span className="text-muted-foreground">{issue.accession_no}</span>
                                ) : null}
                              </div>
                              {issue.detail ? (
                                <div className="mt-1 text-muted-foreground">{issue.detail}</div>
                              ) : null}
                            </div>
                          ))
                        ) : (
                          <div className="text-xs text-muted-foreground">No issues recorded.</div>
                        );
                      })()}
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">
                    No quality report for this quarter.
                  </div>
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

    </AdminPageLayout>
  );
}
