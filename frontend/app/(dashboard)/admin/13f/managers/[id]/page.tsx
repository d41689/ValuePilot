'use client';

/**
 * MVP6-02: manager detail route.
 *
 * Closes the MVP4-07b priority Card deep-link loop. Renders the
 * manager's metadata, exposes the manager_type editor inline, and
 * surfaces the two audit logs (CIK review events from MVP3-03 +
 * manager_type review events from MVP5-05).
 *
 * Manager metadata is sourced client-side from the existing
 * ``useManagersQuery()`` list so V1 doesn't need a new
 * ``GET /admin/13f/managers/{id}`` backend endpoint. The list is
 * paginated to 100 today; if a manager ID isn't in the first 100,
 * the page surfaces ``not-seeded`` empty state. A follow-up can
 * add backend pagination or a dedicated endpoint.
 */
import Link from 'next/link';
import { use, useMemo, useState, type ComponentProps } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import apiClient from '@/lib/api/client';
import { AdminPageLayout } from '@/components/admin13f/AdminPageLayout';
import { AdminLoadingState } from '@/components/admin13f/AdminLoadingState';
import { AdminEmptyState } from '@/components/admin13f/AdminEmptyState';
import { AdminErrorState } from '@/components/admin13f/AdminErrorState';
import {
  ManagerTypeEditorDialog,
  type ManagerTypeEditorState,
} from '@/components/admin13f/ManagerTypeEditorDialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useToast } from '@/components/ui/use-toast';
import {
  useManagerCikReviewEventsQuery,
  useManagerTypeEventsQuery,
  useManagersQuery,
} from '@/lib/admin13f/queries';

type BadgeVariant = ComponentProps<typeof Badge>['variant'];

function statusBadgeVariant(value: string): BadgeVariant {
  if (value === 'active' || value === 'confirmed') return 'success';
  if (value === 'candidate' || value === 'needs_review') return 'warning';
  if (value === 'rejected' || value === 'revoked' || value === 'inactive')
    return 'danger';
  return 'secondary';
}

