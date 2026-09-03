'use client';

import axios from 'axios';
import Link from 'next/link';
import { useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, BookOpen, CalendarCheck, History, LoaderCircle, Plus, Scale, XCircle } from 'lucide-react';

import apiClient from '@/lib/api/client';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  type CanonicalCurrentPrice,
  currentPriceEvidenceLabel,
  currentPriceReasonLabel,
} from '@/lib/currentPrice';

type Position = {
  id: number;
  stock_id: number;
  ticker: string;
  company_name: string;
  state: 'open' | 'closed';
  quantity: string;
  average_unit_cost: string | null;
  currency: string;
  research_case_id: number | null;
  research_revision_id: number | null;
  opened_on: string;
  closed_on: string | null;
  last_reviewed_on: string | null;
  next_review_on: string | null;
  review_status: string;
  version: number;
  identity_state: string;
  current_price: CanonicalCurrentPrice;
  market_value: string | null;
  unrealized_return: string | null;
  valuation_status: string;
};

type Workspace = {
  as_of: string;
  portfolio: { id: number; name: string; description: string | null; status: string; version: number };
  positions: Position[];
  totals_by_currency: Record<string, string>;
  cross_currency_total: null;
  review_calendar: Array<{
    position_id: number;
    ticker: string;
    research_case_id: number | null;
    review_status: string;
    next_review_on: string | null;
    last_reviewed_on: string | null;
  }>;
  journal_events: Array<{
    id: number;
    position_id: number;
    sequence_number: number;
    event_type: string;
    effective_on: string;
    prior_quantity: string | null;
    new_quantity: string | null;
    currency: string;
    reason: string | null;
    research_case_id: number | null;
    research_revision_id: number | null;
    recorded_identity: { ticker: string; company_name: string; exchange: string };
  }>;
  linked_revisions: Record<string, {
    id: number;
    case_id: number;
    revision_number: number;
    thesis: string | null;
    variant_view: string | null;
    decision: string | null;
    valuation_base: string | null;
    valuation_as_of_date: string | null;
  }>;
  research_comparisons: Record<string, {
    recorded_revision: {
      revision_number: number;
      thesis: string | null;
      variant_view: string | null;
      decision: string | null;
      valuation_base: string | null;
    } | null;
    current_revision: {
      revision_number: number;
      thesis: string | null;
      variant_view: string | null;
      decision: string | null;
      valuation_base: string | null;
    } | null;
    current_case: {
      state: string;
      decision: string | null;
      next_review_on: string | null;
      head_revision_number: number;
    };
  }>;
  disclaimer: string;
};

function money(value: string | number | null, currency = 'USD') {
  if (value === null) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 2 }).format(Number(value));
}

function priceMoney(value: number | null, currency: string | null) {
  if (value === null) return '—';
  if (currency === null) return `${Number(value).toLocaleString('en-US')} (currency unknown)`;
  return money(value, currency);
}

function label(value: string) {
  return value.replaceAll('_', ' ');
}

