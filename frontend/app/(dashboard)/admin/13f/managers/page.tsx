'use client';

/**
 * MVP6-02: dedicated managers list route.
 *
 * Moved out of the index page's ``#managers`` section. Same table
 * shape as the previous inline implementation (Name / CIK /
 * Manager Type / Candidate Evidence / Latest Audit / Status) plus
 * a match_status filter at the top. Manager names link to
 * ``/admin/13f/managers/[id]`` (replaces the MVP5-05 anchor
 * fallback).
 */
import Link from 'next/link';
import { useMemo, useState, type ComponentProps } from 'react';
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

type BadgeVariant = ComponentProps<typeof Badge>['variant'];
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
import { useToast } from '@/components/ui/use-toast';
import { useManagersQuery } from '@/lib/admin13f/queries';

function statusBadgeVariant(value: string): BadgeVariant {
  if (value === 'active' || value === 'confirmed') return 'success';
  if (value === 'candidate' || value === 'needs_review') return 'warning';
  if (value === 'rejected' || value === 'revoked' || value === 'inactive')
    return 'danger';
  return 'secondary';
}

const MATCH_STATUS_FILTERS = [
  { value: 'all', label: 'All match statuses' },
  { value: 'confirmed', label: 'Confirmed' },
  { value: 'candidate', label: 'Candidate' },
  { value: 'needs_review', label: 'Needs review' },
  { value: 'revoked', label: 'Revoked' },
  { value: 'rejected', label: 'Rejected' },
];

export default function ManagersPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const managersQuery = useManagersQuery();
  const [matchStatusFilter, setMatchStatusFilter] = useState('all');
  const [managerTypeEditor, setManagerTypeEditor] = useState<ManagerTypeEditorState | null>(null);
  const [managerTypeDraft, setManagerTypeDraft] = useState<string>('unknown');
  const [managerTypeNote, setManagerTypeNote] = useState<string>('');

  const managerTypeMutation = useMutation({
    mutationFn: async (payload: {
      managerId: number;
      newManagerType: string;
      note: string;
      evidenceUrl: string;
    }) =>
      (
        await apiClient.patch(`/admin/13f/managers/${payload.managerId}/manager-type`, {
          new_manager_type: payload.newManagerType,
          note: payload.note || null,
          evidence_json: payload.evidenceUrl ? { url: payload.evidenceUrl } : null,
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
      queryClient.invalidateQueries({ queryKey: ['admin-13f-manager-type-events'] });
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

  const openManagerTypeEditor = (manager: {
    id: number;
    manager_type: string | null | undefined;
    legal_name: string | null | undefined;
  }) => {
    const currentType =
      (manager.manager_type as string | null | undefined) || 'unknown';
    setManagerTypeEditor({
      managerId: manager.id,
      currentType,
      managerName: manager.legal_name || `Manager #${manager.id}`,
    });
    setManagerTypeDraft(currentType);
    setManagerTypeNote('');
  };

  const allManagers = useMemo(() => {
    const items = managersQuery.data?.items;
    return Array.isArray(items) ? (items as Record<string, unknown>[]) : [];
  }, [managersQuery.data]);

  const filteredManagers = useMemo(() => {
    if (matchStatusFilter === 'all') return allManagers;
    return allManagers.filter(
      (m) => String(m.match_status ?? '') === matchStatusFilter,
    );
  }, [allManagers, matchStatusFilter]);

  return (
    <AdminPageLayout
      title="Managers"
      description={`Manager universe (${allManagers.length} total). Confirm CIKs, classify by manager_type, and review audit history.`}
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href="/admin/13f">← Back to Overview</Link>
        </Button>
      }
    >
      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex flex-col gap-2 text-base sm:flex-row sm:items-center sm:justify-between">
            <span>Manager list</span>
            <div className="flex flex-wrap items-center gap-2">
              <Select value={matchStatusFilter} onValueChange={setMatchStatusFilter}>
                <SelectTrigger className="w-[180px]" aria-label="Filter by match status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MATCH_STATUS_FILTERS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Badge variant="secondary">{filteredManagers.length} shown</Badge>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {managersQuery.isPending ? (
            <AdminLoadingState />
          ) : managersQuery.isError ? (
            <AdminErrorState
              error={managersQuery.error}
              onRetry={() => managersQuery.refetch()}
            />
          ) : filteredManagers.length === 0 ? (
            <AdminEmptyState reason="filter-empty" />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>CIK</TableHead>
                    <TableHead>Manager Type</TableHead>
                    <TableHead>Match Status</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredManagers.slice(0, 200).map((manager) => {
                    const managerType =
                      (manager.manager_type as string | null | undefined) || 'unknown';
                    const id = Number(manager.id);
                    const legalName = String(manager.legal_name ?? '—');
                    return (
                      <TableRow key={String(id)}>
                        <TableCell className="font-medium">
                          <Link
                            href={`/admin/13f/managers/${id}`}
                            className="hover:underline"
                          >
                            {legalName}
                          </Link>
                        </TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          {String(manager.cik ?? '—')}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <Badge
                              variant={managerType === 'unknown' ? 'warning' : 'secondary'}
                            >
                              {managerType.replaceAll('_', ' ')}
                            </Badge>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2 text-xs"
                              onClick={() =>
                                openManagerTypeEditor({
                                  id,
                                  manager_type: manager.manager_type as
                                    | string
                                    | null
                                    | undefined,
                                  legal_name: legalName,
                                })
                              }
                            >
                              Edit
                            </Button>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={statusBadgeVariant(String(manager.match_status ?? '—'))}
                          >
                            {String(manager.match_status ?? '—')}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={statusBadgeVariant(String(manager.status ?? '—'))}
                          >
                            {String(manager.status ?? '—')}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    );
                  })}
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
