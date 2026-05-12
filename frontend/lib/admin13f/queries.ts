/**
 * MVP6-01 Tier 3: shared admin/13f query hooks.
 *
 * Lifted from the inline ``useQuery`` definitions previously living
 * at the top of ``frontend/app/(dashboard)/admin/13f/page.tsx``. Each
 * hook is a thin wrapper around ``useQuery`` with the same
 * ``queryKey`` + ``queryFn`` shape the page used inline so mutation
 * ``invalidateQueries`` calls (still in page.tsx) continue to find
 * the right caches.
 *
 * Subsequent MVP6 tickets (MVP6-02..07) import these hooks instead
 * of redefining them per-route.
 */
import { useQuery } from '@tanstack/react-query';

import apiClient from '@/lib/api/client';
import { buildAdminJobsQueryPath } from '@/lib/thirteenfAdmin';

// ===========================================================================
// Health / readiness / overview
// ===========================================================================

export function useReadinessQuery() {
  return useQuery({
    queryKey: ['admin-13f-readiness'],
    queryFn: async () => (await apiClient.get('/admin/13f/readiness')).data,
  });
}

export function useQuartersQuery() {
  return useQuery({
    queryKey: ['admin-13f-quarters'],
    queryFn: async () => (await apiClient.get('/admin/13f/quarters')).data,
  });
}

export function useTasksQuery() {
  return useQuery({
    queryKey: ['admin-13f-tasks'],
    queryFn: async () => (await apiClient.get('/admin/13f/tasks')).data,
  });
}

// ===========================================================================
// Managers
// ===========================================================================

export function useManagersQuery() {
  return useQuery({
    queryKey: ['admin-13f-managers'],
    queryFn: async () => (await apiClient.get('/admin/13f/managers')).data,
  });
}

// MVP4-07b admin priority Card
export function useUnknownManagerPriorityQuery() {
  return useQuery({
    queryKey: ['admin-13f-oracles-lens-unknown-manager-priority'],
    queryFn: async () =>
      (await apiClient.get('/admin/13f/oracles-lens/unknown-manager-priority')).data,
    refetchInterval: 60_000,
  });
}

// ===========================================================================
// Jobs / workers / EDGAR rate limit
// ===========================================================================

interface AdminJobsFilters {
  status: string;
  jobType: string;
  startedFrom: string;
  startedTo: string;
  syncDate: string;
  quarter: string;
}

export function useJobsQuery(filters: AdminJobsFilters) {
  return useQuery({
    queryKey: [
      'admin-13f-jobs',
      filters.status,
      filters.jobType,
      filters.startedFrom,
      filters.startedTo,
      filters.syncDate,
      filters.quarter,
    ],
    queryFn: async () => {
      return (
        await apiClient.get(
          buildAdminJobsQueryPath({
            status: filters.status,
            jobType: filters.jobType,
            startedFrom: filters.startedFrom,
            startedTo: filters.startedTo,
            syncDate: filters.syncDate,
            quarter: filters.quarter,
          })
        )
      ).data;
    },
    refetchInterval: 5000,
  });
}

export function useJobDetailQuery(selectedJobId: number | null) {
  return useQuery({
    queryKey: ['admin-13f-job-detail', selectedJobId],
    queryFn: async () =>
      (await apiClient.get(`/admin/13f/jobs/${selectedJobId}`)).data,
    enabled: selectedJobId !== null,
    refetchInterval: selectedJobId === null ? false : 5000,
  });
}

export function useWorkersQuery() {
  return useQuery({
    queryKey: ['admin-13f-workers'],
    queryFn: async () => (await apiClient.get('/admin/13f/workers')).data,
    refetchInterval: 5000,
  });
}

export function useEdgarRateLimitQuery() {
  return useQuery({
    queryKey: ['admin-13f-edgar-rate-limit'],
    queryFn: async () => (await apiClient.get('/admin/13f/edgar-rate-limit')).data,
    refetchInterval: 30000,
  });
}

// ===========================================================================
// Quality / amendments / needs-validation
// ===========================================================================

