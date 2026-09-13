'use client';

import axios from 'axios';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertCircle,
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ExternalLink,
  FileText,
  History,
  Landmark,
  LoaderCircle,
  Plus,
  Save,
  ShieldAlert,
} from 'lucide-react';

import apiClient from '@/lib/api/client';
import { showAppToast } from '@/lib/appToast';
import { formatIsoCurrencyAmount } from '@/lib/currencyFormat';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { AnnualFinancialsTable } from '@/components/research/AnnualFinancialsTable';
import { FinancialEvidencePanel } from '@/components/research/FinancialEvidencePanel';
import { ResearchPath } from '@/components/research/ResearchPath';
import { emptyResearchNotes, hasResearchNotes, appendResearchNotes, type ResearchNotes } from '@/lib/researchPath';
import type { FinancialHistory, FinancialHistoryRow } from '@/lib/financialHistory';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/components/ui/use-toast';
import {
  currentPriceEvidenceLabel,
  type CanonicalCurrentPrice,
} from '@/lib/currentPrice';

type CaseState = 'queued' | 'researching' | 'monitoring' | 'closed' | 'voided';
type Decision = 'watch' | 'own' | 'pass';
type DecisionAction = 'draft' | 'decision' | 'review';
type ValuationMode = 'none' | 'range' | 'unavailable';

type Evidence = {
  source_type: string;
  source_id?: number;
  url?: string;
  label: string;
  source_date?: string;
  claim: string;
  destination_domain?: string;
  access_status?: 'available' | 'source_unavailable';
  financial_fact?: FinancialHistoryRow;
};

type Revision = {
  id: number;
  revision_number: number;
  thesis: string | null;
  variant_view: string | null;
  decision_reason: string | null;
  assumptions: Array<Record<string, unknown>>;
  risks: Array<Record<string, unknown>>;
  evidence: Evidence[];
  valuation_low: string | null;
  valuation_base: string | null;
  valuation_high: string | null;
  valuation_currency: string | null;
  valuation_unavailable_reason: string | null;
  valuation_as_of_date: string | null;
  case_state: CaseState;
  decision: Decision | null;
  next_review_on: string | null;
  recorded_identity: {
    stock_id: number;
    ticker: string;
    company_name: string;
    exchange: string;
    listing_exchange: string | null;
  };
  is_qualified_decision: boolean;
  is_redacted: boolean;
  created_at: string;
};

type Workspace = {
  as_of: string;
  case: {
    id: number;
    stock_id: number;
    ticker: string;
    company_name: string;
    state: CaseState;
    decision: Decision | null;
    next_review_on: string | null;
    head_revision_number: number;
  };
  current_identity: {
    ticker: string;
    company_name: string;
    exchange: string;
    listing_exchange: string | null;
    market_country: string | null;
    is_active: boolean;
  };
  origins: Array<{
    id: number;
    origin_type: string;
    origin_key: string;
    source_version: string;
    created_at: string;
  }>;
  revisions: Revision[];
  documents: Array<{
    id: number;
    file_name: string;
    source: string;
    report_date: string | null;
    parse_status: string;
    identity_needs_review: boolean;
  }>;
  financial_history: FinancialHistory;
  piotroski_f_score: Array<{
    fiscal_year: number | null;
    period_end_date: string | null;
    score: number | null;
    status: string | null;
    variant: string | null;
  }>;
  actual_conflicts: Array<{
    metric_key: string;
    period_end_date: string | null;
    current_value_numeric: number | null;
    previous_value_numeric: number | null;
  }>;
  current_price: CanonicalCurrentPrice;
  valuation: {
    user_intrinsic_value: number | null;
    user_intrinsic_value_status: string;
    display_state: string;
    user_intrinsic_value_as_of: string | null;
    user_intrinsic_value_currency: string | null;
    system_reference_value: number | null;
    system_reference_type: string | null;
    system_reference_as_of: string | null;
    system_reference_currency: string | null;
  };
  coverage: Array<{
    id: number;
    kind: string;
    state: string;
    reason_code: string | null;
    reason: string;
    source_type: string | null;
    source_ref_id: number | null;
    observed_at: string | null;
    freshness_policy_version: string;
    as_of: string | null;
    evaluated_at: string;
    next_action: string | null;
  }>;
  oracles_lens: {
    signal_id: number;
    report_quarter: string;
    consensus_score: string | null;
    distinctive_score: string | null;
    confidence: string | null;
    caution_flag_codes: string[];
  } | null;
  holders_13f: {
    status: string;
    as_of_quarter?: string | null;
    reason?: { message?: string };
    top_holders?: Array<{
      holding_id: number;
      manager: { id: number; display_name?: string | null; canonical_name?: string | null };
      portfolio_weight_pct: number | null;
      value_usd: number | null;
      holding_streak_quarters: number;
    }>;
    recent_changes?: Array<{
      manager: { id: number; display_name?: string | null; canonical_name?: string | null };
      change_status: string;
      value_delta_usd: number | null;
      share_delta: number | null;
      caveat_codes: string[];
    }>;
    data_caveats?: Array<{ code: string; message: string }>;
  };
};

