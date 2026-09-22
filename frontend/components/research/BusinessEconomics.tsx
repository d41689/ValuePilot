'use client';

import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { businessEconomics, analysisObservation, ANALYSIS_METRICS, REASONS, type EconomicsSeries, type EconomicsPoint } from '@/lib/businessEconomics';
import { formatExactDecimal, type FinancialHistory, type FinancialHistoryRow } from '@/lib/financialHistory';

type Actions = { readOnly: boolean; onSelect: (row: FinancialHistoryRow) => void; onResearch: (text: string) => void };

export function EconomicsCalculation({ series, point, evaluatedAt, readOnly, onSelect, onResearch }: Actions & {
  series: EconomicsSeries; point: EconomicsPoint; evaluatedAt: string;
}) {
  return <div className="min-w-0 space-y-3 rounded-lg border p-4" aria-label={`${series.label} calculation`}>
    <div><h5 className="font-semibold">{series.label} · FY{point.year}</h5>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{point.text}<span className="ml-2 text-xs font-normal">{point.unitLabel === '%' ? '' : point.unitLabel}</span></p>
      <p className="mt-1 text-xs text-muted-foreground">Display calculation · {series.formula}</p></div>
    <p className="text-sm text-muted-foreground">{series.caveat}</p>
    {point.status === 'available' ? <>
      <div className="text-xs text-muted-foreground">Same reported period: {point.inputs[0].period_start} → {point.inputs[0].period_end}. SEC primary as-filed actuals; no tax, normalization or annualization assumptions.</div>
      <div className="grid min-w-0 gap-2 sm:grid-cols-2">{point.inputs.map(row => <div key={row.row_key} className="min-w-0 rounded bg-muted/30 p-3 text-sm [overflow-wrap:anywhere]">
        <div>{ANALYSIS_METRICS.find(m => m.key === row.metric_key)?.label}</div>
        <div className="my-1 font-medium tabular-nums">{formatExactDecimal(row.value_numeric_exact)} {row.currency}</div>
        <Button size="sm" variant="link" className="h-auto whitespace-normal p-0 text-left" onClick={() => onSelect(row)}>Inspect {ANALYSIS_METRICS.find(m => m.key === row.metric_key)?.label} · fact #{row.fact_id}</Button>
        <div className="mt-1 text-xs text-muted-foreground">Publication #{row.publication_id}</div>
      </div>)}</div>
      {point.valueExact !== null ? <div className="break-all text-xs text-muted-foreground">Exact difference: {formatExactDecimal(point.valueExact)} {point.inputs[0].currency}</div> : <p className="text-xs text-muted-foreground">Percentage rounded to two decimals from the exact operands above, not a separately reported fact.</p>}
      <Button size="sm" variant="outline" disabled={readOnly} onClick={() => {
        const text = analysisObservation(series, point, evaluatedAt);
        if (!readOnly && text) onResearch(text);
      }}>Research this calculation</Button>
      <p className="text-xs text-muted-foreground">Adds only this factual background to your observation draft. You supply the explanation and judgment; inspect and attach evidence separately. Nothing is saved automatically.</p>
    </> : <p className="text-sm text-amber-800">{REASONS[point.reason || ''] || 'Calculation unavailable; input identity was not proven.'}</p>}
    <div className="break-all text-xs text-muted-foreground">{point.policy} · evaluated {evaluatedAt}</div>
  </div>;
}

export function BusinessEconomics({ history, readOnly, onSelect, onResearch }: Actions & { history: FinancialHistory }) {
  const model = useMemo(() => businessEconomics(history), [history]);
  const [selected, setSelected] = useState('operating_margin');
  const [year, setYear] = useState(model.years.at(-1));
  const series = model.series.find(s => s.id === selected)!;
  const point = series.points.find(p => p.year === year);
  return <section className="min-w-0 space-y-4 rounded-xl border p-4" aria-label="Business economics">
    <div><h4 className="font-semibold">What do the economics tell us?</h4><p className="mt-1 text-sm text-muted-foreground">Compare profitability and cash generation before forming a judgment. These are descriptive calculations, not quality scores.</p></div>
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
      <div className="font-medium">ROIC — not calculated in this view</div>
      <p className="mt-1">Operating margin is not a return on invested capital. ROIC needs a supported NOPAT and average invested-capital method, tax and capital adjustments, canonical inputs, and the required economic-class and risk reviews. No tax rate or capital base is guessed here.</p>
    </div>
    <div className="flex flex-wrap gap-2" role="group" aria-label="Economics calculation">
      {model.series.map(s => <Button key={s.id} size="sm" variant={selected === s.id ? 'default' : 'outline'} className="h-auto min-h-9 whitespace-normal text-left" aria-pressed={selected === s.id} onClick={() => setSelected(s.id)}>{s.label}</Button>)}
    </div>
    <p className="text-sm font-medium">{series.question}</p>
    {model.years.length ? <>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3" aria-label="Latest three annual calculations">{series.points.slice(-3).map(p => <Button key={p.year} variant={year === p.year ? 'secondary' : 'outline'} className="h-auto min-w-0 flex-col items-start whitespace-normal p-3" aria-pressed={year === p.year} onClick={() => setYear(p.year)}>
        <span className="text-xs">FY{p.year}</span><span className="text-base tabular-nums">{p.text} {p.unitLabel === '%' ? '' : p.unitLabel}</span>
      </Button>)}</div>
      <div className="flex flex-wrap items-center gap-3"><span className="text-xs">Inspect an annual calculation</span><Select value={String(year)} onValueChange={value => setYear(Number(value))}><SelectTrigger className="w-32" aria-label="Economics fiscal year"><SelectValue /></SelectTrigger><SelectContent>{[...model.years].reverse().map(y => <SelectItem key={y} value={String(y)}>FY{y}</SelectItem>)}</SelectContent></Select></div>
      {point ? <EconomicsCalculation series={series} point={point} evaluatedAt={model.evaluatedAt} readOnly={readOnly} onSelect={onSelect} onResearch={onResearch} /> : null}
    </> : <p className="text-sm text-muted-foreground">Annual window not proven. No year or calculation has been invented; inspect returned facts below.</p>}
    <div className="grid min-w-0 gap-3 border-t pt-3 text-xs text-muted-foreground sm:grid-cols-2">
      <div><h5 className="font-medium text-foreground">Survival: cash is not the whole debt picture</h5><p className="mt-1">Use the financial-buffer view below for reported cash and long-term debt components. This view does not establish complete debt, restrictions on cash, maturity schedules or interest coverage, and does not calculate net debt or certify solvency.</p></div>
      <div><h5 className="font-medium text-foreground">Per-share value: comparability first</h5><p className="mt-1">Use Shares &amp; SBC below to inspect reported amounts. A proven share-class and split basis is needed before computing per-share trends. SBC and repurchases need separate economic analysis; no automatic adjustment is made.</p></div>
    </div>
    <p className="text-xs text-muted-foreground">Price and margin of safety still require your separate valuation and assumptions. Profitability alone does not establish that a stock is cheap.</p>
  </section>;
}