export function useQualityQuery() {
  return useQuery({
    queryKey: ['admin-13f-quality'],
    queryFn: async () => (await apiClient.get('/admin/13f/quality')).data,
  });
}

export function useAmendmentsQuery() {
  return useQuery({
    queryKey: ['admin-13f-amendments'],
    queryFn: async () => (await apiClient.get('/admin/13f/amendments')).data,
  });
}

export function usePendingAmendmentsQuery() {
  return useQuery({
    queryKey: ['admin-13f-amendments-pending'],
    queryFn: async () =>
      (await apiClient.get('/admin/13f/amendments/pending?page=1&page_size=50')).data,
  });
}

export function useAmendmentDetailQuery(selectedAmendmentAccession: string | null) {
  return useQuery({
    queryKey: ['admin-13f-amendment-detail', selectedAmendmentAccession],
    queryFn: async () =>
      (await apiClient.get(`/admin/13f/amendments/${selectedAmendmentAccession}`)).data,
    enabled: selectedAmendmentAccession !== null,
  });
}

export function useNeedsValidationQuery() {
  return useQuery({
    queryKey: ['admin-13f-backfill-needs-validation'],
    queryFn: async () =>
      (await apiClient.get('/admin/13f/backfill/needs-validation')).data,
    refetchInterval: 60_000,
  });
}

// ===========================================================================
// Filings / parse runs / quarter detail
// ===========================================================================

export function useFilingsQuery(filingParseStatus: string) {
  return useQuery({
    queryKey: ['admin-13f-filings', filingParseStatus],
    queryFn: async () => {
      const params = new URLSearchParams({ page: '1', page_size: '50' });
      if (filingParseStatus !== 'all') params.set('parse_status', filingParseStatus);
      return (await apiClient.get(`/admin/13f/filings?${params.toString()}`)).data;
    },
  });
}

export function useParseRunsQuery(selectedFilingAccession: string | null) {
  return useQuery({
    queryKey: ['admin-13f-parse-runs', selectedFilingAccession],
    queryFn: async () =>
      (await apiClient.get(
        `/admin/13f/filings/${selectedFilingAccession}/parse-runs?page=1&page_size=50`,
      )).data,
    enabled: selectedFilingAccession !== null,
  });
}

interface QuarterDetailFilters {
  selectedQuarter: string | null;
  quarterFilingStatus: string;
  quarterFilingOffset: number;
}

export function useQuarterDetailQuery(filters: QuarterDetailFilters) {
  const { selectedQuarter, quarterFilingStatus, quarterFilingOffset } = filters;
  return useQuery({
    queryKey: [
      'admin-13f-quarter-detail',
      selectedQuarter,
      quarterFilingStatus,
      quarterFilingOffset,
    ],
    queryFn: async () => {
      const params = new URLSearchParams({
        filing_limit: '25',
        filing_offset: String(quarterFilingOffset),
      });
      if (quarterFilingStatus !== 'all') params.set('filing_status', quarterFilingStatus);
      return (await apiClient.get(
        `/admin/13f/quarters/${selectedQuarter}/detail?${params.toString()}`,
      )).data;
    },
    enabled: selectedQuarter !== null,
  });
}

// ===========================================================================
// Holdings coverage / CUSIPs
// ===========================================================================

export function useHoldingsCoverageQuery(coverageQuarter: string | null) {
  return useQuery({
    queryKey: ['admin-13f-holdings-coverage', coverageQuarter],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (coverageQuarter) params.set('report_quarter', coverageQuarter);
      const suffix = params.toString() ? `?${params.toString()}` : '';
      return (await apiClient.get(`/admin/13f/holdings/coverage${suffix}`)).data;
    },
    enabled: Boolean(coverageQuarter),
  });
}

export function useUnresolvedCusipsQuery() {
  return useQuery({
    queryKey: ['admin-13f-unresolved-cusips'],
    queryFn: async () =>
      (await apiClient.get('/admin/13f/cusip-mappings/unresolved?page=1&page_size=50')).data,
  });
}
