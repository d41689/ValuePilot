'use client';

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { AlertTriangle, ChevronRight, Search, Users } from 'lucide-react';

import apiClient from '@/lib/api/client';
import managerHelpers from '@/lib/thirteenfManagers';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
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

const { VALUE_STYLES, filterManagers, normalizeManagers, titleizeCode } = managerHelpers;

const STYLE_OPTIONS = [
  ...VALUE_STYLES,
  'activist',
  'special_situations',
  'growth_long_short',
  'multi_strategy_macro',
  'endowment_passive',
  'unknown',
];

export default function ThirteenFManagersPage() {
  const [scope, setScope] = useState('value');
  const [style, setStyle] = useState('all');
  const [search, setSearch] = useState('');
  const managersQuery = useQuery({
    queryKey: ['13f-user-managers'],
    queryFn: async () => {
      const response = await apiClient.get('/13f/managers');
      return normalizeManagers(response.data?.items ?? []);
    },
  });
  const managers = useMemo(() => managersQuery.data ?? [], [managersQuery.data]);
  const visibleManagers = useMemo(
    () => filterManagers(managers, { scope, style, search }),
    [managers, scope, search, style],
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase text-muted-foreground">
            13F manager research
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Value Investors</h1>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            Start with the investor, then inspect what changed in the reported equity book.
            Value and quality-compounder styles are the default; noisy manager types are opt-in.
          </p>
        </div>
        <div className="rounded-md border border-border/70 bg-background px-3 py-2 text-sm">
          <div className="text-xs uppercase text-muted-foreground">Visible managers</div>
          <div className="mt-1 text-lg font-semibold tabular-nums">
            {visibleManagers.length} / {managers.length}
          </div>
        </div>
      </div>

      <div className="flex gap-3 rounded-md border border-amber-300/70 bg-amber-50 px-4 py-3 text-sm text-amber-950">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          13F filings can arrive up to 45 days after quarter end. They cover reportable long US
          securities, not the manager&apos;s complete portfolio, current holdings, cost basis, short
          book, or a buy recommendation. Options are shown separately and are not directional proof.
        </div>
      </div>

      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Users className="h-4 w-4" />
            Manager universe
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            The default view is defined by reviewed V2 investment style, not manager name or raw
            institutional size.
          </p>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-[1.3fr_1fr_1fr]">
            <div>
              <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="manager-search">
                Search
              </label>
              <div className="relative mt-2">
                <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  id="manager-search"
                  className="pl-9"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Manager, CIK, or investing tag"
                />
              </div>
            </div>
            <div>
              <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="manager-scope">
                Investor scope
              </label>
              <Select value={scope} onValueChange={setScope}>
                <SelectTrigger id="manager-scope" className="mt-2">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="value">Value DNA</SelectItem>
                  <SelectItem value="value_plus_activist">Value + activists</SelectItem>
                  <SelectItem value="all">All tracked managers</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="manager-style">
                Style
              </label>
              <Select value={style} onValueChange={setStyle}>
                <SelectTrigger id="manager-style" className="mt-2">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All styles in scope</SelectItem>
                  {STYLE_OPTIONS.map((option) => (
                    <SelectItem key={option} value={option}>
                      {titleizeCode(option)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="rounded-md">
        <CardContent className="p-0">
          {managersQuery.isLoading ? (
            <div className="p-6 text-sm text-muted-foreground">Loading manager profiles…</div>
          ) : managersQuery.isError ? (
            <div className="p-6 text-sm text-rose-700">Manager profiles could not be loaded.</div>
          ) : visibleManagers.length === 0 ? (
            <div className="p-6 text-sm text-muted-foreground">
              No managers match the current value-investor filters.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Manager</TableHead>
                    <TableHead>Investment DNA</TableHead>
                    <TableHead>Structure / turnover</TableHead>
                    <TableHead>Latest report</TableHead>
                    <TableHead className="w-10" aria-label="Open manager" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleManagers.map((manager) => (
                    <TableRow key={manager.id}>
                      <TableCell>
                        <Link href={`/13f/managers/${manager.id}`} className="font-medium hover:underline">
                          {manager.displayName}
                        </Link>
                        <div className="mt-1 font-mono text-xs text-muted-foreground">
                          CIK {manager.cik ?? '—'}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{titleizeCode(manager.stylePrimary)}</Badge>
                        {manager.classificationRationale ? (
                          <div className="mt-2 max-w-xl text-xs leading-5 text-muted-foreground">
                            {manager.classificationRationale}
                          </div>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        <div className="text-sm">{titleizeCode(manager.capitalStructure)}</div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {manager.historicalTurnover
                            ? `${titleizeCode(manager.historicalTurnover)} turnover`
                            : 'Turnover unknown'}
                        </div>
                      </TableCell>
                      <TableCell>
                        {manager.latestFiling ? (
                          <div>
                            <div className="font-medium">{manager.latestFiling.quarter ?? '—'}</div>
                            <div className="mt-1 flex flex-wrap gap-1.5">
                              <Badge
                                variant={manager.latestFiling.status === 'available' ? 'success' : 'warning'}
                              >
                                {titleizeCode(manager.latestFiling.status)}
                              </Badge>
                              <Badge variant="outline">{manager.latestFiling.formType ?? '—'}</Badge>
                            </div>
                          </div>
                        ) : (
                          <Badge variant="warning">No active filing</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <Link
                          href={`/13f/managers/${manager.id}`}
                          aria-label={`Open ${manager.displayName}`}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                          <ChevronRight className="h-4 w-4" />
                        </Link>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
