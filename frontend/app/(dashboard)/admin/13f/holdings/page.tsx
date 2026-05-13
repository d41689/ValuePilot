'use client';

/**
 * MVP6-05: Holdings Coverage + CUSIP workflow dedicated route.
 *
 * Three sections lifted from the index page:
 *
 *   1. Holdings Coverage panel — coverage summary for the latest
 *      usable quarter (MetricTiles + caveat badges).
 *   2. Unresolved CUSIPs — full table (no longer capped at 6 rows
 *      like the index page preview).
 *   3. Corporate Action Mapping (MVP3-08) — trigger button + side
 *      drawer with the preview-then-confirm form.
 */
import Link from 'next/link';
import { useMemo, useState, type ComponentProps } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Database, Link2, Loader2 } from 'lucide-react';

import apiClient from '@/lib/api/client';
import { AdminPageLayout } from '@/components/admin13f/AdminPageLayout';
import { AdminLoadingState } from '@/components/admin13f/AdminLoadingState';
import { AdminEmptyState } from '@/components/admin13f/AdminEmptyState';
import { AdminErrorState } from '@/components/admin13f/AdminErrorState';
import { DrawerShell, MetricTile } from '@/components/admin13f/Admin13FPrimitives';
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useToast } from '@/components/ui/use-toast';
import thirteenfAdmin from '@/lib/thirteenfAdmin';
import {
  useHoldingsCoverageQuery,
  useReadinessQuery,
  useUnresolvedCusipsQuery,
} from '@/lib/admin13f/queries';

