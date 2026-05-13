'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Play,
  RefreshCw,
  Settings,
} from 'lucide-react';
import type { ComponentProps } from 'react';

import apiClient from '@/lib/api/client';
import thirteenfAdmin from '@/lib/thirteenfAdmin';
import { AdminPageLayout } from '@/components/admin13f/AdminPageLayout';
// AdminEmptyState + AdminErrorState ship as new shared components
// in MVP6-01 but the existing page's inline empty-state divs are
// preserved byte-for-byte (per the MVP6-01 SR2 scope refinement);
// MVP6-02..07 route-owner tickets adopt them in each section as
// they migrate.
import { JobPendingDialog, type PendingJob } from '@/components/admin13f/JobPendingDialog';
import { ReleaseStaleLockDialog } from '@/components/admin13f/ReleaseStaleLockDialog';
import { ManagerCikDialogs } from '@/components/admin13f/ManagerCikDialogs';
import {
  useEdgarRateLimitQuery,
  useHoldingsCoverageQuery,
  useJobsQuery,
  useManagersQuery,
  usePendingAmendmentsQuery,
  useReadinessQuery,
  useTasksQuery,
  useUnknownManagerPriorityQuery,
} from '@/lib/admin13f/queries';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { useToast } from '@/components/ui/use-toast';

