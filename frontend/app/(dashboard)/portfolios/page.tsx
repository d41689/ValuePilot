'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, ArrowRight, LoaderCircle, PieChart, Plus } from 'lucide-react';

import apiClient from '@/lib/api/client';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

type Portfolio = {
  id: number;
  name: string;
  description: string | null;
  status: 'active' | 'archived';
  version: number;
  updated_at: string;
};

export default function ManualPortfoliosPage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const portfoliosQuery = useQuery({
    queryKey: ['manual-portfolios'],
    queryFn: async () => {
      const response = await apiClient.get('/portfolios');
      return (response.data?.items ?? []) as Portfolio[];
    },
  });
  const createMutation = useMutation({
    mutationFn: () => apiClient.post('/portfolios', {
      name,
      description: description || null,
    }),
    onSuccess: async () => {
      setName('');
      setDescription('');
      await queryClient.invalidateQueries({ queryKey: ['manual-portfolios'] });
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2 text-sm font-medium text-primary"><PieChart className="h-4 w-4" /> Manual portfolios</div>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Positions tied to decisions</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          These records are entered by you and are not broker-synchronized. They do not claim executions, tax lots, fees, realized gains, or tax accuracy.
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle>Create a manual portfolio</CardTitle><CardDescription>Use it as a review journal, not as a brokerage ledger.</CardDescription></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-[1fr_2fr_auto] md:items-start">
          <Input aria-label="Portfolio name" placeholder="Long-term holdings" maxLength={120} value={name} onChange={(event) => setName(event.target.value)} />
          <Textarea aria-label="Portfolio description" rows={2} placeholder="Purpose and review discipline" maxLength={4000} value={description} onChange={(event) => setDescription(event.target.value)} />
          <Button type="button" disabled={!name.trim() || createMutation.isPending} onClick={() => createMutation.mutate()}>{createMutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Create</Button>
        </CardContent>
      </Card>

      {portfoliosQuery.isLoading ? <Card><CardContent className="flex items-center gap-2 p-8 text-sm text-muted-foreground"><LoaderCircle className="h-4 w-4 animate-spin" /> Loading manual portfolios…</CardContent></Card> : portfoliosQuery.isError || createMutation.isError ? <Card className="border-destructive/40"><CardContent className="flex items-center gap-2 p-8 text-sm text-destructive"><AlertCircle className="h-4 w-4" /> Unable to load or change portfolios. Existing records were preserved.</CardContent></Card> : (portfoliosQuery.data?.length ?? 0) === 0 ? <Card><CardContent className="p-10 text-center"><div className="font-medium">No manual portfolios</div><p className="mt-2 text-sm text-muted-foreground">Create one only when it helps you review decisions; ValuePilot will not infer positions from 13F filings.</p></CardContent></Card> : <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{portfoliosQuery.data?.map((portfolio) => <Card key={portfolio.id}><CardHeader><div className="flex items-start justify-between gap-3"><div><CardTitle>{portfolio.name}</CardTitle><CardDescription className="mt-2">{portfolio.description ?? 'No description'}</CardDescription></div><Badge variant={portfolio.status === 'active' ? 'success' : 'secondary'}>{portfolio.status}</Badge></div></CardHeader><CardContent><div className="mb-4 text-xs text-muted-foreground">Updated {new Date(portfolio.updated_at).toLocaleString()} · version {portfolio.version}</div><Button asChild className="w-full"><Link href={`/portfolios/${portfolio.id}`}>Open review journal <ArrowRight className="h-4 w-4" /></Link></Button></CardContent></Card>)}</div>}
    </div>
  );
}