type Draft = {
  researchNotes: ResearchNotes;
  thesis: string;
  variantView: string;
  decisionReason: string;
  assumptionsText: string;
  risksText: string;
  evidence: Evidence[];
  targetState: CaseState;
  decision: Decision | '';
  nextReviewOn: string;
  voidReason: string;
  valuationMode: ValuationMode;
  valuationLow: string;
  valuationBase: string;
  valuationHigh: string;
  valuationAsOf: string;
  valuationUnavailableReason: string;
};

const stateLabels: Record<CaseState, string> = {
  queued: 'Queued',
  researching: 'Researching',
  monitoring: 'Monitoring',
  closed: 'Closed / pass',
  voided: 'Voided',
};

const availableTransitions: Record<CaseState, CaseState[]> = {
  queued: ['queued', 'researching', 'closed', 'voided'],
  researching: ['researching', 'monitoring', 'closed', 'voided'],
  monitoring: ['monitoring', 'researching', 'closed', 'voided'],
  closed: ['closed'],
  voided: ['voided'],
};

function listToText(items: Array<Record<string, unknown>>): string {
  return items
    .map((item) => String(item.text ?? item.label ?? item.assumption ?? item.risk ?? ''))
    .filter(Boolean)
    .join('\n');
}

function textToList(value: string): Array<{ text: string }> {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((text) => ({ text }));
}

function initialDraft(workspace: Workspace): Draft {
  const head = workspace.revisions[0];
  const valuationMode: ValuationMode = head?.valuation_base
    ? 'range'
    : head?.valuation_unavailable_reason
      ? 'unavailable'
      : 'none';
  return {
    researchNotes: emptyResearchNotes(),
    thesis: head?.thesis ?? '',
    variantView: head?.variant_view ?? '',
    decisionReason: head?.decision_reason ?? '',
    assumptionsText: listToText(head?.assumptions ?? []),
    risksText: listToText(head?.risks ?? []),
    evidence: (head?.evidence ?? []).map((item) => {
      const snapshot = { ...item };
      delete snapshot.access_status;
      return snapshot;
    }),
    targetState: workspace.case.state,
    decision: workspace.case.decision ?? '',
    nextReviewOn: workspace.case.next_review_on ?? '',
    voidReason: '',
    valuationMode,
    valuationLow: head?.valuation_low ?? '',
    valuationBase: head?.valuation_base ?? '',
    valuationHigh: head?.valuation_high ?? '',
    valuationAsOf: head?.valuation_as_of_date ?? workspace.as_of,
    valuationUnavailableReason: head?.valuation_unavailable_reason ?? '',
  };
}

function money(
  value: number | string | null | undefined,
  currency: string | null | undefined,
): string {
  if (value === null || value === undefined || value === '') return '—';
  return formatIsoCurrencyAmount(value, currency, 2);
}

function label(value: string | null | undefined): string {
  return value ? value.replaceAll('_', ' ') : '—';
}

function sameIdentity(workspace: Workspace, revision: Revision): boolean {
  return (
    workspace.current_identity.ticker === revision.recorded_identity.ticker &&
    workspace.current_identity.company_name === revision.recorded_identity.company_name &&
    workspace.current_identity.exchange === revision.recorded_identity.exchange
  );
}

