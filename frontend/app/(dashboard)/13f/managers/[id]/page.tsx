'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { AlertTriangle, ArrowLeft, ArrowRight, Info } from 'lucide-react';

import apiClient from '@/lib/api/client';
import managerHelpers from '@/lib/thirteenfManagers';
import ManagerResearchWorkbench, {
  type ManagerView,
} from '@/components/thirteenf/ManagerResearchWorkbench';
import { ManagerFollowButton } from '@/components/research/ManagerFollowButton';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

const {
  normalizeManagerHistory,
  normalizeManagerHoldings,
  normalizeManagers,
  normalizeQuarters,
  titleizeCode,
} = managerHelpers;

const MANAGER_VIEWS = new Set<ManagerView>(['holdings', 'activity', 'buys', 'sells', 'history']);

function readViewFromLocation(): ManagerView {
  if (typeof window === 'undefined') return 'holdings';
  const candidate = new URLSearchParams(window.location.search).get('view') as ManagerView | null;
  return candidate && MANAGER_VIEWS.has(candidate) ? candidate : 'holdings';
}

export default function ThirteenFManagerDetailPage() {
  const params = useParams();
  const rawId = Array.isArray(params?.id) ? params.id[0] : params?.id;
  const managerId = Number(rawId);
  const [selectedQuarter, setSelectedQuarter] = useState('');
  const [activeView, setActiveView] = useState<ManagerView>('holdings');

  useEffect(() => {
    const syncView = () => setActiveView(readViewFromLocation());
    syncView();
    window.addEventListener('popstate', syncView);
    return () => window.removeEventListener('popstate', syncView);
  }, []);

  const updateView = (view: ManagerView) => {
    setActiveView(view);
    const url = new URL(window.location.href);
    if (view === 'holdings') url.searchParams.delete('view');
    else url.searchParams.set('view', view);
    window.history.pushState({}, '', `${url.pathname}${url.search}${url.hash}`);
  };

  const managersQuery = useQuery({
    queryKey: ['13f-user-managers'],
    queryFn: async () => {
      const response = await apiClient.get('/13f/managers');
      return normalizeManagers(response.data?.items ?? []);
    },
  });
  const manager = useMemo(
    () => (managersQuery.data ?? []).find((item) => item.id === managerId) ?? null,
    [managerId, managersQuery.data],
  );
  const quartersQuery = useQuery({
    queryKey: ['13f-manager-quarters', managerId],
    enabled: Number.isFinite(managerId),
    queryFn: async () => {
      const response = await apiClient.get(`/13f/managers/${managerId}/quarters`);
      return normalizeQuarters(response.data?.items ?? []);
    },
  });
  const quarters = useMemo(() => quartersQuery.data ?? [], [quartersQuery.data]);

  useEffect(() => {
    if (!selectedQuarter && quarters.length && quarters[0].quarter) {
      setSelectedQuarter(quarters[0].quarter);
    }
  }, [quarters, selectedQuarter]);

  const holdingsQuery = useQuery({
    queryKey: ['13f-manager-holdings', managerId, selectedQuarter],
    enabled: Number.isFinite(managerId) && Boolean(selectedQuarter),
    queryFn: async () => {
      const response = await apiClient.get(
        `/13f/managers/${managerId}/holdings?quarter=${encodeURIComponent(selectedQuarter)}`,
      );
      return normalizeManagerHoldings(response.data);
    },
  });
  const historyQuery = useQuery({
    queryKey: ['13f-manager-history', managerId],
    enabled: Number.isFinite(managerId),
    queryFn: async () => {
      const response = await apiClient.get(`/13f/managers/${managerId}/history`);
      return normalizeManagerHistory(response.data);
    },
  });
  const selectedQuarterMeta = quarters.find((item) => item.quarter === selectedQuarter) ?? null;

  if (!Number.isFinite(managerId)) {
    return <div className="text-sm text-rose-700">Invalid manager identifier.</div>;
  }

  return (
    <div className="space-y-5">
      <Button asChild variant="ghost" size="sm" className="-ml-2">
        <Link href="/13f/managers">
          <ArrowLeft className="h-4 w-4" />
          All managers
        </Link>
      </Button>

      {managersQuery.isLoading ? (
        <div className="text-sm text-muted-foreground">Loading manager profile…</div>
      ) : !manager ? (
        <div className="rounded-md border border-rose-300/70 bg-rose-50 p-4 text-sm text-rose-800">
          This active 13F manager could not be found.
        </div>
      ) : (
        <>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                13F manager research
              </div>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight">{manager.displayName}</h1>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant="outline">{titleizeCode(manager.stylePrimary)}</Badge>
                <Badge variant="secondary">
                  {manager.historicalTurnover
                    ? `${titleizeCode(manager.historicalTurnover)} turnover`
                    : 'Turnover unknown'}
                </Badge>
                <Badge variant="outline">{titleizeCode(manager.capitalStructure)}</Badge>
                <Badge variant="outline" className="font-mono">CIK {manager.cik ?? '—'}</Badge>
              </div>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
                {manager.classificationRationale ??
                  'No curated classification rationale is available for this manager.'}
              </p>
            </div>
            <div className="flex w-full max-w-xs flex-col gap-3">
              <ManagerFollowButton managerId={managerId} />
              <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="manager-quarter">
                Reported quarter
              </label>
              <Select value={selectedQuarter} onValueChange={setSelectedQuarter}>
                <SelectTrigger id="manager-quarter" className="mt-2">
                  <SelectValue placeholder="Select a quarter" />
                </SelectTrigger>
                <SelectContent>
                  {quarters.map((item) =>
                    item.quarter ? (
                      <SelectItem key={item.quarter} value={item.quarter}>
                        {item.quarter} · {titleizeCode(item.status)}
                      </SelectItem>
                    ) : null,
                  )}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex gap-3 rounded-md border border-amber-300/70 bg-amber-50 px-4 py-3 text-sm text-amber-950">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              13F filings can arrive up to 45 days after quarter end and cover reportable long US
              securities—not the manager&apos;s complete or current portfolio, cost basis, short book,
              or a buy recommendation. Options are shown separately and are not directional proof.
            </div>
          </div>

          {selectedQuarterMeta?.caveats?.length ? (
            <div className="space-y-2">
              {selectedQuarterMeta.caveats.map((caveat) => (
                <div
                  key={caveat.code}
                  className="flex gap-2 rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950"
                >
                  <Info className="mt-0.5 h-4 w-4 shrink-0" />
                  <div>
                    <span className="font-medium">{titleizeCode(caveat.code)}.</span>{' '}
                    {caveat.message}
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          <ManagerResearchWorkbench
            managerId={managerId}
            activeView={activeView}
            onViewChange={updateView}
            selectedQuarter={selectedQuarter}
            holdings={holdingsQuery.data}
            history={historyQuery.data}
            holdingsLoading={holdingsQuery.isLoading}
            historyLoading={historyQuery.isLoading}
          />

          <div className="flex justify-end">
            <Button asChild variant="outline" size="sm">
              <Link href="/13f/oracles-lens">
                Compare value-manager consensus
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