const { normalizeHoldingsCoverage, normalizeUnresolvedCusips } = thirteenfAdmin as {
  normalizeHoldingsCoverage: (data: unknown) => {
    reportQuarter: string;
    totalHoldingsCount: number;
    commonHoldingsCount: number;
    linkedCommonHoldingsCount: number;
    unresolvedCommonHoldingsCount: number;
    optionsCount: number;
    linkedCommonHoldingRatio: number | null;
    linkedCommonHoldingRatioLabel: string;
    combinationReportCount: number;
    confidentialTreatmentCount: number;
  };
  normalizeUnresolvedCusips: (data: unknown) => {
    items: Record<string, unknown>[];
    total: number;
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

export default function HoldingsAdminPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const readinessQuery = useReadinessQuery();
  const coverageQuarter =
    typeof readinessQuery.data?.latest_usable_quarter === 'string'
      ? readinessQuery.data.latest_usable_quarter
      : null;

  const holdingsCoverageQuery = useHoldingsCoverageQuery(coverageQuarter);
  const unresolvedCusipsQuery = useUnresolvedCusipsQuery();

  const holdingsCoverage = useMemo(
    () => normalizeHoldingsCoverage(holdingsCoverageQuery.data ?? {}),
    [holdingsCoverageQuery.data],
  );
  const unresolvedCusips = useMemo(
    () => normalizeUnresolvedCusips(unresolvedCusipsQuery.data ?? {}),
    [unresolvedCusipsQuery.data],
  );

  // Corporate action confirm state + mutations.
  const [caOpen, setCaOpen] = useState(false);
  const [caCusip, setCaCusip] = useState('');
  const [caFromQ, setCaFromQ] = useState('');
  const [caToQ, setCaToQ] = useState('');
  const [caNewTicker, setCaNewTicker] = useState('');
  const [caEvidence, setCaEvidence] = useState('');
  const [caReason, setCaReason] = useState('');
  const [caPreview, setCaPreview] = useState<Record<string, unknown> | null>(null);

  const caPreviewMutation = useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      (
        await apiClient.post('/admin/13f/cusips/corporate-actions/preview', body)
      ).data,
    onSuccess: (data) => setCaPreview(data),
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Preview failed.';
      toast({ title: 'Corporate action preview error', description: msg, variant: 'destructive' });
    },
  });

  const caConfirmMutation = useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      (
        await apiClient.post('/admin/13f/cusips/corporate-actions/confirm', body)
      ).data,
    onSuccess: () => {
      setCaOpen(false);
      setCaPreview(null);
      setCaCusip('');
      setCaFromQ('');
      setCaToQ('');
      setCaNewTicker('');
      setCaEvidence('');
      setCaReason('');
      toast({
        title: 'Corporate action confirmed',
        description:
          'Temporal mapping confirmed. Affected ownership_changes flagged for recomputation.',
      });
      queryClient.invalidateQueries({ queryKey: ['admin-13f-unresolved-cusips'] });
      queryClient.invalidateQueries({ queryKey: ['admin-13f-holdings-coverage'] });
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Confirm failed.';
      toast({
        title: 'Corporate action error',
        description: msg,
        variant: 'destructive',
      });
    },
  });

  return (
    <AdminPageLayout
      title="Holdings Coverage"
      description="Linked-common ratio, unresolved CUSIP queue, and corporate-action temporal mapping confirms."
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href="/admin/13f">← Back to Overview</Link>
        </Button>
      }
    >
      {/* Holdings Coverage */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
            <span className="flex items-center gap-2">
              <Database className="h-4 w-4" />
              Holdings Coverage
            </span>
            <Badge variant="outline">{holdingsCoverage.reportQuarter}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {holdingsCoverageQuery.isPending ? (
            <AdminLoadingState variant="compact" label="Loading holdings coverage..." />
          ) : !coverageQuarter ? (
            <AdminEmptyState reason="readiness-blocked" />
          ) : holdingsCoverageQuery.isError ? (
            <AdminErrorState
              error={holdingsCoverageQuery.error}
              onRetry={() => holdingsCoverageQuery.refetch()}
            />
          ) : (
            <>
              <div className="grid gap-3 md:grid-cols-4">
                <MetricTile
                  label="Total holdings"
                  value={formatInteger(holdingsCoverage.totalHoldingsCount)}
                />
                <MetricTile
                  label="Common holdings"
                  value={formatInteger(holdingsCoverage.commonHoldingsCount)}
                />
                <MetricTile
                  label="Linked common"
                  value={holdingsCoverage.linkedCommonHoldingRatioLabel}
                  detail={`${formatInteger(holdingsCoverage.linkedCommonHoldingsCount)} linked`}
                />
                <MetricTile
                  label="Options"
                  value={formatInteger(holdingsCoverage.optionsCount)}
                />
              </div>
              <div className="flex flex-wrap gap-2 text-sm">
                <Badge
                  variant={
                    holdingsCoverage.unresolvedCommonHoldingsCount > 0 ? 'warning' : 'success'
                  }
                >
                  {formatInteger(holdingsCoverage.unresolvedCommonHoldingsCount)} unresolved common
                </Badge>
                <Badge
                  variant={
                    holdingsCoverage.combinationReportCount > 0 ? 'warning' : 'secondary'
                  }
                >
                  {formatInteger(holdingsCoverage.combinationReportCount)} combination reports
                </Badge>
                <Badge
                  variant={
                    holdingsCoverage.confidentialTreatmentCount > 0 ? 'warning' : 'secondary'
                  }
                >
                  {formatInteger(holdingsCoverage.confidentialTreatmentCount)} confidential treatment
                </Badge>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Unresolved CUSIPs */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Link2 className="h-4 w-4" />
            Unresolved CUSIPs
          </CardTitle>
        </CardHeader>
        <CardContent>
          {unresolvedCusipsQuery.isPending ? (
            <AdminLoadingState />
          ) : unresolvedCusipsQuery.isError ? (
            <AdminErrorState
              error={unresolvedCusipsQuery.error}
              onRetry={() => unresolvedCusipsQuery.refetch()}
            />
          ) : unresolvedCusips.items.length === 0 ? (
            <AdminEmptyState
              reason="filter-empty"
              message="No unresolved current CUSIP mappings."
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>CUSIP</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Issuer</TableHead>
                    <TableHead>Rows</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {unresolvedCusips.items.map((item) => (
                    <TableRow
                      key={`${String(item.cusip)}-${String(item.cusipMappingStatus)}`}
                    >
                      <TableCell className="font-mono text-xs">{String(item.cusip)}</TableCell>
                      <TableCell>
                        <Badge variant={badgeVariant(String(item.statusTone))}>
                          {String(item.cusipMappingStatus).replaceAll('_', ' ')}
                        </Badge>
                      </TableCell>
                      <TableCell className="max-w-[280px] truncate text-sm text-muted-foreground">
                        {String(item.issuerName)}
                      </TableCell>
                      <TableCell>{formatInteger(item.holdingCount)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div className="mt-3 text-xs text-muted-foreground">
                Showing {formatInteger(unresolvedCusips.items.length)} of{' '}
                {formatInteger(unresolvedCusips.total)} current unresolved groups.
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Corporate Action Mapping (MVP3-08) */}
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Link2 className="h-4 w-4" />
            Corporate Action Mapping
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="text-sm text-muted-foreground">
            Manually confirm a CUSIP temporal mapping after a corporate action
            (spin-off, merger, rename). Evidence URL and reason are required per D4.
          </div>
          <Button type="button" variant="outline" onClick={() => setCaOpen(true)}>
            Confirm corporate action mapping
          </Button>
        </CardContent>
      </Card>

      {caOpen ? (
        <DrawerShell
          title="Confirm Corporate Action Mapping"
          description="D4: manual confirmation only. Evidence URL and reason are required."
          closeLabel="Close corporate action confirm"
          labelledBy="ca-confirm-title"
          maxWidthClassName="max-w-xl"
          onClose={() => {
            setCaOpen(false);
            setCaPreview(null);
          }}
        >
          <div className="flex-1 space-y-4 overflow-y-auto p-4">
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <label
                  className="text-xs font-semibold uppercase text-muted-foreground"
                  htmlFor="ca-cusip"
                >
                  CUSIP (9 chars)
                </label>
                <Input
                  id="ca-cusip"
                  className="mt-1 font-mono"
                  maxLength={9}
                  value={caCusip}
                  onChange={(e) => {
                    setCaCusip(e.target.value.toUpperCase());
                    setCaPreview(null);
                  }}
                />
              </div>
              <div>
                <label
                  className="text-xs font-semibold uppercase text-muted-foreground"
                  htmlFor="ca-new-ticker"
                >
                  New ticker (optional)
                </label>
                <Input
                  id="ca-new-ticker"
                  className="mt-1 font-mono"
                  maxLength={10}
                  value={caNewTicker}
                  onChange={(e) => setCaNewTicker(e.target.value.toUpperCase())}
                />
              </div>
              <div>
                <label
                  className="text-xs font-semibold uppercase text-muted-foreground"
                  htmlFor="ca-from-q"
                >
                  Effective from quarter
                </label>
                <Input
                  id="ca-from-q"
                  className="mt-1 font-mono"
                  placeholder="YYYY-Qn"
                  value={caFromQ}
                  onChange={(e) => {
                    setCaFromQ(e.target.value);
                    setCaPreview(null);
                  }}
                />
              </div>
              <div>
                <label
                  className="text-xs font-semibold uppercase text-muted-foreground"
                  htmlFor="ca-to-q"
                >
                  Effective to quarter (optional)
                </label>
                <Input
                  id="ca-to-q"
                  className="mt-1 font-mono"
                  placeholder="leave empty = open-ended"
                  value={caToQ}
                  onChange={(e) => {
                    setCaToQ(e.target.value);
                    setCaPreview(null);
                  }}
                />
              </div>
            </div>
            <div>
              <label
                className="text-xs font-semibold uppercase text-muted-foreground"
                htmlFor="ca-evidence"
              >
                Evidence URL (required)
              </label>
              <Input
                id="ca-evidence"
                className="mt-1"
                placeholder="https://sec.gov/..."
                value={caEvidence}
                onChange={(e) => setCaEvidence(e.target.value)}
              />
            </div>
            <div>
              <label
                className="text-xs font-semibold uppercase text-muted-foreground"
                htmlFor="ca-reason"
              >
                Reason (required)
              </label>
              <Input
                id="ca-reason"
                className="mt-1"
                placeholder="e.g. Spin-off effective YYYY-Qn"
                value={caReason}
                onChange={(e) => setCaReason(e.target.value)}
              />
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={
                  caCusip.length !== 9 || !caFromQ.trim() || caPreviewMutation.isPending
                }
                onClick={() =>
                  caPreviewMutation.mutate({
                    cusip: caCusip,
                    effective_from_quarter: caFromQ.trim(),
                    effective_to_quarter: caToQ.trim() || undefined,
                  })
                }
              >
                {caPreviewMutation.isPending ? (
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                ) : null}
                Preview affected rows
              </Button>
            </div>
            {caPreview ? (
              <div className="space-y-2">
                <div className="rounded-md border border-border/70 p-3 text-sm">
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <div className="text-xs text-muted-foreground">Affected ownership_changes</div>
                      <div className="font-semibold">
                        {String(caPreview['affected_ownership_changes_count'])}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground">Overlapping mapping IDs</div>
                      <div className="font-mono text-xs">
                        {(caPreview['overlapping_mapping_ids'] as number[])?.join(', ') ||
                          'none'}
                      </div>
                    </div>
                  </div>
                </div>
                {(caPreview['overlapping_mapping_ids'] as number[])?.length ? (
                  <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
                    <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />
                    Overlapping mappings detected. Provide{' '}
                    <strong>prior_mapping_id</strong> to supersede, or adjust the
                    effective quarter window.
                  </div>
                ) : null}
                <Button
                  type="button"
                  disabled={
                    !caEvidence.trim() ||
                    !caReason.trim() ||
                    caConfirmMutation.isPending
                  }
                  onClick={() =>
                    caConfirmMutation.mutate({
                      cusip: caCusip,
                      new_ticker: caNewTicker.trim() || undefined,
                      effective_from_quarter: caFromQ.trim(),
                      effective_to_quarter: caToQ.trim() || undefined,
                      evidence_url: caEvidence.trim(),
                      reason: caReason.trim(),
                    })
                  }
                >
                  {caConfirmMutation.isPending ? (
                    <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                  ) : null}
                  Confirm mapping
                </Button>
              </div>
            ) : null}
          </div>
        </DrawerShell>
      ) : null}
    </AdminPageLayout>
  );
}