const {
  normalizeEdgarRateLimit,
  normalizeHoldingsCoverage,
  normalizeReadiness,
  normalizeTasks,
  taskPrimaryAction,
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

// MVP6-07: ``formatJson`` removed along with the Quarter Detail Drawer
// that consumed it.
// MVP6-02: ``MANAGER_TYPE_OPTIONS`` moved to
// ``frontend/components/admin13f/ManagerTypeEditorDialog.tsx``
// (the lifted component owns the vocabulary now that its only
// caller on this page is gone).

export default function Admin13FPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  // MVP6-07: selectedQuarter + quarterFilingStatus + quarterFilingOffset
  // moved to /admin/13f/readiness along with the Quarter Detail drawer.
  // MVP6-06: selectedJobId + Job Runs filter state moved to /admin/13f/jobs.
  // MVP6-04: selectedFiling/AmendmentAccession + filingParseStatus
  // moved to /admin/13f/filings. The two detail drawers are gone too.
  // MVP6-01 Tier 3: the 20 admin/13f useQuery hooks moved to
  // ``frontend/lib/admin13f/queries.ts``. Same queryKey + queryFn
  // shapes as before so the inline mutation ``invalidateQueries``
  // calls further down still hit the right caches.
  const readinessQuery = useReadinessQuery();
  // MVP6-07: quartersQuery moved to /admin/13f/readiness.
  const tasksQuery = useTasksQuery();
  const managersQuery = useManagersQuery();
  // MVP6-06: jobsQuery stays on the index page because the Overview
  // hub Jobs card KPI reads ``jobsQuery.data?.items?.length``. Filter
  // state moved to /admin/13f/jobs so this call uses default ``all``
  // filters.
  const jobsQuery = useJobsQuery({
    status: 'all',
    jobType: 'all',
    startedFrom: '',
    startedTo: '',
    syncDate: '',
    quarter: '',
  });
  // MVP6-07: qualityQuery moved to /admin/13f/readiness.
  // MVP6-04: amendmentsQuery + filingsQuery removed — fully consumed by
  // ``/admin/13f/filings``. pendingAmendmentsQuery stays because the
  // Overview hub Filings card KPI reads its count.
  const pendingAmendmentsQuery = usePendingAmendmentsQuery();
  const coverageQuarter =
    typeof readinessQuery.data?.latest_usable_quarter === 'string'
      ? readinessQuery.data.latest_usable_quarter
      : null;
  const holdingsCoverageQuery = useHoldingsCoverageQuery(coverageQuarter);
  // MVP6-05: useUnresolvedCusipsQuery moved to /admin/13f/holdings.
  // MVP6-07: workersQuery + needsValidationQuery + quarterDetailQuery
  // moved to /admin/13f/readiness.
  const edgarRateLimitQuery = useEdgarRateLimitQuery();
  // MVP6-06: jobDetailQuery moved to /admin/13f/jobs along with the
  // Job Detail Drawer.
  // MVP6-04: amendmentDetailQuery + parseRunsQuery now live on
  // /admin/13f/filings; the queries module hook still exists.
  const unknownManagerPriorityQuery = useUnknownManagerPriorityQuery();
  // MVP6-02: manager_type editor state + mutation moved to the new
  // ``/admin/13f/managers`` and ``/admin/13f/managers/[id]`` routes
  // along with the Managers section that hosted it.
  const [manualQuarter, setManualQuarter] = useState('');
  const [backfillQuarters, setBackfillQuarters] = useState('4');
  const [backfillStartQuarter, setBackfillStartQuarter] = useState('');
  const [accessionNo, setAccessionNo] = useState('');
  const [pendingJob, setPendingJob] = useState<PendingJob | null>(null);
  const [pendingStaleReleaseJobId, setPendingStaleReleaseJobId] = useState<number | null>(null);
  // MVP6-06: showWorkerHistory moved to /admin/13f/jobs along with
  // the Worker Heartbeat Card.
  const [pendingConfirmManager, setPendingConfirmManager] = useState<Record<string, unknown> | null>(null);
  const [confirmCik, setConfirmCik] = useState('');
  const [confirmNote, setConfirmNote] = useState('');
  const [pendingRejectManager, setPendingRejectManager] = useState<Record<string, unknown> | null>(null);
  const [rejectNote, setRejectNote] = useState('');
  const [pendingRevokeManager, setPendingRevokeManager] = useState<Record<string, unknown> | null>(null);
  const [revokeNote, setRevokeNote] = useState('');
  const [pendingRetryManager, setPendingRetryManager] = useState<Record<string, unknown> | null>(null);
  const [retrySearchName, setRetrySearchName] = useState('');
  const [retryNote, setRetryNote] = useState('');
  // MVP6-06: Historical Backfill + Batch Reparse state moved to
  // /admin/13f/jobs along with their Cards + mutations.
  // MVP6-05: Corporate Action Confirm state moved to
  // /admin/13f/holdings along with the form/drawer that consumed it.
  const refreshAdminData = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['admin-13f-readiness'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-quarters'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-tasks'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-jobs'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-managers'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-quality'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-amendments'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-amendments-pending'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-filings'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-holdings-coverage'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-unresolved-cusips'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-parse-runs'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-quarter-detail'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-workers'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-job-detail'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-13f-edgar-rate-limit'] }),
    ]);
  }, [queryClient]);
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
  const retryCikSearch = useMutation({
    mutationFn: async ({
      managerId,
      searchName,
      note,
    }: {
      managerId: number;
      searchName: string;
      note: string | null;
    }) =>
      (await apiClient.post(`/admin/13f/managers/${managerId}/retry-cik-search`, {
        search_name: searchName,
        note,
      })).data,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['admin-13f-readiness'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-tasks'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-13f-managers'] }),
      ]);
    },
  });
  // MVP6-06: hbPreviewMutation / hbEnqueueMutation / brPreviewMutation /
  // brEnqueueMutation moved to /admin/13f/jobs along with the Historical
  // Backfill + Batch Reparse Cards.
  // MVP6-05: caPreviewMutation + caConfirmMutation moved to
  // /admin/13f/holdings.

  const readiness = useMemo(
    () => normalizeReadiness(readinessQuery.data ?? {}),
    [readinessQuery.data]
  );
  // MVP6-07: readinessThresholds + quarters + qualityReports +
  // workers + hasAvailableWorker + operationalHealth memos moved
  // to /admin/13f/readiness along with the surfaces that consumed
  // them.
  const tasks = useMemo(() => normalizeTasks(tasksQuery.data?.items ?? []), [tasksQuery.data]);
  // MVP6-04: ``amendments`` / ``pendingAmendments`` /
  // ``pendingAmendmentGroups`` / ``adminFilings`` memos moved to
  // ``/admin/13f/filings`` along with the sections that consumed
  // them. The underlying queries are still fired here so the
  // Overview hub Filings card KPI (``pendingAmendmentsQuery.data
  // ?.items?.length``) keeps working.
  const holdingsCoverage = useMemo(
    () => normalizeHoldingsCoverage(holdingsCoverageQuery.data ?? {}),
    [holdingsCoverageQuery.data]
  );
  // MVP6-05: unresolvedCusips memo moved to /admin/13f/holdings.
  // MVP6-04: parseRuns memo moved to /admin/13f/filings.
  const edgarRateLimit = useMemo(
    () => normalizeEdgarRateLimit(edgarRateLimitQuery.data ?? {}),
    [edgarRateLimitQuery.data]
  );
  // MVP6-06: workerRows memo (table-row paging logic for the Worker
  // Heartbeat Card) moved to /admin/13f/jobs.
  // MVP6-02: ``managers`` memoized list removed — its only consumer
  // was the Managers section on this page, now moved to
  // ``/admin/13f/managers``. The Overview hub Managers card reads
  // ``managersQuery.data?.items?.length`` directly.
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

  const prevActiveKeys = useRef(new Set<string>());
  useEffect(() => {
    const currentKeys = activeLockKeys;
    const wasActive = prevActiveKeys.current;
    const someJobFinished = Array.from(wasActive).some((key) => !currentKeys.has(key));

    if (someJobFinished) {
      refreshAdminData();
    }

    prevActiveKeys.current = currentKeys;
  }, [activeLockKeys, refreshAdminData]);

  // MVP6-07: selectedQuarterDetail + isLoading aggregate + operationalHealth
  // memo moved to /admin/13f/readiness.
  // MVP6-06: selectedJob (job detail drawer data) moved to /admin/13f/jobs.
  // MVP6-04: selectedAmendment moved to /admin/13f/filings.

  const latestQuarter = readiness.latestUsableQuarter === '—' ? undefined : readiness.latestUsableQuarter;
  const targetQuarter = manualQuarter.trim() || latestQuarter;
  const targetAccession = accessionNo.trim();

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

  // MVP6-02: ``handleConfirm/Reject/Revoke/RetryManager`` removed
  // along with the Managers section that called them. The CIK review
  // dialogs (``<ManagerCikDialogs>``) remain rendered on the index
  // page with their state + submit/close helpers intact, so the
  // CIK review flow can be re-triggered from the new Managers
  // page in a future ticket without re-plumbing here.

  function closeConfirmManagerDialog() {
    setPendingConfirmManager(null);
    setConfirmCik('');
    setConfirmNote('');
  }

  function submitConfirmManagerDialog() {
    if (!pendingConfirmManager) return;
    const managerId = Number(pendingConfirmManager.id);
    if (!Number.isFinite(managerId)) return;
    confirmManager.mutate({
      managerId,
      cik: confirmCik.trim(),
      note: confirmNote.trim() || null,
    });
    closeConfirmManagerDialog();
  }

  function closeRejectManagerDialog() {
    setPendingRejectManager(null);
    setRejectNote('');
  }

  function submitRejectManagerDialog() {
    if (!pendingRejectManager) return;
    const managerId = Number(pendingRejectManager.id);
    if (!Number.isFinite(managerId)) return;
    rejectManager.mutate({ managerId, note: rejectNote.trim() || null });
    closeRejectManagerDialog();
  }

  function closeRevokeManagerDialog() {
    setPendingRevokeManager(null);
    setRevokeNote('');
  }

  function submitRevokeManagerDialog() {
    if (!pendingRevokeManager) return;
    const managerId = Number(pendingRevokeManager.id);
    if (!Number.isFinite(managerId)) return;
    revokeManager.mutate({ managerId, note: revokeNote.trim() });
    closeRevokeManagerDialog();
  }

  function closeRetryManagerDialog() {
    setPendingRetryManager(null);
    setRetrySearchName('');
    setRetryNote('');
  }

  function submitRetryManagerDialog() {
    if (!pendingRetryManager) return;
    const managerId = Number(pendingRetryManager.id);
    if (!Number.isFinite(managerId)) return;
    retryCikSearch.mutate({
      managerId,
      searchName: retrySearchName.trim(),
      note: retryNote.trim() || null,
    });
    closeRetryManagerDialog();
  }

  return (
    <AdminPageLayout
      title="13F Operations"
      description="Readiness, quarter health, admin tasks, manager review, and safe ingestion jobs."
      actions={
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
            queryClient.invalidateQueries({ queryKey: ['admin-13f-amendments-pending'] });
            queryClient.invalidateQueries({ queryKey: ['admin-13f-filings'] });
            queryClient.invalidateQueries({ queryKey: ['admin-13f-holdings-coverage'] });
            queryClient.invalidateQueries({ queryKey: ['admin-13f-unresolved-cusips'] });
            queryClient.invalidateQueries({ queryKey: ['admin-13f-parse-runs'] });
            queryClient.invalidateQueries({ queryKey: ['admin-13f-quarter-detail'] });
            queryClient.invalidateQueries({ queryKey: ['admin-13f-workers'] });
          }}
        >
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      }
    >
      {/* MVP6-01 Overview hub — navigation cards linking to each
          functional surface. While MVP6-02..07 are pending, each card
          is an anchor link to the relevant section below; once a
          route ships, that ticket flips the href to a real route. */}
      <section aria-label="13F admin surfaces">
        <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
          Surfaces
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
          <Link
            href="/admin/13f/managers"
            className="block rounded-md border border-border/70 p-3 transition-colors hover:bg-muted/40"
          >
            <div className="text-xs uppercase text-muted-foreground">Managers</div>
            <div className="mt-1 text-base font-semibold">
              {managersQuery.isPending ? '—' : `${managersQuery.data?.items?.length ?? 0} managers`}
            </div>
            <div className="text-xs text-muted-foreground">CIK review · classification · backfill</div>
          </Link>
          <Link
            href="/admin/13f/sync"
            className="block rounded-md border border-border/70 p-3 transition-colors hover:bg-muted/40"
          >
            <div className="text-xs uppercase text-muted-foreground">Daily Sync</div>
            <div className="mt-1 text-base font-semibold">
              {edgarRateLimitQuery.isPending ? '—' : edgarRateLimit.mode}
            </div>
            <div className="text-xs text-muted-foreground">EDGAR rate limit · no-index calendar</div>
          </Link>
          <Link
            href="/admin/13f/filings"
            className="block rounded-md border border-border/70 p-3 transition-colors hover:bg-muted/40"
          >
            <div className="text-xs uppercase text-muted-foreground">Filings</div>
            <div className="mt-1 text-base font-semibold">
              {pendingAmendmentsQuery.isPending
                ? '—'
                : `${pendingAmendmentsQuery.data?.items?.length ?? 0} pending`}
            </div>
            <div className="text-xs text-muted-foreground">Parse status · amendments · reparse</div>
          </Link>
          <Link
            href="/admin/13f/holdings"
            className="block rounded-md border border-border/70 p-3 transition-colors hover:bg-muted/40"
          >
            <div className="text-xs uppercase text-muted-foreground">Holdings</div>
            <div className="mt-1 text-base font-semibold">
              {holdingsCoverageQuery.isPending
                ? '—'
                : holdingsCoverage.linkedRatioLabel || '—'}
            </div>
            <div className="text-xs text-muted-foreground">Coverage · CUSIP workflow</div>
          </Link>
          <Link
            href="/admin/13f/jobs"
            className="block rounded-md border border-border/70 p-3 transition-colors hover:bg-muted/40"
          >
            <div className="text-xs uppercase text-muted-foreground">Jobs</div>
            <div className="mt-1 text-base font-semibold">
              {jobsQuery.isPending ? '—' : `${jobsQuery.data?.items?.length ?? 0} runs`}
            </div>
            <div className="text-xs text-muted-foreground">Queue · retry · stale-lock</div>
          </Link>
          <Link
            href="/admin/13f/readiness"
            className="block rounded-md border border-border/70 p-3 transition-colors hover:bg-muted/40"
          >
            <div className="text-xs uppercase text-muted-foreground">Readiness</div>
            <div className="mt-1 text-base font-semibold">
              {readinessQuery.isPending
                ? '—'
                : readiness.readinessLevel.replaceAll('_', ' ')}
            </div>
            <div className="text-xs text-muted-foreground">Blockers · quality findings</div>
          </Link>
          <Link
            href="/admin/13f/readiness"
            className="block rounded-md border border-border/70 p-3 transition-colors hover:bg-muted/40"
          >
            <div className="text-xs uppercase text-muted-foreground">Oracle&apos;s Lens</div>
            <div className="mt-1 text-base font-semibold">
              {unknownManagerPriorityQuery.isPending
                ? '—'
                : `${(unknownManagerPriorityQuery.data?.items as unknown[] | undefined)?.length ?? 0} unknown`}
            </div>
            <div className="text-xs text-muted-foreground">Unknown-manager priority queue</div>
          </Link>
        </div>
      </section>

      {/* MVP6-07: Data Readiness & Operations Health Card moved to
          /admin/13f/readiness. Overview hub is now a thin nav hub
          (KPI strip + Tasks Card + Manual Controls + dialog mounts). */}

      {/* MVP6-06: EDGAR Rate Limit Card moved to /admin/13f/jobs.
          Overview hub still surfaces the mode chip in the header
          strip via ``edgarRateLimit.mode``. */}

      {/* MVP6-07: Quality Reports Card moved to /admin/13f/readiness. */}

      {/* MVP6-05: Holdings Coverage + Unresolved CUSIPs moved to
          /admin/13f/holdings. */}

      {/* MVP6-06: Worker Heartbeat Card moved to /admin/13f/jobs.
          ``hasAvailableWorker`` derivation stays on this page so
          the Tasks Card readiness gating still works. */}

      {/* MVP6-07: Quarters Card moved to /admin/13f/readiness along
          with the Quarter Detail Drawer. */}

      <div className="grid grid-cols-1 gap-4">
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
                <div key={task.renderKey ?? task.code} className="rounded-md border border-border/70 p-3">
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

      {/* MVP6-06: Historical Backfill Card moved to /admin/13f/jobs. */}

      {/* MVP6-07: Needs Validation + Unknown Manager Type Priority
          Cards moved to /admin/13f/readiness. */}

      {/* MVP6-06: Batch Reparse Card moved to /admin/13f/jobs. */}

      {/* MVP6-05: Corporate Action Mapping Card + DrawerShell moved
          to /admin/13f/holdings along with the MVP3-08 confirm flow. */}

      <div id="managers" className="grid grid-cols-1 scroll-mt-6 gap-4">
        <Card className="rounded-md">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Managers</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>
              Manager management lives on the dedicated{' '}
              <Link href="/admin/13f/managers" className="font-medium text-foreground hover:underline">
                Managers page
              </Link>
              {' '}— list with filters, CIK review, manager_type classification,
              and per-manager audit history (CIK + manager_type events).
            </p>
            <Button asChild size="sm" variant="outline">
              <Link href="/admin/13f/managers">Open Managers page →</Link>
            </Button>
          </CardContent>
        </Card>

        {/* MVP6-06: Job Runs Card moved to /admin/13f/jobs. */}
      </div>

      {/* MVP6-06: inline Dialogs lifted to shared components in
          frontend/components/admin13f/. The state + mutations stay
          on the index page because the Tasks Card + Manual
          Triggers still call ``runJob`` / ``requestStaleJobLockRelease``. */}
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

      <ManagerCikDialogs
        pendingConfirmManager={pendingConfirmManager}
        confirmCik={confirmCik}
        confirmNote={confirmNote}
        confirmPending={confirmManager.isPending}
        onConfirmCikChange={setConfirmCik}
        onConfirmNoteChange={setConfirmNote}
        onCloseConfirm={closeConfirmManagerDialog}
        onSubmitConfirm={submitConfirmManagerDialog}
        pendingRejectManager={pendingRejectManager}
        rejectNote={rejectNote}
        rejectPending={rejectManager.isPending}
        onRejectNoteChange={setRejectNote}
        onCloseReject={closeRejectManagerDialog}
        onSubmitReject={submitRejectManagerDialog}
        pendingRevokeManager={pendingRevokeManager}
        revokeNote={revokeNote}
        revokePending={revokeManager.isPending}
        onRevokeNoteChange={setRevokeNote}
        onCloseRevoke={closeRevokeManagerDialog}
        onSubmitRevoke={submitRevokeManagerDialog}
        pendingRetryManager={pendingRetryManager}
        retrySearchName={retrySearchName}
        retryNote={retryNote}
        retryPending={retryCikSearch.isPending}
        onRetrySearchNameChange={setRetrySearchName}
        onRetryNoteChange={setRetryNote}
        onCloseRetry={closeRetryManagerDialog}
        onSubmitRetry={submitRetryManagerDialog}
      />

      {/* MVP6-07: Quarter Detail Drawer moved to /admin/13f/readiness. */}
      {/* MVP6-06: Job Detail Drawer moved to /admin/13f/jobs. */}
    </AdminPageLayout>
  );
}
