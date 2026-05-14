'use client';

/**
 * MVP6-04: Filings + Amendments dedicated route.
 *
 * Lifted from the two large Cards previously at the top of the
 * index page. Side-drawer detail views reuse the existing
 * ``DrawerShell`` primitive. Per SR1, "Reprocess via job preview"
 * stays on the index page; the new route uses direct POST
 * mutations for Reparse + Resolve. Quarter filter deferred per
 * SR2 (no backend support).
 */
import Link from 'next/link';
import { useMemo, useState, type ComponentProps } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { History, Loader2 } from 'lucide-react';

import apiClient from '@/lib/api/client';
import { AdminPageLayout } from '@/components/admin13f/AdminPageLayout';
import { AdminLoadingState } from '@/components/admin13f/AdminLoadingState';
import { AdminEmptyState } from '@/components/admin13f/AdminEmptyState';
import { AdminErrorState } from '@/components/admin13f/AdminErrorState';
import { DrawerShell } from '@/components/admin13f/Admin13FPrimitives';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
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
  useAmendmentDetailQuery,
  useAmendmentsQuery,
  useFilingsQuery,
  useParseRunsQuery,
  usePendingAmendmentsQuery,
} from '@/lib/admin13f/queries';

const {
  normalizeAdminFilings,
  normalizeAmendments,
  normalizeParseRuns,
} = thirteenfAdmin as {
  normalizeAdminFilings: (data: unknown) => { items: Record<string, unknown>[]; total: number };
  normalizeAmendments: (items: unknown) => Record<string, unknown>[];
  normalizeParseRuns: (data: unknown) => { items: Record<string, unknown>[]; total: number; accessionNumber: string };
};

function formatInteger(value: unknown): string {
  if (typeof value !== 'number') return '—';
  return value.toLocaleString('en-US');
}

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

const RESOLVE_ACTIONS = [
  { value: 'mark_resolved', label: 'Mark resolved (no further action)' },
  { value: 'mark_failed', label: 'Mark failed (manual intervention required)' },
];

