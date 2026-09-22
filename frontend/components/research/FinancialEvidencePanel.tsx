'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { ExternalLink, LoaderCircle, Plus, X } from 'lucide-react';
import apiClient from '@/lib/api/client';
import { CORE_METRICS, formatExactDecimal, readFinancialEvidence, inputEvidenceFilings, type FinancialHistoryRow } from '@/lib/financialHistory';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

type Statement = {
  accession: string; form: string; sec_url: string | null;
  raw_fact_id: number; statement_authority_id: number; raw_value: string; display_value: string | null;
  scale: number | null; sign: string | null; decimals: string | null; unit_measure: string | null;
  display_multiplier: string | null; preferred_label_role: string | null; report_name: string;
  row_label: string; column_header: string; header_date: string; context_id: string; concept: string;
  locator: Record<string, number>;
};
type EvidenceInput = {
  ordinal: number; arithmetic_sign: number; statement?: Statement;
  publication_id?: number; metric_fact_id?: number; value_numeric_exact?: string | null;
  inputs?: EvidenceInput[]; accession?: string; form?: string;
};
type SecEvidence = {
  evidence_state: string; evidence_reason_code: string | null; currentness?: string;
  metric_fact_id: number; publication_id: number; value_numeric_exact: string | null;
  inputs: EvidenceInput[]; filings: Array<{ accession: string; form: string; sec_url: string | null }>;
};
export type FinancialReference = {
  source_type: string; source_id: number; label: string; claim: string; source_date?: string;
};