export default function ManualPortfolioWorkspacePage() {
  const params = useParams();
  const rawId = Array.isArray(params?.id) ? params.id[0] : params?.id;
  const portfolioId = Number(rawId);
  const queryClient = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);
  const [ticker, setTicker] = useState('');
  const [quantity, setQuantity] = useState('');
  const [averageCost, setAverageCost] = useState('');
  const [currency, setCurrency] = useState('USD');
  const [openedOn, setOpenedOn] = useState(today);
  const [researchCaseId, setResearchCaseId] = useState('');
  const [researchRevisionId, setResearchRevisionId] = useState('');
  const [reason, setReason] = useState('');
  const [editQuantity, setEditQuantity] = useState<Record<number, string>>({});
  const [editCost, setEditCost] = useState<Record<number, string>>({});
  const [actionReason, setActionReason] = useState<Record<number, string>>({});
  const [closeConfirmed, setCloseConfirmed] = useState<Record<number, boolean>>({});

  const workspaceQuery = useQuery({
    queryKey: ['manual-portfolio', portfolioId],
    enabled: Number.isInteger(portfolioId) && portfolioId > 0,
    queryFn: async () => {
      const response = await apiClient.get(`/portfolios/${portfolioId}`);
      return response.data as Workspace;
    },
  });
  const workspace = workspaceQuery.data;

  const createMutation = useMutation({
    mutationFn: async () => {
      const stockResponse = await apiClient.get(`/stocks/by_ticker/${encodeURIComponent(ticker.trim())}`);
      const stockId = stockResponse.data?.id;
      if (typeof stockId !== 'number') throw new Error('Ticker did not resolve to a stock.');
      return apiClient.post(`/portfolios/${portfolioId}/positions`, {
        stock_id: stockId,
        quantity,
        average_unit_cost: averageCost || null,
        currency,
        opened_on: openedOn,
        research_case_id: researchCaseId ? Number(researchCaseId) : null,
        research_revision_id: researchRevisionId ? Number(researchRevisionId) : null,
        reason: reason || null,
      });
    },
    onSuccess: async () => {
      setTicker(''); setQuantity(''); setAverageCost(''); setResearchCaseId(''); setResearchRevisionId(''); setReason('');
      await queryClient.invalidateQueries({ queryKey: ['manual-portfolio', portfolioId] });
    },
  });
  const positionMutation = useMutation({
    mutationFn: async ({ position, operation }: { position: Position; operation: 'resize' | 'review' | 'close' }) => {
      const common = {
        expected_version: position.version,
        research_case_id: position.research_case_id,
        research_revision_id: position.research_revision_id,
        reason: actionReason[position.id] || null,
      };
      if (operation === 'resize') {
        await apiClient.post(`/portfolios/positions/${position.id}/resize`, { ...common, quantity: editQuantity[position.id] || position.quantity, average_unit_cost: editCost[position.id] || position.average_unit_cost });
        return;
      }
      if (operation === 'review') {
        await apiClient.post(`/portfolios/positions/${position.id}/review`, { ...common, reviewed_on: today, reason: actionReason[position.id] || 'Reviewed current evidence; no journal detail supplied.' });
        return;
      }
      await apiClient.post(`/portfolios/positions/${position.id}/close`, { ...common, closed_on: today });
    },
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['manual-portfolio', portfolioId] }),
  });

  const errors = workspaceQuery.isError || createMutation.isError || positionMutation.isError;
  const conflict = axios.isAxiosError(positionMutation.error) && positionMutation.error.response?.status === 409;
  const openPositions = useMemo(() => workspace?.positions.filter((position) => position.state === 'open') ?? [], [workspace]);

  if (workspaceQuery.isLoading) return <Card><CardContent className="flex items-center gap-2 p-10 text-sm text-muted-foreground"><LoaderCircle className="h-4 w-4 animate-spin" /> Loading manual portfolio…</CardContent></Card>;
  if (!workspace) return <Card className="border-destructive/40"><CardContent className="p-8 text-sm text-destructive">Portfolio not found or unavailable to this account.</CardContent></Card>;

  return (
    <div className="space-y-6">
      <div><Badge variant="outline">Manual · version {workspace.portfolio.version}</Badge><h1 className="mt-3 text-3xl font-semibold tracking-tight">{workspace.portfolio.name}</h1><p className="mt-2 text-sm text-muted-foreground">{workspace.portfolio.description ?? workspace.disclaimer}</p></div>
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">Manual positions may be stale and are not an execution record. ValuePilot does not connect to a broker, calculate tax lots, or infer your position from any 13F filing.</div>
      {errors ? <div className="flex gap-2 rounded-lg border border-rose-300 bg-rose-50 p-4 text-sm text-rose-950"><AlertCircle className="mt-0.5 h-4 w-4" /> {conflict ? 'This position changed after you opened it. Reload before retrying; no partial event was saved.' : 'The requested operation failed. Existing positions and journal events were preserved.'}</div> : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card><CardHeader className="pb-2"><CardDescription>Open positions</CardDescription><CardTitle>{openPositions.length}</CardTitle></CardHeader></Card>
        {Object.entries(workspace.totals_by_currency).map(([code, value]) => <Card key={code}><CardHeader className="pb-2"><CardDescription>Calculable {code} value</CardDescription><CardTitle>{money(value, code)}</CardTitle></CardHeader></Card>)}
        <Card><CardHeader className="pb-2"><CardDescription>Cross-currency total</CardDescription><CardTitle>Not calculated</CardTitle></CardHeader><CardContent className="text-xs text-muted-foreground">No FX conversion or false aggregation.</CardContent></Card>
      </div>

      <Card><CardHeader><CardTitle className="flex items-center gap-2"><CalendarCheck className="h-4 w-4" /> Review calendar</CardTitle><CardDescription>Open manual positions ordered by overdue review obligation, not by market noise.</CardDescription></CardHeader><CardContent className="space-y-2">{workspace.review_calendar.length === 0 ? <div className="text-sm text-muted-foreground">No open positions require review.</div> : workspace.review_calendar.map((item) => <div key={item.position_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 text-sm"><div><span className="font-medium">{item.ticker}</span>{item.research_case_id ? <Link href={`/research/cases/${item.research_case_id}`} className="ml-2 text-xs text-primary hover:underline">Open case</Link> : null}<div className="mt-1 text-xs text-muted-foreground">Next review {item.next_review_on ?? 'not scheduled'} · last recorded review {item.last_reviewed_on ?? 'never'}</div></div><Badge variant={item.review_status === 'overdue' ? 'danger' : item.review_status === 'due_today' || item.review_status === 'under_review' ? 'warning' : 'secondary'}>{label(item.review_status)}</Badge></div>)}</CardContent></Card>

      {workspace.portfolio.status === 'active' ? <Card><CardHeader><CardTitle>Add a manual position</CardTitle><CardDescription>Long-only quantity and optional average unit cost. Link the exact Research case/revision that supported the decision.</CardDescription></CardHeader><CardContent className="grid gap-3 md:grid-cols-3"><Input aria-label="Position ticker" placeholder="Ticker" value={ticker} onChange={(event) => setTicker(event.target.value.toUpperCase())} /><Input aria-label="Long quantity" inputMode="decimal" placeholder="Quantity (> 0)" value={quantity} onChange={(event) => setQuantity(event.target.value)} /><Input aria-label="Average unit cost" inputMode="decimal" placeholder="Average unit cost (optional)" value={averageCost} onChange={(event) => setAverageCost(event.target.value)} /><Input aria-label="Position currency" maxLength={3} value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} /><Input aria-label="Position opened date" type="date" value={openedOn} onChange={(event) => setOpenedOn(event.target.value)} /><Input aria-label="Research case ID" inputMode="numeric" placeholder="Research case ID (optional)" value={researchCaseId} onChange={(event) => setResearchCaseId(event.target.value)} /><Input aria-label="Research revision ID" inputMode="numeric" placeholder="Research revision ID (optional)" value={researchRevisionId} onChange={(event) => setResearchRevisionId(event.target.value)} /><Textarea aria-label="Opening journal reason" className="md:col-span-2" placeholder="Why this position belongs here" value={reason} onChange={(event) => setReason(event.target.value)} /><Button type="button" className="md:col-span-3" disabled={!ticker || !quantity || currency.length !== 3 || createMutation.isPending} onClick={() => createMutation.mutate()}><Plus className="h-4 w-4" /> Add manual position</Button></CardContent></Card> : null}

      <div className="space-y-4">
        <h2 className="text-xl font-semibold">Positions</h2>
        {workspace.positions.length === 0 ? <Card><CardContent className="p-10 text-center text-sm text-muted-foreground">No manual positions. Nothing is inferred from Watchlists, managers, or filings.</CardContent></Card> : workspace.positions.map((position) => {
          const revision = position.research_revision_id ? workspace.linked_revisions[String(position.research_revision_id)] : null;
          const comparison = workspace.research_comparisons[String(position.id)];
          const unavailable = position.current_price.status !== 'available' || ['currency_mismatch', 'stock_inactive'].includes(position.valuation_status);
          const displayedPrice = position.current_price.status === 'available' ? position.current_price.value : position.current_price.observation_value;
          const priceReason = currentPriceReasonLabel(position.current_price);
          return <Card key={position.id} className={position.state === 'closed' ? 'opacity-75' : undefined}><CardHeader><div className="flex flex-wrap items-start justify-between gap-3"><div><CardTitle>{position.ticker} · {position.company_name}</CardTitle><CardDescription className="mt-2">Manual {position.state} position · {position.quantity} shares · {position.currency} · version {position.version}</CardDescription></div><div className="flex gap-2"><Badge variant={position.state === 'open' ? 'success' : 'secondary'}>{position.state}</Badge><Badge variant={position.review_status === 'overdue' ? 'danger' : position.review_status === 'under_review' ? 'warning' : 'outline'}>{label(position.review_status)}</Badge><Badge variant={unavailable ? 'warning' : 'outline'}>{label(position.valuation_status)}</Badge></div></div></CardHeader><CardContent className="space-y-4"><div className="grid gap-3 sm:grid-cols-4"><div><div className="text-xs text-muted-foreground">Average unit cost</div><div className="font-medium">{money(position.average_unit_cost, position.currency)}</div></div><div><div className="text-xs text-muted-foreground">Canonical price</div><div className="font-medium">{priceMoney(displayedPrice, position.current_price.currency)}</div><div className="text-xs text-muted-foreground">{currentPriceEvidenceLabel(position.current_price)}</div><div className="text-xs text-muted-foreground">Status: {position.current_price.status} · source authorization: {position.current_price.source_authorization_state}</div><div className="text-xs text-muted-foreground">Expected session {position.current_price.expected_session_date ?? 'unresolved'} · {position.current_price.as_of_mode} as of {position.current_price.as_of_date}</div><div className="text-xs text-muted-foreground">Policies: {position.current_price.freshness_policy_version} · {position.current_price.calendar_policy_version} · {position.current_price.source_policy_version}</div>{priceReason ? <div className="text-xs text-amber-800">{position.current_price.reason_code}: {priceReason}</div> : null}</div><div><div className="text-xs text-muted-foreground">Market value</div><div className="font-medium">{position.market_value ? money(position.market_value, position.currency) : label(position.valuation_status)}</div></div><div><div className="text-xs text-muted-foreground">Unrealized return</div><div className="font-medium">{position.unrealized_return ? `${(Number(position.unrealized_return) * 100).toFixed(1)}%` : 'Not calculated'}</div></div></div>{position.valuation_status === 'currency_mismatch' ? <p className="text-sm text-amber-800">currency_mismatch: the canonical price and manual cost currencies differ; ValuePilot performs no FX conversion.</p> : null}{position.research_case_id ? <div className="rounded-lg border bg-muted/20 p-3 text-sm"><Link href={`/research/cases/${position.research_case_id}`} className="font-medium text-primary hover:underline"><BookOpen className="mr-1 inline h-4 w-4" /> Research case #{position.research_case_id}{revision ? ` · revision ${revision.revision_number}` : ''}</Link>{revision ? <div className="mt-2 grid gap-2 md:grid-cols-2"><p><span className="text-xs uppercase text-muted-foreground">Recorded thesis</span><br />{revision.thesis ?? 'Not recorded'}</p><p><span className="text-xs uppercase text-muted-foreground">Recorded value / decision</span><br />{revision.valuation_base ? money(revision.valuation_base) : 'Not valued'} · {revision.decision ?? 'undecided'}</p></div> : null}{comparison?.current_revision ? <div className="mt-3 border-t pt-3"><div className="text-xs font-medium uppercase text-muted-foreground">Current evidence comparison · revision {comparison.current_revision.revision_number}</div><p className="mt-1">{comparison.current_revision.thesis ?? 'Current thesis not recorded'}</p><p className="mt-1 text-xs text-muted-foreground">Current value {comparison.current_revision.valuation_base ? money(comparison.current_revision.valuation_base) : 'not valued'} · {comparison.current_case.decision ?? comparison.current_case.state}. Recorded history above is unchanged.</p></div> : null}</div> : null}{position.state === 'open' ? <div className="space-y-3 rounded-lg border p-4"><div className="grid gap-2 md:grid-cols-3"><Input aria-label={`${position.ticker} resized quantity`} placeholder={position.quantity} value={editQuantity[position.id] ?? ''} onChange={(event) => setEditQuantity((current) => ({ ...current, [position.id]: event.target.value }))} /><Input aria-label={`${position.ticker} revised average cost`} placeholder={position.average_unit_cost ?? 'Average cost'} value={editCost[position.id] ?? ''} onChange={(event) => setEditCost((current) => ({ ...current, [position.id]: event.target.value }))} /><Input aria-label={`${position.ticker} journal reason`} placeholder="Reason / review note" value={actionReason[position.id] ?? ''} onChange={(event) => setActionReason((current) => ({ ...current, [position.id]: event.target.value }))} /></div><div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" onClick={() => positionMutation.mutate({ position, operation: 'resize' })}><Scale className="h-3.5 w-3.5" /> Resize</Button><Button type="button" size="sm" variant="outline" onClick={() => positionMutation.mutate({ position, operation: 'review' })}><CalendarCheck className="h-3.5 w-3.5" /> Record review</Button><label className="flex items-center gap-2 text-xs"><Checkbox checked={Boolean(closeConfirmed[position.id])} onCheckedChange={(checked) => setCloseConfirmed((current) => ({ ...current, [position.id]: checked === true }))} /> Confirm this creates a manual close journal entry, not an execution.</label><Button type="button" size="sm" variant="destructive" disabled={!closeConfirmed[position.id]} onClick={() => positionMutation.mutate({ position, operation: 'close' })}><XCircle className="h-3.5 w-3.5" /> Close manual position</Button></div></div> : null}</CardContent></Card>;
        })}
      </div>

      <Card><CardHeader><CardTitle className="flex items-center gap-2"><History className="h-4 w-4" /> Decision journal</CardTitle><CardDescription>Append-only open, resize, review, and close records preserve the identity and research link used at the time.</CardDescription></CardHeader><CardContent className="space-y-3">{workspace.journal_events.length === 0 ? <div className="text-sm text-muted-foreground">No journal events.</div> : workspace.journal_events.map((event) => <div key={event.id} className="rounded-lg border p-3 text-sm"><div className="flex flex-wrap items-center justify-between gap-2"><div className="font-medium">{event.recorded_identity.ticker} · {label(event.event_type)} · sequence {event.sequence_number}</div><Badge variant="outline">{event.effective_on}</Badge></div><div className="mt-1 text-xs text-muted-foreground">{event.prior_quantity ?? '—'} → {event.new_quantity ?? '—'} {event.currency} · {event.recorded_identity.company_name} / {event.recorded_identity.exchange}</div><p className="mt-2">{event.reason ?? 'No reason recorded.'}</p>{event.research_case_id ? <Link href={`/research/cases/${event.research_case_id}`} className="mt-2 inline-block text-xs font-medium text-primary hover:underline">Research case #{event.research_case_id}{event.research_revision_id ? ` / revision ID ${event.research_revision_id}` : ''}</Link> : null}</div>)}</CardContent></Card>
    </div>
  );
}
