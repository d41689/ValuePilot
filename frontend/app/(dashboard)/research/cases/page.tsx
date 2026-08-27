'use client';

import Link from 'next/link';
import { Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { AlertCircle, ArrowRight, BookOpen, LoaderCircle } from 'lucide-react';

import apiClient from '@/lib/api/client';
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

type CaseState = 'queued' | 'researching' | 'monitoring' | 'closed' | 'voided';

type ResearchCase = {
  id: number;
  stock_id: number;
  ticker: string;
  company_name: string;
  state: CaseState;
  decision: 'watch' | 'own' | 'pass' | null;
  next_review_on: string | null;
  head_revision_number: number;
  updated_at: string;
};

const states: CaseState[] = ['queued', 'researching', 'monitoring', 'closed', 'voided'];

function isOverdue(value: string | null) {
  if (!value) return false;
  return value < new Date().toISOString().slice(0, 10);
}

function ResearchCasesContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedState = searchParams?.get('state') ?? null;
  const activeState = states.includes(requestedState as CaseState)
    ? (requestedState as CaseState)
    : 'all';
  const casesQuery = useQuery({
    queryKey: ['research-cases', activeState],
    queryFn: async () => {
      const query = activeState === 'all' ? '' : `?state=${activeState}`;
      const response = await apiClient.get(`/research/cases${query}`);
      return response.data as { items: ResearchCase[]; total: number };
    },
  });

  function changeState(value: string) {
    const query = value === 'all' ? '' : `?state=${encodeURIComponent(value)}`;
    router.replace(`/research/cases${query}`);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium text-primary">
            <BookOpen className="h-4 w-4" /> Research Cases
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">Decision cycles</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Each cycle preserves its original discovery context, immutable revisions, decision, and next review.
          </p>
        </div>
        <div className="w-full md:w-56">
          <Select value={activeState} onValueChange={changeState}>
            <SelectTrigger aria-label="Filter research cases by lifecycle state">
              <SelectValue placeholder="All lifecycle states" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All lifecycle states</SelectItem>
              {states.map((state) => (
                <SelectItem key={state} value={state}>
                  {state[0].toUpperCase() + state.slice(1)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {casesQuery.isLoading ? (
        <Card><CardContent className="flex items-center gap-2 p-8 text-sm text-muted-foreground"><LoaderCircle className="h-4 w-4 animate-spin" /> Loading research cases…</CardContent></Card>
      ) : casesQuery.isError ? (
        <Card className="border-destructive/40">
          <CardContent className="space-y-4 p-8">
            <div className="flex items-center gap-2 font-medium text-destructive"><AlertCircle className="h-4 w-4" /> Unable to load research cases</div>
            <Button type="button" variant="outline" onClick={() => void casesQuery.refetch()}>Retry</Button>
          </CardContent>
        </Card>
      ) : (casesQuery.data?.items.length ?? 0) === 0 ? (
        <Card><CardContent className="p-10 text-center text-sm text-muted-foreground">No research cases match this lifecycle filter.</CardContent></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {casesQuery.data?.items.map((item) => {
            const overdue = isOverdue(item.next_review_on);
            return (
              <Card key={item.id} className={overdue ? 'border-amber-400/60' : undefined}>
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <CardTitle className="text-base">{item.ticker}</CardTitle>
                      <p className="mt-1 text-sm text-muted-foreground">{item.company_name}</p>
                    </div>
                    <Badge variant={overdue ? 'warning' : 'secondary'}>
                      {overdue ? 'Overdue' : item.state}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4 text-sm">
                  <dl className="grid grid-cols-2 gap-3">
                    <div><dt className="text-xs text-muted-foreground">Decision</dt><dd className="mt-1 font-medium">{item.decision ?? 'Undecided'}</dd></div>
                    <div><dt className="text-xs text-muted-foreground">Head revision</dt><dd className="mt-1 font-medium">{item.head_revision_number}</dd></div>
                    <div className="col-span-2"><dt className="text-xs text-muted-foreground">Next review</dt><dd className="mt-1 font-medium">{item.next_review_on ?? 'Not scheduled'}</dd></div>
                  </dl>
                  <Button asChild className="w-full">
                    <Link href={`/research/cases/${item.id}`}>Open case <ArrowRight className="h-4 w-4" /></Link>
                  </Button>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function ResearchCasesPage() {
  return (
    <Suspense fallback={<Card><CardContent className="p-8 text-sm text-muted-foreground">Loading research cases…</CardContent></Card>}>
      <ResearchCasesContent />
    </Suspense>
  );
}