export default function ResearchCaseWorkspacePage() {
  const params = useParams();
  const rawId = Array.isArray(params?.id) ? params.id[0] : params?.id;
  const caseId = Number(rawId);
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [loadedHead, setLoadedHead] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [externalUrl, setExternalUrl] = useState('');
  const [externalLabel, setExternalLabel] = useState('');
  const [externalClaim, setExternalClaim] = useState('');
  const [showValuationContext, setShowValuationContext] = useState(false);
  const [showFullThesis, setShowFullThesis] = useState(false);
  const [financialSelection, setFinancialSelection] = useState<{ evaluatedAt: string; row: FinancialHistoryRow } | null>(null);

  const workspaceQuery = useQuery({
    queryKey: ['research-case-workspace', caseId],
    enabled: Number.isInteger(caseId) && caseId > 0,
    queryFn: async () => {
      const response = await apiClient.get(`/research/cases/${caseId}/workspace`);
      return response.data as Workspace;
    },
  });
  const workspace = workspaceQuery.data;
  const storageKey = workspace
    ? `vp-research-draft:${workspace.case.id}:${workspace.case.head_revision_number}`
    : null;

  useEffect(() => {
    if (!workspace || loadedHead === workspace.case.head_revision_number) return;
    const serverDraft = initialDraft(workspace);
    let restored = serverDraft;
    let didRestore = false;
    const key = `vp-research-draft:${workspace.case.id}:${workspace.case.head_revision_number}`;
    try {
      const saved = window.localStorage.getItem(key);
      if (saved) {
        restored = { ...serverDraft, ...(JSON.parse(saved) as Partial<Draft>) };
        didRestore = true;
      }
    } catch {
      window.localStorage.removeItem(key);
    }
    setDraft(restored);
    setDirty(didRestore);
    setConflict(false);
    setLoadedHead(workspace.case.head_revision_number);
  }, [loadedHead, workspace]);

  useEffect(() => {
    if (!dirty || !draft || !storageKey) return;
    window.localStorage.setItem(storageKey, JSON.stringify(draft));
  }, [dirty, draft, storageKey]);

  useEffect(() => {
    function warnOnLeave(event: BeforeUnloadEvent) {
      if (!dirty) return;
      event.preventDefault();
    }
    window.addEventListener('beforeunload', warnOnLeave);
    return () => window.removeEventListener('beforeunload', warnOnLeave);
  }, [dirty]);

  function updateDraft(patch: Partial<Draft>) {
    setDraft((current) => (current ? { ...current, ...patch } : current));
    setDirty(true);
    setConflict(false);
  }

  function addEvidence(item: Evidence) {
    if (!draft) return;
    const duplicate = draft.evidence.some(
      (evidence) =>
        evidence.source_type === item.source_type &&
        evidence.source_id === item.source_id &&
        evidence.url === item.url,
    );
    if (duplicate) return;
    updateDraft({ evidence: [...draft.evidence, item] });
  }

  const saveMutation = useMutation({
    mutationFn: async (decisionAction: DecisionAction) => {
      if (!workspace || !draft) throw new Error('Workspace is not ready.');
      if (hasResearchNotes(draft.researchNotes)) throw new Error('Append or clear your five-step notes before saving.');
      const targetDecision =
        draft.targetState === 'monitoring'
          ? draft.decision || 'watch'
          : draft.targetState === 'closed'
            ? 'pass'
            : null;
      const payload: Record<string, unknown> = {
        expected_head_revision_number: workspace.case.head_revision_number,
        target_state: draft.targetState,
        thesis: draft.thesis || null,
        variant_view: draft.variantView || null,
        decision_reason: draft.decisionReason || null,
        assumptions: textToList(draft.assumptionsText),
        risks: textToList(draft.risksText),
        evidence: draft.evidence,
        decision: targetDecision,
        next_review_on: draft.targetState === 'monitoring' ? draft.nextReviewOn || null : null,
        void_reason: draft.targetState === 'voided' ? draft.voidReason || null : null,
        correlation_id: crypto.randomUUID(),
        decision_action: decisionAction,
      };
      if (draft.valuationMode === 'range') {
        Object.assign(payload, {
          valuation_low: draft.valuationLow || null,
          valuation_base: draft.valuationBase || null,
          valuation_high: draft.valuationHigh || null,
          valuation_currency: 'USD',
          valuation_as_of_date: draft.valuationAsOf || null,
        });
      } else if (draft.valuationMode === 'unavailable') {
        Object.assign(payload, {
          valuation_unavailable_reason: draft.valuationUnavailableReason || null,
          valuation_as_of_date: draft.valuationAsOf || null,
        });
      }
      return apiClient.post(`/research/cases/${caseId}/revisions`, payload);
    },
    onSuccess: async () => {
      if (storageKey) window.localStorage.removeItem(storageKey);
      setDirty(false);
      setConflict(false);
      setLoadedHead(null);
      await queryClient.invalidateQueries({ queryKey: ['research-case-workspace', caseId] });
      await queryClient.invalidateQueries({ queryKey: ['research-cases'] });
      showAppToast(toast, {
        type: 'success',
        title: 'Research revision saved',
        description: 'The immutable decision snapshot and its evidence were recorded.',
      });
    },
    onError: (error) => {
      if (axios.isAxiosError(error) && error.response?.status === 409) {
        setConflict(true);
        return;
      }
      showAppToast(toast, {
        type: 'error',
        title: 'Revision was not saved',
        description: 'Review the state, valuation, evidence, and review-date requirements, then retry.',
      });
    },
  });

  const head = workspace?.revisions[0];
  const terminal = workspace?.case.state === 'closed' || workspace?.case.state === 'voided';
  const marginOfSafety = useMemo(() => {
    if (
      !workspace ||
      workspace.valuation.user_intrinsic_value === null ||
      workspace.valuation.display_state === 'under_review' ||
      workspace.current_price.status !== 'available' ||
      workspace.current_price.value === null ||
      workspace.current_price.currency !== workspace.valuation.user_intrinsic_value_currency
    ) {
      return null;
    }
    const fairValue = workspace.valuation.user_intrinsic_value;
    return (fairValue - Number(workspace.current_price.value)) / fairValue;
  }, [workspace]);

  if (workspaceQuery.isLoading) {
    return <Card><CardContent className="flex items-center gap-2 p-10 text-sm text-muted-foreground"><LoaderCircle className="h-4 w-4 animate-spin" /> Loading research workspace…</CardContent></Card>;
  }
  if (workspaceQuery.isError || !workspace || !draft) {
    return (
      <Card className="border-destructive/40">
        <CardContent className="space-y-4 p-8">
          <div className="flex items-center gap-2 font-medium text-destructive"><AlertCircle className="h-4 w-4" /> Unable to load this research case</div>
          <p className="text-sm text-muted-foreground">It may not exist, may belong to another account, or the service may be unavailable.</p>
          <Button type="button" variant="outline" onClick={() => void workspaceQuery.refetch()}>Retry</Button>
        </CardContent>
      </Card>
    );
  }

  const evidenceKey = (item: Evidence, index: number) => `${item.source_type}:${item.source_id ?? item.url ?? index}`;

  return (
    <div className="min-w-0 max-w-full space-y-6 pb-16">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">Research case #{workspace.case.id}</Badge>
            <Badge variant={workspace.case.state === 'monitoring' ? 'success' : 'secondary'}>{stateLabels[workspace.case.state]}</Badge>
            {!workspace.current_identity.is_active ? <Badge variant="danger">Inactive identity</Badge> : null}
          </div>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight">{workspace.case.ticker} · {workspace.case.company_name}</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Current identity: {workspace.current_identity.exchange} · {workspace.current_identity.market_country ?? 'country unknown'} · as of {workspace.as_of}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline"><Link href={`/stocks/${encodeURIComponent(workspace.case.ticker)}/summary`}>Stock summary</Link></Button>
          <Button asChild variant="outline"><Link href={`/stocks/${encodeURIComponent(workspace.case.ticker)}/dcf`}>DCF workspace</Link></Button>
          <Button
            type="button"
            variant="outline"
            disabled={terminal || !dirty || hasResearchNotes(draft.researchNotes) || saveMutation.isPending}
            onClick={() => saveMutation.mutate('draft')}
          >
            {saveMutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {saveMutation.isPending ? 'Saving…' : 'Save revision'}
          </Button>
          {draft.targetState === 'monitoring' || draft.targetState === 'closed' ? <Button type="button" disabled={terminal || !dirty || hasResearchNotes(draft.researchNotes) || saveMutation.isPending} onClick={() => saveMutation.mutate(workspace.case.state === 'monitoring' && draft.targetState === 'monitoring' ? 'review' : 'decision')}>{workspace.case.state === 'monitoring' && draft.targetState === 'monitoring' ? 'Record review decision' : 'Record decision'}</Button> : null}
        </div>
      </div>

      {dirty ? (
        <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> Unsaved draft is stored in this browser. Saving creates a new immutable revision.
        </div>
      ) : null}
      {conflict ? (
        <div className="space-y-3 rounded-lg border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-950">
          <div className="flex items-start gap-2"><ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" /> This case changed after your draft opened. Your local draft was kept; reload current evidence before deciding how to reconcile it.</div>
          <Button type="button" size="sm" variant="outline" onClick={() => void workspaceQuery.refetch()}>Reload current case</Button>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border p-3 text-xs text-muted-foreground">
        <span>Decision: {workspace.case.decision ? label(workspace.case.decision) : 'Undecided'} · Review: {workspace.case.next_review_on ?? 'not scheduled'}</span>
        <span>Price: {label(workspace.current_price.status)} · Your valuation: {label(workspace.valuation.user_intrinsic_value_status)}{workspace.valuation.display_state === 'under_review' ? ' · under review' : ''}</span>
        <Button asChild variant="link" size="sm"><a href="#research-path">Work through a research question</a></Button>
        <Button asChild variant="link" size="sm"><a href="#research-editor">Continue your thesis</a></Button>
      </div>
      {hasResearchNotes(draft.researchNotes) ? <p className="text-sm text-amber-800" role="status">Save is paused: append your five-step notes to the thesis draft or explicitly clear them first.</p> : null}

      <AnnualFinancialsTable
        key={workspace.financial_history.evaluated_at}
        history={workspace.financial_history}
        refreshing={workspaceQuery.isFetching}
        onRefresh={() => { setFinancialSelection(null); void workspaceQuery.refetch(); }}
        onSelect={row => setFinancialSelection({ evaluatedAt: workspace.financial_history.evaluated_at, row })}
      />
      {financialSelection?.evaluatedAt === workspace.financial_history.evaluated_at ? <FinancialEvidencePanel
        key={`${workspace.financial_history.evaluated_at}:${financialSelection.row.row_key}`}
        stockId={workspace.case.stock_id} row={financialSelection.row} readOnly={terminal}
        onClose={() => setFinancialSelection(null)} onAdd={addEvidence}
      /> : null}

      <Button type="button" variant="outline" aria-expanded={showValuationContext} onClick={() => setShowValuationContext(!showValuationContext)}>{showValuationContext ? 'Hide' : 'Show'} price, valuation &amp; decision context</Button>
      {showValuationContext ? <div className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader className="pb-2"><CardDescription>Canonical EOD price</CardDescription><CardTitle>{money(workspace.current_price.value, workspace.current_price.currency)}</CardTitle></CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            {currentPriceEvidenceLabel(workspace.current_price)}
            <div className="mt-1">Source authority: {workspace.current_price.source_authorization_state}</div>
            {workspace.current_price.reason_code ? <div className="mt-1 font-mono">{workspace.current_price.reason_code}</div> : null}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardDescription>User intrinsic value</CardDescription><CardTitle>{money(workspace.valuation.user_intrinsic_value, workspace.valuation.user_intrinsic_value_currency)}</CardTitle></CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            {workspace.valuation.display_state === 'under_review' ? 'Last user value — under review' : label(workspace.valuation.user_intrinsic_value_status)} · {workspace.valuation.user_intrinsic_value_as_of ?? 'no valuation date'}
            <div className="mt-1">Margin of safety: {marginOfSafety === null ? 'Unavailable until fresh USD price and user value exist' : `${(marginOfSafety * 100).toFixed(1)}%`}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardDescription>System valuation reference</CardDescription><CardTitle>{money(workspace.valuation.system_reference_value, workspace.valuation.system_reference_currency)}</CardTitle></CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            {workspace.valuation.system_reference_type ? label(workspace.valuation.system_reference_type) : 'No parsed reference'} · {workspace.valuation.system_reference_as_of ?? '—'}
            <div className="mt-1">Reference only; never treated as your intrinsic value.</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardDescription>Decision status</CardDescription><CardTitle>{workspace.case.decision ? label(workspace.case.decision) : 'Undecided'}</CardTitle></CardHeader>
          <CardContent className="text-xs text-muted-foreground">Next review: {workspace.case.next_review_on ?? 'not scheduled'} · head revision {workspace.case.head_revision_number}</CardContent>
        </Card>
      </div> : null}

      <div className="grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
        <div className="min-w-0 space-y-6">
          <ResearchPath notes={draft.researchNotes ?? emptyResearchNotes()} readOnly={terminal || saveMutation.isPending}
            onChange={researchNotes => updateDraft({ researchNotes })}
            onClear={() => updateDraft({ researchNotes: emptyResearchNotes() })}
            onAppend={() => {
              if (terminal || !hasResearchNotes(draft.researchNotes)) return;
              updateDraft({ thesis: appendResearchNotes(draft.thesis, draft.researchNotes), researchNotes: emptyResearchNotes() });
              setShowFullThesis(true);
            }} />
          <Card id="research-editor" className="min-w-0 scroll-mt-6">
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><BookOpen className="h-4 w-4" /> Independent thesis</CardTitle>
              <CardDescription>Write what must be true, why the market may disagree, and what would invalidate the case.</CardDescription>
              <Button type="button" variant="outline" size="sm" aria-expanded={showFullThesis} onClick={() => setShowFullThesis(!showFullThesis)}>{showFullThesis ? 'Hide' : 'Edit'} full thesis &amp; decision notes</Button>
            </CardHeader>
            {!showFullThesis ? <CardContent><p className="whitespace-pre-wrap break-words text-sm">{draft.thesis ? `${draft.thesis.slice(0, 240)}${draft.thesis.length > 240 ? '…' : ''}` : 'No thesis recorded yet. Use the five questions above, or open the editor to write freely.'}</p><p className="mt-2 text-xs text-muted-foreground">Preview only; your full text and existing notes are preserved.</p></CardContent> : null}
            {showFullThesis ? <>
            <CardContent className="space-y-5">
              <div className="space-y-2"><label htmlFor="thesis" className="text-sm font-medium">Thesis</label><Textarea id="thesis" rows={8} value={draft.thesis} disabled={terminal} onChange={(event) => updateDraft({ thesis: event.target.value })} placeholder="Business quality, durable economics, normalized earnings power, and why value exceeds price…" /></div>
              <div className="space-y-2"><label htmlFor="variant-view" className="text-sm font-medium">Disconfirming view</label><Textarea id="variant-view" rows={5} value={draft.variantView} disabled={terminal} onChange={(event) => updateDraft({ variantView: event.target.value })} placeholder="The strongest bear case and evidence that would falsify the thesis…" /></div>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2"><label htmlFor="assumptions" className="text-sm font-medium">Key assumptions · one per line</label><Textarea id="assumptions" rows={5} value={draft.assumptionsText} disabled={terminal} onChange={(event) => updateDraft({ assumptionsText: event.target.value })} /></div>
                <div className="space-y-2"><label htmlFor="risks" className="text-sm font-medium">Risks / kill criteria · one per line</label><Textarea id="risks" rows={5} value={draft.risksText} disabled={terminal} onChange={(event) => updateDraft({ risksText: event.target.value })} /></div>
              </div>
              <div className="space-y-2"><label htmlFor="decision-reason" className="text-sm font-medium">Decision rationale</label><Textarea id="decision-reason" rows={4} value={draft.decisionReason} disabled={terminal} onChange={(event) => updateDraft({ decisionReason: event.target.value })} /></div>
              <p className="text-xs text-muted-foreground">Not ready to judge is a valid research outcome. Lifecycle and valuation below are separate choices; saving a valuation range also updates your published user value under the existing rules.</p>
              <Button type="button" variant="outline" disabled={terminal || !dirty || hasResearchNotes(draft.researchNotes) || saveMutation.isPending} onClick={() => saveMutation.mutate('draft')}>Save research revision</Button>
            </CardContent>
            </> : null}
          </Card>

          <Card>
            <CardHeader><CardTitle>Evidence snapshot</CardTitle><CardDescription>Selected evidence is copied by stable reference into the next revision; current data remains visually separate.</CardDescription></CardHeader>
            <CardContent className="space-y-4">
              {draft.evidence.length === 0 ? <div className="rounded-lg border border-dashed p-5 text-sm text-muted-foreground">No evidence selected yet. Add current facts, reports, price, 13F context, or an external source.</div> : (
                <div className="space-y-2">
                  {draft.evidence.map((item, index) => (
                    <div key={evidenceKey(item, index)} className="flex items-start justify-between gap-3 rounded-lg border p-3 text-sm">
                      <div><div className="font-medium">{item.label}</div><div className="mt-1 text-xs text-muted-foreground">{label(item.source_type)} · {item.claim}</div></div>
                      {!terminal ? <Button type="button" size="sm" variant="outline" onClick={() => updateDraft({ evidence: draft.evidence.filter((_, evidenceIndex) => evidenceIndex !== index) })}>Remove</Button> : null}
                    </div>
                  ))}
                </div>
              )}
              {!terminal ? (
                <div className="grid gap-3 rounded-lg border bg-muted/30 p-4 md:grid-cols-3">
                  <Input aria-label="External evidence label" placeholder="Source label" value={externalLabel} onChange={(event) => setExternalLabel(event.target.value)} />
                  <Input aria-label="External evidence HTTPS URL" placeholder="https://…" value={externalUrl} onChange={(event) => setExternalUrl(event.target.value)} />
                  <Input aria-label="External evidence claim" placeholder="Claim supported" value={externalClaim} onChange={(event) => setExternalClaim(event.target.value)} />
                  <Button type="button" variant="outline" className="md:col-span-3" disabled={!externalLabel.trim() || !externalUrl.trim() || !externalClaim.trim()} onClick={() => {
                    addEvidence({ source_type: 'external_url', url: externalUrl.trim(), label: externalLabel.trim(), claim: externalClaim.trim() });
                    setExternalLabel(''); setExternalUrl(''); setExternalClaim('');
                  }}><Plus className="h-4 w-4" /> Add external HTTPS evidence</Button>
                </div>
              ) : null}
            </CardContent>
          </Card>

        </div>

        <div className="min-w-0 space-y-6">
          {!terminal ? (
            <Card>
              <CardHeader><CardTitle>Decision & valuation</CardTitle><CardDescription>Only an explicit save changes case state or publishes user intrinsic value.</CardDescription></CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2"><label className="text-sm font-medium">Target lifecycle state</label><Select value={draft.targetState} onValueChange={(value) => updateDraft({ targetState: value as CaseState, decision: value === 'monitoring' ? draft.decision || 'watch' : value === 'closed' ? 'pass' : '', nextReviewOn: value === 'monitoring' ? draft.nextReviewOn : '' })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{availableTransitions[workspace.case.state].map((state) => <SelectItem key={state} value={state}>{stateLabels[state]}</SelectItem>)}</SelectContent></Select></div>
                {draft.targetState === 'monitoring' ? <div className="space-y-2"><label className="text-sm font-medium">Decision</label><Select value={draft.decision || 'watch'} onValueChange={(value) => updateDraft({ decision: value as Decision })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="watch">Watch</SelectItem><SelectItem value="own">Own</SelectItem></SelectContent></Select></div> : null}
                {draft.targetState === 'monitoring' ? <div className="space-y-2"><label htmlFor="next-review" className="text-sm font-medium">Next review date</label><Input id="next-review" type="date" value={draft.nextReviewOn} onChange={(event) => updateDraft({ nextReviewOn: event.target.value })} /></div> : null}
                {draft.targetState === 'voided' ? <div className="space-y-2"><label htmlFor="void-reason" className="text-sm font-medium">Void reason</label><Textarea id="void-reason" value={draft.voidReason} onChange={(event) => updateDraft({ voidReason: event.target.value })} /></div> : null}
                <div className="space-y-2"><label className="text-sm font-medium">Valuation status</label><Select value={draft.valuationMode} onValueChange={(value) => updateDraft({ valuationMode: value as ValuationMode })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">Not assessed</SelectItem><SelectItem value="range">USD intrinsic value range</SelectItem><SelectItem value="unavailable">Cannot value responsibly</SelectItem></SelectContent></Select></div>
                {draft.valuationMode === 'range' ? <div className="grid grid-cols-3 gap-2"><Input aria-label="Valuation low" inputMode="decimal" placeholder="Low" value={draft.valuationLow} onChange={(event) => updateDraft({ valuationLow: event.target.value })} /><Input aria-label="Valuation base" inputMode="decimal" placeholder="Base" value={draft.valuationBase} onChange={(event) => updateDraft({ valuationBase: event.target.value })} /><Input aria-label="Valuation high" inputMode="decimal" placeholder="High" value={draft.valuationHigh} onChange={(event) => updateDraft({ valuationHigh: event.target.value })} /></div> : null}
                {draft.valuationMode === 'unavailable' ? <Textarea aria-label="Valuation unavailable reason" placeholder="Why a responsible valuation is not currently possible" value={draft.valuationUnavailableReason} onChange={(event) => updateDraft({ valuationUnavailableReason: event.target.value })} /> : null}
                {draft.valuationMode !== 'none' ? <div className="space-y-2"><label htmlFor="valuation-date" className="text-sm font-medium">Valuation as-of date</label><Input id="valuation-date" type="date" value={draft.valuationAsOf} onChange={(event) => updateDraft({ valuationAsOf: event.target.value })} /></div> : null}
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader><CardTitle>Other research inputs &amp; gaps</CardTitle><CardDescription>Price, uploaded-report and valuation readiness are separate from the SEC financials above. Available financial rows do not imply complete company coverage.</CardDescription></CardHeader>
            <CardContent className="space-y-2">
              {workspace.coverage.length === 0 ? <div className="text-sm text-muted-foreground">Coverage has not been evaluated for this case.</div> : workspace.coverage.map((item) => (
                <div key={item.id} className="rounded-lg border p-3 text-sm"><div className="flex items-center justify-between gap-2"><span className="font-medium">{label(item.kind)}</span><Badge variant={item.state === 'ready' ? 'success' : ['blocked', 'failed', 'inaccessible', 'unsupported'].includes(item.state) ? 'danger' : 'warning'}>{label(item.state)}</Badge></div><p className="mt-2 text-xs text-muted-foreground">{item.reason}</p><div className="mt-2 text-xs text-muted-foreground">Source: {item.source_type ? `${label(item.source_type)}${item.source_ref_id ? ` #${item.source_ref_id}` : ''}` : 'none yet'} · As of {item.as_of ?? item.observed_at ?? 'not observed'}</div><div className="mt-1 text-xs text-muted-foreground">Freshness policy: <span className="font-mono">{item.freshness_policy_version}</span> · Evaluated {item.evaluated_at}</div>{item.reason_code ? <div className="mt-1 text-xs font-mono text-muted-foreground">{item.reason_code}</div> : null}{item.next_action ? <div className="mt-1 text-xs">Next: {label(item.next_action)}</div> : null}</div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Piotroski quality history</CardTitle><CardDescription>Calculated from this account&apos;s current normalized facts; partial/proxy variants remain labeled.</CardDescription></CardHeader>
            <CardContent className="space-y-2">
              {workspace.piotroski_f_score.length === 0 ? <div className="text-sm text-muted-foreground">No Piotroski score is available.</div> : workspace.piotroski_f_score.map((row) => <div key={`${row.fiscal_year}-${row.period_end_date}`} className="flex items-center justify-between rounded-lg border p-3 text-sm"><span>{row.fiscal_year ?? row.period_end_date ?? 'Unknown period'} · {row.variant ? label(row.variant) : 'variant unavailable'}</span><Badge variant={row.score !== null && row.score >= 7 ? 'success' : 'secondary'}>{row.score ?? '—'} / 9</Badge></div>)}
              {workspace.actual_conflicts.length > 0 ? <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950">{workspace.actual_conflicts.length} source conflict(s) need review. Current facts follow the latest-report rule; open original evidence before deciding.</div> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><FileText className="h-4 w-4" /> Your uploaded reports</CardTitle><CardDescription>Account-owned PDF reports, including Value Line. Retained SEC statement evidence opens from financial values above.</CardDescription></CardHeader>
            <CardContent className="space-y-2">
              {workspace.documents.length === 0 ? <div className="text-sm text-muted-foreground">No uploaded PDF report is linked to this stock for your account. This does not mean SEC evidence is unavailable.</div> : workspace.documents.map((document) => (
                <div key={document.id} className="rounded-lg border p-3 text-sm"><div className="font-medium">{document.file_name}</div><div className="mt-1 text-xs text-muted-foreground">{document.report_date ?? 'undated'} · {label(document.parse_status)}{document.identity_needs_review ? ' · identity review needed' : ''}</div><Button type="button" size="sm" variant="outline" className="mt-2" disabled={terminal} onClick={() => addEvidence({ source_type: 'pdf_document', source_id: document.id, source_date: document.report_date ?? undefined, label: document.file_name, claim: `Authorized report reviewed for ${workspace.case.ticker}.` })}>Add as evidence</Button></div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Landmark className="h-4 w-4" /> 13F context</CardTitle><CardDescription>13F is delayed up to 45 days after quarter end and is not proof of a current holding, cost basis, or complete portfolio.</CardDescription></CardHeader>
            <CardContent className="space-y-3">
              {workspace.oracles_lens ? <div className="rounded-lg border p-3 text-sm"><div className="font-medium">Oracle&apos;s Lens · {workspace.oracles_lens.report_quarter}</div><div className="mt-1 text-xs text-muted-foreground">Consensus {workspace.oracles_lens.consensus_score ?? '—'} · distinctive {workspace.oracles_lens.distinctive_score ?? '—'} · confidence {workspace.oracles_lens.confidence ?? '—'}</div><Button type="button" size="sm" variant="outline" className="mt-2" disabled={terminal} onClick={() => addEvidence({ source_type: 'oracles_lens_signal', source_id: workspace.oracles_lens!.signal_id, label: `Oracle's Lens ${workspace.oracles_lens!.report_quarter}`, claim: 'Reviewed the model signal and its disclosed limitations.' })}>Add signal evidence</Button></div> : <div className="text-sm text-muted-foreground">No current Oracle&apos;s Lens signal.</div>}
              {workspace.holders_13f.status === 'unavailable' ? <div className="text-sm text-muted-foreground">{workspace.holders_13f.reason?.message ?? 'No active 13F holder context.'}</div> : workspace.holders_13f.top_holders?.slice(0, 8).map((holder) => <div key={holder.holding_id} className="flex items-center justify-between gap-3 rounded-lg border p-3 text-sm"><div><Link href={`/13f/managers/${holder.manager.id}`} className="font-medium text-primary hover:underline">{holder.manager.display_name ?? holder.manager.canonical_name ?? `Manager #${holder.manager.id}`}</Link><div className="text-xs text-muted-foreground">Reported weight {holder.portfolio_weight_pct ?? '—'}% · {money(holder.value_usd, 'USD')} · holding streak {holder.holding_streak_quarters} quarter(s)</div></div><Button type="button" size="sm" variant="outline" disabled={terminal} onClick={() => addEvidence({ source_type: 'holding_13f', source_id: holder.holding_id, source_date: workspace.holders_13f.as_of_quarter ?? undefined, label: `${holder.manager.display_name ?? holder.manager.canonical_name ?? 'Manager'} 13F holding`, claim: `Reported position for ${workspace.holders_13f.as_of_quarter ?? 'the current active quarter'}.` })}>Add</Button></div>)}
              {(workspace.holders_13f.recent_changes ?? []).length > 0 ? <div className="space-y-2"><div className="text-xs font-medium uppercase text-muted-foreground">Latest reported changes</div>{workspace.holders_13f.recent_changes!.slice(0, 8).map((change, index) => <div key={`${change.manager.id}-${change.change_status}-${index}`} className="rounded-lg border p-3 text-xs"><span className="font-medium">{change.manager.display_name ?? change.manager.canonical_name ?? `Manager #${change.manager.id}`}</span> · {label(change.change_status)} · value change {money(change.value_delta_usd, 'USD')}</div>)}</div> : null}
              {(workspace.holders_13f.data_caveats ?? []).map((caveat) => <div key={caveat.code} className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950">{caveat.message}</div>)}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Discovery origins</CardTitle></CardHeader>
            <CardContent className="space-y-2">{workspace.origins.map((origin) => <div key={origin.id} className="rounded-lg border p-3 text-xs"><div className="font-medium">{label(origin.origin_type)}</div><div className="mt-1 text-muted-foreground">{origin.origin_key} · {origin.source_version}</div></div>)}</CardContent>
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><History className="h-4 w-4" /> Revision history</CardTitle><CardDescription>Immutable snapshots preserve what was known, believed, valued, and decided at each point in time.</CardDescription></CardHeader>
        <CardContent className="space-y-4">
          {workspace.revisions.length === 0 ? <div className="py-8 text-center text-sm text-muted-foreground">No saved revisions yet. The current content is an unsaved first draft.</div> : workspace.revisions.map((revision) => (
            <div key={revision.id} className="rounded-xl border p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><div className="font-semibold">Revision {revision.revision_number} · {stateLabels[revision.case_state]}</div><div className="mt-1 text-xs text-muted-foreground">{new Date(revision.created_at).toLocaleString()} · recorded as {revision.recorded_identity.ticker} / {revision.recorded_identity.company_name}</div></div>
                <div className="flex gap-2">{revision.is_qualified_decision ? <Badge variant="success"><CheckCircle2 className="h-3 w-3" /> Qualified decision</Badge> : <Badge variant="secondary">Draft record</Badge>}{revision.is_redacted ? <Badge variant="danger">Redacted</Badge> : null}{!sameIdentity(workspace, revision) ? <Badge variant="warning">Identity changed</Badge> : null}</div>
              </div>
              <div className="mt-4 grid gap-4 md:grid-cols-3"><div><div className="text-xs font-medium uppercase text-muted-foreground">Thesis</div><p className="mt-1 whitespace-pre-wrap text-sm">{revision.thesis ?? 'Not recorded'}</p></div><div><div className="text-xs font-medium uppercase text-muted-foreground">Disconfirming view</div><p className="mt-1 whitespace-pre-wrap text-sm">{revision.variant_view ?? 'Not recorded'}</p></div><div><div className="text-xs font-medium uppercase text-muted-foreground">Valuation / decision</div><p className="mt-1 text-sm">{revision.valuation_base ? `${money(revision.valuation_low, revision.valuation_currency)} / ${money(revision.valuation_base, revision.valuation_currency)} / ${money(revision.valuation_high, revision.valuation_currency)}` : revision.valuation_unavailable_reason ?? 'Not assessed'}<br />{revision.decision ? label(revision.decision) : 'No decision'} · review {revision.next_review_on ?? '—'}</p></div></div>
              {revision.evidence.length > 0 ? <div className="mt-4"><div className="text-xs font-medium uppercase text-muted-foreground">Recorded evidence</div><div className="mt-2 flex flex-wrap gap-2">{revision.evidence.map((item, index) => item.access_status === 'source_unavailable' ? <Badge key={evidenceKey(item, index)} variant="danger" title="The recorded source is no longer authorized or available."><AlertCircle className="h-3 w-3" /> {item.label} · source_unavailable</Badge> : item.financial_fact ? <Button key={evidenceKey(item, index)} type="button" size="sm" variant="outline" onClick={() => setFinancialSelection({ evaluatedAt: workspace.financial_history.evaluated_at, row: item.financial_fact! })}>Review original evidence · {item.label}</Button> : item.url ? <a key={evidenceKey(item, index)} href={item.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium text-primary hover:underline">{item.label} · {item.destination_domain ?? new URL(item.url).hostname}<ExternalLink className="h-3 w-3" /></a> : <Badge key={evidenceKey(item, index)} variant="outline">{item.label}</Badge>)}</div></div> : null}
            </div>
          ))}
        </CardContent>
      </Card>

      {head && !sameIdentity(workspace, head) ? <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950"><AlertTriangle className="mt-0.5 h-4 w-4" /> The current stock identity differs from the latest recorded identity. Review the mapping before relying on current evidence.</div> : null}
    </div>
  );
}