export default function FilingsAdminPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [filingParseStatus, setFilingParseStatus] = useState('all');
  const filingsQuery = useFilingsQuery(filingParseStatus);
  const amendmentsQuery = useAmendmentsQuery();
  const pendingAmendmentsQuery = usePendingAmendmentsQuery();

  const adminFilings = useMemo(
    () => normalizeAdminFilings(filingsQuery.data ?? {}),
    [filingsQuery.data],
  );
  const pendingAmendments = useMemo(
    () => normalizeAdminFilings(pendingAmendmentsQuery.data ?? {}),
    [pendingAmendmentsQuery.data],
  );
  const pendingAmendmentGroups =
    (pendingAmendmentsQuery.data as { groups?: Record<string, Record<string, number>> } | undefined)
      ?.groups ?? {};
  const amendments = useMemo(
    () =>
      normalizeAmendments(
        (amendmentsQuery.data as { items?: unknown } | undefined)?.items ?? [],
      ),
    [amendmentsQuery.data],
  );

  // Drawer state.
  const [selectedFilingAccession, setSelectedFilingAccession] = useState<string | null>(null);
  const [selectedAmendmentAccession, setSelectedAmendmentAccession] = useState<string | null>(null);

  const parseRunsQuery = useParseRunsQuery(selectedFilingAccession);
  const amendmentDetailQuery = useAmendmentDetailQuery(selectedAmendmentAccession);

  const parseRuns = useMemo(
    () => normalizeParseRuns(parseRunsQuery.data ?? {}),
    [parseRunsQuery.data],
  );
  const amendmentDetail =
    (amendmentDetailQuery.data as Record<string, unknown> | undefined) ?? null;

  // Mutations.
  const reparseMutation = useMutation({
    mutationFn: async (accession: string) =>
      (await apiClient.post(`/admin/13f/filings/${accession}/reparse`)).data,
    onSuccess: () => {
      toast({ title: 'Reparse queued' });
      queryClient.invalidateQueries({ queryKey: ['admin-13f-filings'] });
      queryClient.invalidateQueries({
        queryKey: ['admin-13f-parse-runs', selectedFilingAccession],
      });
    },
    onError: (error: unknown) => {
      const message =
        error && typeof error === 'object' && 'message' in error
          ? String((error as { message?: unknown }).message)
          : 'Failed to reparse filing';
      toast({ title: message, variant: 'destructive' });
    },
  });

  const [resolveAction, setResolveAction] = useState<string>('mark_resolved');
  const [resolveNote, setResolveNote] = useState<string>('');
  const resolveMutation = useMutation({
    mutationFn: async (payload: { accession: string; action: string; note: string }) =>
      (
        await apiClient.post(`/admin/13f/amendments/${payload.accession}/resolve`, {
          action: payload.action,
          note: payload.note || null,
        })
      ).data,
    onSuccess: () => {
      toast({ title: 'Amendment resolved' });
      queryClient.invalidateQueries({ queryKey: ['admin-13f-amendments'] });
      queryClient.invalidateQueries({ queryKey: ['admin-13f-amendments-pending'] });
      queryClient.invalidateQueries({ queryKey: ['admin-13f-filings'] });
      queryClient.invalidateQueries({
        queryKey: ['admin-13f-amendment-detail', selectedAmendmentAccession],
      });
      setSelectedAmendmentAccession(null);
      setResolveNote('');
    },
    onError: (error: unknown) => {
      const message =
        error && typeof error === 'object' && 'message' in error
          ? String((error as { message?: unknown }).message)
          : 'Failed to resolve amendment';
      toast({ title: message, variant: 'destructive' });
    },
  });

  return (
    <AdminPageLayout
      title="Filings"
      description="13F filings + amendment accessions. Filter by parse status; drill into per-filing parse-run history and per-amendment detail."
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href="/admin/13f">← Back to Overview</Link>
        </Button>
      }
    >
      {/* Filings table */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
            <span>Filings ({adminFilings.total})</span>
            <Select value={filingParseStatus} onValueChange={setFilingParseStatus}>
              <SelectTrigger className="w-[200px]" aria-label="Filter filings by parse status">
                <SelectValue placeholder="Parse status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All parse statuses</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
                <SelectItem value="succeeded">Succeeded</SelectItem>
                <SelectItem value="partial_success">Partial success</SelectItem>
                <SelectItem value="failed">Failed</SelectItem>
                <SelectItem value="needs_review">Needs review</SelectItem>
              </SelectContent>
            </Select>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {filingsQuery.isPending ? (
            <AdminLoadingState />
          ) : filingsQuery.isError ? (
            <AdminErrorState
              error={filingsQuery.error}
              onRetry={() => filingsQuery.refetch()}
            />
          ) : adminFilings.items.length === 0 ? (
            <AdminEmptyState reason="filter-empty" />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Accession</TableHead>
                    <TableHead>Manager</TableHead>
                    <TableHead>Report</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Caveats</TableHead>
                    <TableHead>Deadline</TableHead>
                    <TableHead>Runs</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {adminFilings.items.map((filing) => (
                    <TableRow key={String(filing.accessionNumber)}>
                      <TableCell>
                        <div className="font-mono text-xs">{String(filing.accessionNumber)}</div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {String(filing.formType)} · {String(filing.reportQuarter)}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{String(filing.managerName)}</div>
                        <div className="text-xs text-muted-foreground">
                          {String(filing.managerCik)}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="text-sm">
                          {String(filing.reportType).replaceAll('_', ' ')}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {String(filing.coverageCompleteness).replaceAll('_', ' ')} ·{' '}
                          {String(filing.coverageType).replaceAll('_', ' ')}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={badgeVariant(String(filing.statusTone))}>
                          {String(filing.parseStatus).replaceAll('_', ' ')}
                        </Badge>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {String(filing.amendmentStatus).replaceAll('_', ' ')}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex max-w-[240px] flex-wrap gap-1">
                          {(Array.isArray(filing.caveatCodes) ? filing.caveatCodes : []).map(
                            (code) => (
                              <Badge
                                key={String(code)}
                                variant={
                                  code === 'NOTICE_REPORTED_ELSEWHERE' ? 'warning' : 'outline'
                                }
                              >
                                {String(code).replaceAll('_', ' ').toLowerCase()}
                              </Badge>
                            ),
                          )}
                          {(Array.isArray(filing.caveatCodes) ? filing.caveatCodes : []).length ===
                          0 ? (
                            <span className="text-sm text-muted-foreground">—</span>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {String(filing.officialFilingDeadline ?? '—')}
                      </TableCell>
                      <TableCell>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            setSelectedFilingAccession(String(filing.accessionNumber))
                          }
                        >
                          <History className="mr-2 h-3.5 w-3.5" />
                          Parse runs
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div className="mt-3 text-xs text-muted-foreground">
                Showing {formatInteger(adminFilings.items.length)} of{' '}
                {formatInteger(adminFilings.total)} filings. Holdings count uses — when
                unavailable.
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Amendment accessions */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Amendment Accessions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="mb-4 flex flex-wrap gap-2">
            {Object.entries(pendingAmendmentGroups).map(([type, statuses]) => (
              <Badge key={type} variant="warning">
                {type}: {formatInteger(statuses.amendments_pending ?? 0)} pending
              </Badge>
            ))}
            {pendingAmendments.total > 0 ? (
              <Badge variant="outline">
                {formatInteger(pendingAmendments.total)} pending total
              </Badge>
            ) : null}
          </div>
          {amendmentsQuery.isPending ? (
            <AdminLoadingState />
          ) : amendmentsQuery.isError ? (
            <AdminErrorState
              error={amendmentsQuery.error}
              onRetry={() => amendmentsQuery.refetch()}
            />
          ) : amendments.length === 0 ? (
            <AdminEmptyState
              reason="not-seeded"
              message="No 13F/A amendments recorded yet."
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Accession</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Manager</TableHead>
                    <TableHead>Supersedes</TableHead>
                    <TableHead>Holdings</TableHead>
                    <TableHead>Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {amendments.slice(0, 50).map((amendment) => (
                    <TableRow key={String(amendment.accessionNo)}>
                      <TableCell>
                        <div className="font-mono text-xs">{String(amendment.accessionNo)}</div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {String(amendment.quarter)} · filed {String(amendment.filedAt ?? '—')}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={badgeVariant(String(amendment.statusTone))}>
                          {String(amendment.status).replaceAll('_', ' ')}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{String(amendment.managerName)}</div>
                        <div className="mt-1 font-mono text-xs text-muted-foreground">
                          {String(amendment.managerCik)}
                        </div>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {String(amendment.supersedesAccessionNo ?? '—')}
                      </TableCell>
                      <TableCell>{formatInteger(amendment.holdingsCount)}</TableCell>
                      <TableCell>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            setSelectedAmendmentAccession(String(amendment.accessionNo))
                          }
                        >
                          Review
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Parse runs drawer */}
      {selectedFilingAccession !== null ? (
        <DrawerShell
          title="Parse Run History"
          description={
            <span className="font-mono text-xs">{selectedFilingAccession}</span>
          }
          closeLabel="Close parse run history"
          labelledBy="parse-run-history-title"
          maxWidthClassName="max-w-[620px]"
          onClose={() => setSelectedFilingAccession(null)}
        >
          {parseRunsQuery.isPending ? (
            <AdminLoadingState variant="compact" />
          ) : parseRunsQuery.isError ? (
            <AdminErrorState
              error={parseRunsQuery.error}
              onRetry={() => parseRunsQuery.refetch()}
            />
          ) : parseRuns.items.length === 0 ? (
            <AdminEmptyState reason="not-seeded" message="No parse runs recorded yet." />
          ) : (
            <div className="space-y-3">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={reparseMutation.isPending}
                onClick={() => reparseMutation.mutate(selectedFilingAccession!)}
              >
                {reparseMutation.isPending ? (
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                ) : null}
                Reparse filing
              </Button>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Run</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Holdings</TableHead>
                    <TableHead>Job</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {parseRuns.items.map((run) => (
                    <TableRow key={String(run.id)}>
                      <TableCell className="font-mono text-xs">
                        #{String(run.id)}
                        {run.isCurrent ? (
                          <Badge className="ml-2" variant="success">
                            current
                          </Badge>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        <Badge variant={badgeVariant(String(run.statusTone))}>
                          {String(run.status).replaceAll('_', ' ')}
                        </Badge>
                        {run.error ? (
                          <div className="mt-1 max-w-[200px] truncate text-xs text-rose-700">
                            {String(run.error)}
                          </div>
                        ) : null}
                      </TableCell>
                      <TableCell>{formatInteger(run.holdingsCount)}</TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {String(run.jobRunId ?? '—')}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </DrawerShell>
      ) : null}

      {/* Amendment detail drawer */}
      {selectedAmendmentAccession !== null ? (
        <DrawerShell
          title="Amendment Detail"
          description={
            <span className="font-mono text-xs">{selectedAmendmentAccession}</span>
          }
          closeLabel="Close amendment detail"
          labelledBy="amendment-detail-title"
          maxWidthClassName="max-w-[560px]"
          onClose={() => {
            setSelectedAmendmentAccession(null);
            setResolveNote('');
          }}
        >
          {amendmentDetailQuery.isPending ? (
            <AdminLoadingState variant="compact" />
          ) : amendmentDetailQuery.isError ? (
            <AdminErrorState
              error={amendmentDetailQuery.error}
              onRetry={() => amendmentDetailQuery.refetch()}
            />
          ) : !amendmentDetail ? (
            <AdminEmptyState reason="not-seeded" message="Amendment detail not available." />
          ) : (
            <div className="space-y-4">
              <div className="grid gap-2 text-sm">
                <div>
                  <div className="text-xs uppercase text-muted-foreground">Status</div>
                  <Badge variant="outline">
                    {String(amendmentDetail.status ?? '—').replaceAll('_', ' ')}
                  </Badge>
                </div>
                <div>
                  <div className="text-xs uppercase text-muted-foreground">Form type</div>
                  <div>{String(amendmentDetail.form_type ?? '—')}</div>
                </div>
                <div>
                  <div className="text-xs uppercase text-muted-foreground">Supersedes</div>
                  <div className="font-mono text-xs">
                    {String(amendmentDetail.supersedes_accession_no ?? '—')}
                  </div>
                </div>
                {amendmentDetail.parse_error ? (
                  <div className="rounded-md border border-rose-300/70 bg-rose-50 p-2 text-xs text-rose-900">
                    {String(amendmentDetail.parse_error)}
                  </div>
                ) : null}
              </div>

              <div className="rounded-md border border-border/70 p-3 text-sm">
                <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                  Resolve
                </div>
                <Select value={resolveAction} onValueChange={setResolveAction}>
                  <SelectTrigger aria-label="Resolution action">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {RESOLVE_ACTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Textarea
                  className="mt-2"
                  placeholder="Resolution note (optional)"
                  rows={2}
                  value={resolveNote}
                  onChange={(e) => setResolveNote(e.target.value)}
                />
                <Button
                  type="button"
                  size="sm"
                  className="mt-2"
                  disabled={resolveMutation.isPending}
                  onClick={() =>
                    resolveMutation.mutate({
                      accession: selectedAmendmentAccession!,
                      action: resolveAction,
                      note: resolveNote,
                    })
                  }
                >
                  {resolveMutation.isPending ? (
                    <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                  ) : null}
                  Apply resolution
                </Button>
              </div>
            </div>
          )}
        </DrawerShell>
      ) : null}
    </AdminPageLayout>
  );
}