function InputEvidence({ inputs, auditExpanded }: { inputs: EvidenceInput[]; auditExpanded: boolean }) {
  return <div className="min-w-0 space-y-3">{inputs.map(input => <div key={input.ordinal} className="min-w-0 rounded border p-3 text-xs [overflow-wrap:anywhere]">
    <div className="font-medium">Source input {input.ordinal} · {input.arithmetic_sign > 0 ? 'Add (+)' : 'Subtract (−)'}{input.accession ? ` · ${input.form} ${input.accession}` : ''}</div>
    {input.statement ? <div className="mt-2 space-y-2">
      <div>{input.statement.form} · {input.statement.accession}</div>
      <div className="text-sm font-medium">{input.statement.report_name}</div>
      <div><span className="font-medium">Row:</span> {input.statement.row_label}</div>
      <div><span className="font-medium">Column:</span> {input.statement.column_header} · {input.statement.header_date}</div>
      <div className="rounded bg-muted p-3 text-sm"><div>As printed in the statement: <strong>{input.statement.display_value ?? 'display text not retained'}</strong></div><div className="mt-1 text-xs">Statement multiplier: {formatExactDecimal(input.statement.display_multiplier)} · Original unit: {input.statement.unit_measure ?? 'unknown'}</div><p className="mt-1 text-xs text-muted-foreground">Original display units may differ from the normalized amount above.</p></div>
      {auditExpanded ? <div className="space-y-2 rounded border border-dashed p-3" aria-label="Statement technical provenance">
      <div className="break-all font-mono">Raw lexical value: {input.statement.raw_value}</div>
      <div>Raw sign: {input.statement.sign ?? 'not supplied'} · XBRL scale: {input.statement.scale ?? 'not supplied'} · decimals: {input.statement.decimals ?? 'unknown'} · raw unit: {input.statement.unit_measure ?? 'unknown'}</div>
      <div>Statement multiplier: {input.statement.display_multiplier ?? 'unknown'} · label role: {input.statement.preferred_label_role ?? 'not retained'}</div>
      <div>Display-sign conventions (including negatedLabel) do not reverse the canonical value shown above.</div>
      <div className="break-all text-muted-foreground">Concept: {input.statement.concept}<br />Context: {input.statement.context_id}<br />Raw fact #{input.statement.raw_fact_id} · authority #{input.statement.statement_authority_id}<br />Locator: {JSON.stringify(input.statement.locator)}</div>
      </div> : null}
    </div> : null}
    {input.inputs ? <div className="mt-2 space-y-2"><div>Intermediate input: {formatExactDecimal(input.value_numeric_exact)} (base units). Its source inputs follow.</div>{auditExpanded ? <div>Canonical operand fact #{input.metric_fact_id}, publication #{input.publication_id} · exact base value {input.value_numeric_exact ?? 'unavailable'}</div> : null}<InputEvidence inputs={input.inputs} auditExpanded={auditExpanded} /></div> : null}
  </div>)}</div>;
}

export function FinancialEvidenceReading({ row, evidence, auditExpanded }: { row: FinancialHistoryRow; evidence?: SecEvidence; auditExpanded: boolean }) {
  const metric = CORE_METRICS.find(item => item.key === row.metric_key);
  return <>
    <div className="rounded-lg border bg-muted/20 p-4 [overflow-wrap:anywhere]">
      <h4 className="font-semibold">{metric?.label ?? row.metric_key ?? 'Financial fact'}</h4>
      <div className="mt-2 text-xl font-semibold tabular-nums">{row.value_numeric_exact !== null ? formatExactDecimal(row.value_numeric_exact) : row.value_text ?? 'No numeric or text value'} <span className="text-sm font-normal">{row.unit === 'currency' ? row.currency ?? 'currency unknown' : row.unit ?? 'unit unknown'}</span></div>
      <p className="mt-1 text-xs text-muted-foreground">Exact normalized base units; grouping and trailing zeros are display formatting only.</p>
      <p className="mt-2 text-sm">{row.fiscal_year ? `FY${row.fiscal_year}` : 'Fiscal year unproven'} · {row.period_type ?? 'period unknown'} · {row.period_basis === 'instant' ? `At ${row.period_end ?? 'date unknown'}` : `${row.period_start ?? 'start unknown'} → ${row.period_end ?? 'end unknown'}`}</p>
      <p className="mt-1 text-xs">{row.fact_nature?.replaceAll('_', ' ') ?? 'nature unknown'} · {row.source_role?.replaceAll('_', ' ') ?? 'source role unknown'} · {row.period_basis ?? 'basis unknown'}</p>
      {metric ? <p className="mt-2 text-sm text-muted-foreground">{metric.description}</p> : null}
    </div>
    {evidence ? <>
      <div className="text-sm">{evidence.currentness === 'superseded' ? 'Historical fact — superseded, still authorized. This is the original fact, not its replacement.' : 'Current for its period. Evidence access checked for this request.'}</div>
      <InputEvidence inputs={evidence.inputs} auditExpanded={auditExpanded} />
    </> : null}
    {auditExpanded ? <div className="space-y-1 rounded border border-dashed p-3 text-xs [overflow-wrap:anywhere]" aria-label="Canonical technical provenance">
      <div>{row.metric_key} · fact #{row.fact_id} · publication #{row.publication_id ?? 'not applicable'}</div>
      <div className="font-mono">Exact canonical base value: {row.value_numeric_exact ?? row.value_text ?? 'unavailable'}</div>
      <div>{row.unit ?? 'unit unknown'} · {row.currency ?? 'currency unknown / not applicable'} · {row.fact_nature ?? 'nature unknown'} · {row.source_role ?? 'source role unknown'}</div>
    </div> : null}
  </>;
}

export function FinancialEvidencePanel({ stockId, row, onClose, onAdd, readOnly }: {
  stockId: number; row: FinancialHistoryRow; onClose: () => void;
  onAdd: (reference: FinancialReference) => void; readOnly: boolean;
}) {
  const [state, setState] = useState<{ key: string; loading: boolean; error?: string; evidence?: SecEvidence } | null>(null);
  const [auditExpanded, setAuditExpanded] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const identityKey = `${stockId}:${row.row_key}:${row.publication_id}`;
  useEffect(() => {
    panel.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    if (row.evidence_capability !== 'sec_statement') return;
    const controller = new AbortController();
    setState({ key: identityKey, loading: true });
    readFinancialEvidence<SecEvidence>(apiClient, stockId, row, controller.signal)
      .then(result => {
        if (result.cancelled || controller.signal.aborted) return;
        setState({ key: identityKey, loading: false, error: result.error, evidence: result.evidence });
      });
    return () => controller.abort();
  }, [identityKey, row, stockId]);
  const current = state?.key === identityKey ? state : null;
  const evidence = current?.evidence;
  const sec = row.evidence_capability === 'sec_statement';
  const canAdd = row.row_kind === 'fact' && row.fact_id !== null && !readOnly && (!sec || !!evidence);
  return <Card ref={panel} className="min-w-0 max-w-full">
    <CardHeader><div className="flex items-start justify-between gap-2"><CardTitle>Financial fact &amp; original evidence</CardTitle><Button type="button" variant="ghost" size="sm" onClick={onClose} aria-label="Close financial evidence"><X className="h-4 w-4" /></Button></div><CardDescription>Read the amount, period and original statement together. Technical provenance is available on demand.</CardDescription></CardHeader>
    <CardContent className="space-y-4">
      {!sec || evidence ? <FinancialEvidenceReading row={row} evidence={evidence} auditExpanded={auditExpanded} /> : null}
      {sec && (!current || current.loading) ? <div className="flex items-center gap-2 text-sm"><LoaderCircle className="h-4 w-4 animate-spin" />Checking current source access and retained evidence…</div> : null}
      {current?.error ? <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">{current.error}. No previous values or evidence details are being shown here. Refresh financials to check the current response.</div> : null}
      {evidence ? <>
        <div className="flex flex-wrap gap-3 text-xs">{inputEvidenceFilings(evidence).map(filing => filing.sec_url && /^https:\/\/www\.sec\.gov\/Archives\//.test(filing.sec_url) ? <a key={filing.accession} href={filing.sec_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">{filing.form} · {filing.accession}<ExternalLink className="h-3 w-3" /></a> : null)}</div>
      </> : null}
      {!sec || evidence ? <Button type="button" size="sm" variant="outline" aria-expanded={auditExpanded} onClick={() => setAuditExpanded(!auditExpanded)}>{auditExpanded ? 'Hide' : 'Show'} exact values &amp; technical provenance</Button> : null}
      {!sec ? <div className="rounded border p-3 text-sm">{row.evidence_capability === 'document_review' && row.document_id ? <Link href={`/documents/${row.document_id}/review`} className="text-primary hover:underline">Review original evidence in the authorized document</Link> : 'Reference only: no original-document resolver is available for this fact. A fact reference does not imply SEC/PDF evidence exists.'}</div> : null}
      <Button type="button" disabled={!canAdd} onClick={() => {
        if (!canAdd || row.fact_id === null) return;
        onAdd({ source_type: 'metric_fact', source_id: row.fact_id, label: `${CORE_METRICS.find(item => item.key === row.metric_key)?.label ?? row.metric_key} ${row.fiscal_year ? `FY${row.fiscal_year}` : row.period_type ?? ''}`,
          source_date: row.period_end ?? undefined,
          claim: `Reviewed ${row.metric_key} for ${row.period_end ?? 'an unproven period'}; immutable fact #${row.fact_id}${sec ? ' and its retained SEC statement evidence' : ' (reference only unless original document reviewed)'}.` });
      }}><Plus className="h-4 w-4" />Add to research evidence</Button>
      <div className="text-xs text-muted-foreground">This adds a reference to your draft. Only your explicit Save records a revision; it does not create a new financial fact.</div>
    </CardContent>
  </Card>;
}