function formatTimestamp(value: unknown): string {
  if (typeof value !== 'string') return '—';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

interface ManagerDetailPageProps {
  params: Promise<{ id: string }>;
}

export default function ManagerDetailPage({ params }: ManagerDetailPageProps) {
  // Next.js 15: dynamic route ``params`` is a Promise on the client;
  // ``use()`` unwraps it without forcing the component async.
  const { id } = use(params);
  const managerId = Number(id);
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const managersQuery = useManagersQuery();
  const cikEventsQuery = useManagerCikReviewEventsQuery(
    Number.isFinite(managerId) ? managerId : null,
  );
  const typeEventsQuery = useManagerTypeEventsQuery(
    Number.isFinite(managerId) ? managerId : null,
  );
  const [managerTypeEditor, setManagerTypeEditor] = useState<ManagerTypeEditorState | null>(null);
  const [managerTypeDraft, setManagerTypeDraft] = useState<string>('unknown');
  const [managerTypeNote, setManagerTypeNote] = useState<string>('');

  const manager = useMemo(() => {
    const items = managersQuery.data?.items;
    if (!Array.isArray(items)) return null;
    return (
      (items as Record<string, unknown>[]).find(
        (m) => Number(m.id) === managerId,
      ) ?? null
    );
  }, [managersQuery.data, managerId]);

  const managerTypeMutation = useMutation({
    mutationFn: async (payload: {
      managerId: number;
      newManagerType: string;
      note: string;
    }) =>
      (
        await apiClient.patch(`/admin/13f/managers/${payload.managerId}/manager-type`, {
          new_manager_type: payload.newManagerType,
          note: payload.note || null,
        })
      ).data,
    onSuccess: (result) => {
      toast({
        title: result.changed
          ? `Manager type updated to ${result.new_manager_type}`
          : `No change — manager_type stayed ${result.new_manager_type}`,
      });
      queryClient.invalidateQueries({ queryKey: ['admin-13f-managers'] });
      queryClient.invalidateQueries({
        queryKey: ['admin-13f-oracles-lens-unknown-manager-priority'],
      });
      queryClient.invalidateQueries({
        queryKey: ['admin-13f-manager-type-events', managerId],
      });
      setManagerTypeEditor(null);
      setManagerTypeNote('');
    },
    onError: (error: unknown) => {
      const message =
        error && typeof error === 'object' && 'message' in error
          ? String((error as { message?: unknown }).message)
          : 'Failed to update manager_type';
      toast({ title: message, variant: 'destructive' });
    },
  });

  if (!Number.isFinite(managerId)) {
    return (
      <AdminPageLayout title="Manager not found">
        <AdminEmptyState
          reason="filter-empty"
          message="The URL doesn't include a valid manager id."
          cta={{ label: 'Back to managers', href: '/admin/13f/managers' }}
        />
      </AdminPageLayout>
    );
  }

  if (managersQuery.isPending) {
    return (
      <AdminPageLayout title={`Manager #${managerId}`}>
        <AdminLoadingState />
      </AdminPageLayout>
    );
  }

  if (managersQuery.isError) {
    return (
      <AdminPageLayout title={`Manager #${managerId}`}>
        <AdminErrorState
          error={managersQuery.error}
          onRetry={() => managersQuery.refetch()}
        />
      </AdminPageLayout>
    );
  }

  if (!manager) {
    return (
      <AdminPageLayout title={`Manager #${managerId}`}>
        <AdminEmptyState
          reason="not-seeded"
          message="No manager found with this id in the current managers query (paginated to the first 100). If this is a valid manager, deep pagination support is a follow-up; for now, navigate to /admin/13f/managers."
          cta={{ label: 'Back to managers', href: '/admin/13f/managers' }}
        />
      </AdminPageLayout>
    );
  }

  const legalName = String(manager.legal_name ?? '—');
  const managerType = (manager.manager_type as string | null | undefined) || 'unknown';
  const matchStatus = String(manager.match_status ?? '—');
  const status = String(manager.status ?? '—');

  const openEditor = () => {
    setManagerTypeEditor({
      managerId,
      currentType: managerType,
      managerName: legalName,
    });
    setManagerTypeDraft(managerType);
    setManagerTypeNote('');
  };

  return (
    <AdminPageLayout
      title={legalName}
      description={`CIK ${String(manager.cik ?? '—')} · ${managerType.replaceAll('_', ' ')}`}
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href="/admin/13f/managers">← Back to Managers</Link>
        </Button>
      }
    >
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
            <span>Manager profile</span>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={statusBadgeVariant(matchStatus)}>
                match: {matchStatus}
              </Badge>
              <Badge variant={statusBadgeVariant(status)}>
                status: {status}
              </Badge>
              <Badge variant={managerType === 'unknown' ? 'warning' : 'secondary'}>
                type: {managerType.replaceAll('_', ' ')}
              </Badge>
              <Button type="button" variant="outline" size="sm" onClick={openEditor}>
                Edit manager_type
              </Button>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <div className="text-xs uppercase text-muted-foreground">Canonical name</div>
              <div>{String(manager.canonical_name ?? '—')}</div>
            </div>
            <div>
              <div className="text-xs uppercase text-muted-foreground">EDGAR legal name</div>
              <div>{String(manager.edgar_legal_name ?? '—')}</div>
            </div>
            <div>
              <div className="text-xs uppercase text-muted-foreground">Source</div>
              <div>{String(manager.source ?? '—')}</div>
            </div>
            <div>
              <div className="text-xs uppercase text-muted-foreground">Confidence</div>
              <div>{String(manager.confidence_score ?? '—')}</div>
            </div>
            <div>
              <div className="text-xs uppercase text-muted-foreground">Superinvestor</div>
              <div>{manager.is_superinvestor ? 'yes' : 'no'}</div>
            </div>
            <div>
              <div className="text-xs uppercase text-muted-foreground">Featured</div>
              <div>{manager.is_featured ? 'yes' : 'no'}</div>
            </div>
          </div>
          {typeof manager.review_note === 'string' && manager.review_note ? (
            <div className="rounded-md border border-border/70 bg-muted/30 p-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">Review note:</span>{' '}
              {String(manager.review_note)}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Manager_type history</CardTitle>
        </CardHeader>
        <CardContent>
          {typeEventsQuery.isPending ? (
            <AdminLoadingState variant="compact" />
          ) : typeEventsQuery.isError ? (
            <AdminErrorState
              error={typeEventsQuery.error}
              onRetry={() => typeEventsQuery.refetch()}
            />
          ) : !typeEventsQuery.data?.items?.length ? (
            <AdminEmptyState reason="not-seeded" />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>From</TableHead>
                    <TableHead>To</TableHead>
                    <TableHead>Reviewer</TableHead>
                    <TableHead>Note</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(typeEventsQuery.data.items as Record<string, unknown>[]).map((event) => (
                    <TableRow key={String(event.id)}>
                      <TableCell className="font-mono text-xs">
                        {formatTimestamp(event.created_at)}
                      </TableCell>
                      <TableCell>{String(event.old_manager_type ?? '—').replaceAll('_', ' ')}</TableCell>
                      <TableCell>{String(event.new_manager_type ?? '—').replaceAll('_', ' ')}</TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        #{String(event.reviewed_by_user_id ?? '—')}
                      </TableCell>
                      <TableCell>{String(event.note ?? '—')}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">CIK review history</CardTitle>
        </CardHeader>
        <CardContent>
          {cikEventsQuery.isPending ? (
            <AdminLoadingState variant="compact" />
          ) : cikEventsQuery.isError ? (
            <AdminErrorState
              error={cikEventsQuery.error}
              onRetry={() => cikEventsQuery.refetch()}
            />
          ) : !cikEventsQuery.data?.items?.length ? (
            <AdminEmptyState reason="not-seeded" />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Event</TableHead>
                    <TableHead>Old CIK</TableHead>
                    <TableHead>New CIK</TableHead>
                    <TableHead>Downstream</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(cikEventsQuery.data.items as Record<string, unknown>[]).map((event) => (
                    <TableRow key={String(event.id)}>
                      <TableCell className="font-mono text-xs">
                        {formatTimestamp(event.created_at)}
                      </TableCell>
                      <TableCell>
                        {String(event.event_type ?? '—').replaceAll('_', ' ')}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {String(event.old_cik ?? '—')}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {String(event.new_cik ?? '—')}
                      </TableCell>
                      <TableCell>
                        {event.requires_downstream_review ? (
                          <Badge variant="warning">
                            {String(event.affected_filings_count ?? 0)} filings
                          </Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <ManagerTypeEditorDialog
        editor={managerTypeEditor}
        setEditor={setManagerTypeEditor}
        draft={managerTypeDraft}
        setDraft={setManagerTypeDraft}
        note={managerTypeNote}
        setNote={setManagerTypeNote}
        onSave={(payload) => managerTypeMutation.mutate(payload)}
        isPending={managerTypeMutation.isPending}
      />
    </AdminPageLayout>
  );
}
