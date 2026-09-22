'use client';

import { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, List, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { CORE_METRICS, annualCells, pageRows, type FinancialHistory, type FinancialHistoryRow } from '@/lib/financialHistory';
import { annualReading, formatBillions } from '@/lib/financialTrends';
import { AnnualValue, FinancialTrends, readingReason } from './FinancialTrends';

function stateText(row: FinancialHistoryRow) {
  return row.reason_code === 'not_returned'
    ? 'This response did not return an assignable fact; reason unknown.'
    : `${row.status}: ${row.reason_code ?? 'reason unknown'}`;
}

function Period({ row }: { row: FinancialHistoryRow }) {
  return <div className="text-xs text-muted-foreground">
    {row.period_basis === 'instant' ? 'Period end' : row.period_basis === 'duration' ? `${row.period_start ?? 'start unknown'} →` : 'Basis unknown'} {row.period_end ?? 'date unknown'}
    <div>{row.period_type ?? 'period type unknown'} · {row.fiscal_year ? `FY${row.fiscal_year}` : 'fiscal year unproven'}</div>
  </div>;
}

export function AnnualFinancialsTable({ history, onSelect, onRefresh, refreshing }: {
  history: FinancialHistory;
  onSelect: (row: FinancialHistoryRow) => void;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const [page, setPage] = useState(1);
  const [showDetails, setShowDetails] = useState(false);
  const [showAnnual, setShowAnnual] = useState(false);
  const pivot = useMemo(() => annualCells(history), [history]);
  const readings = useMemo(() => CORE_METRICS.map(metric => annualReading(history, metric.key)), [history]);
  const detail = pageRows(history.rows, page);
  const years = [...history.annual_window.years].reverse();
  const latestYear = years[0];
  const sources = [...new Set(readings.flatMap(reading => reading.points.at(-1)?.row ? [reading.points.at(-1)!.row!] : [])
    .map(row => `${row.source_type?.toUpperCase()} · ${row.source_role?.replaceAll('_', ' ')}`))];
  return <Card className="min-w-0 max-w-full" id="financial-reading">
    <CardHeader>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <CardTitle>Operating performance &amp; cash quality</CardTitle>
        <Button type="button" size="sm" variant="outline" onClick={onRefresh} disabled={refreshing}><RefreshCw className="h-4 w-4" />Refresh financials</Button>
      </div>
      <CardDescription>Start with what changed, then investigate why. Reported annual facts, not an investment conclusion. Click a value to check the evidence.</CardDescription>
    </CardHeader>
    <CardContent className="min-w-0 space-y-4">
      {latestYear ? <>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground"><span>Latest retained annual period · FY{latestYear}</span><span>Rounded display values · billions, currency shown per metric</span></div>
        <div className="grid gap-3 sm:grid-cols-3">{readings.slice(0, 3).map(reading => <div key={reading.metric.key} className="rounded-xl border bg-muted/20 p-4">
          <div className="mb-3 text-sm font-medium">{reading.metric.label}</div><AnnualValue point={reading.points.at(-1)!} previous={reading.points.at(-2)} label={reading.metric.label} onSelect={onSelect} headline />
        </div>)}</div>
        <p className="text-xs text-muted-foreground">Sources for latest-year readings: {sources.join('; ') || 'No comparable actuals'}. Source and period exceptions remain in the annual table and evidence.</p>
        <div className="text-xs text-muted-foreground">YoY compares adjacent, compatible reported fiscal years: (current − prior) / prior. It is a display calculation, not a published fact or an adjustment. N/M means a zero/negative prior value or a current loss.</div>
      </> : null}
      {readings.some(reading => reading.points.some(point => point.reason || point.row?.unit === 'shares')) ? <div className="space-y-1 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950">
        <div className="font-semibold">Reading limits — gaps are not zero</div>
        {readings.map(reading => {
          const reasons = [...new Set(reading.points.map(p => p.reason).filter(Boolean))];
          return reasons.map(reason => <div key={`${reading.metric.key}:${reason}`}>{reading.metric.label} · {reading.points.filter(p => p.reason === reason).map(p => `FY${p.year}`).join(', ')}: {readingReason(reason)}</div>);
        })}
        {readings.some(reading => reading.points.some(point => point.row?.unit === 'shares')) ? <div>Reported share counts: split basis is unverified; cross-year lines and YoY are withheld, not adjusted or guessed.</div> : null}
      </div> : null}
      {pivot.cycleStates.map(row => <div key={row.row_key} className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">Filing-cycle state: {stateText(row)}<div className="mt-1 text-xs">Scope: {JSON.stringify(row.scope ?? {})}</div></div>)}
      {history.annual_window.status === 'undetermined' ? Object.entries(pivot.metricStates).flatMap(([key, rows]) => rows.map(row => <div key={row.row_key} className="rounded border border-amber-300 p-3 text-sm text-amber-900">{CORE_METRICS.find(metric => metric.key === key)?.label ?? key}: {stateText(row)}</div>)) : null}
      {history.annual_window.status === 'undetermined' ? <div className="rounded border border-dashed p-4 text-sm">Annual window undetermined: no authorized completed FY anchor was proven. All returned observations remain in the detail view.</div> : <FinancialTrends readings={readings} onSelect={onSelect} />}
      <div className="flex flex-wrap gap-2 border-t pt-4"><Button size="sm" variant="outline" aria-expanded={showAnnual} disabled={history.annual_window.status !== 'determined'} onClick={() => setShowAnnual(!showAnnual)}>{showAnnual ? 'Hide' : 'Show'} ten-year annual table</Button>
        <Button type="button" size="sm" variant="ghost" aria-expanded={showDetails} onClick={() => setShowDetails(!showDetails)}><List className="h-4 w-4" />{showDetails ? 'Hide' : 'Show'} all financial details</Button></div>
      {showAnnual && history.annual_window.status === 'determined' ? <div className="min-w-0 max-w-full space-y-3" data-testid="annual-table-container">
        <p className="text-xs text-muted-foreground">Actual observations · billions (USD or other currency shown), shares in billions · rounded to two decimals. The latest three years are highlighted. Multiple observations stay separate; source/period exceptions appear below the value. Exact periods and provenance are in the evidence and full details.</p>
        <Table>
          <TableHeader><TableRow><TableHead className="sticky left-0 z-10 min-w-52 bg-card">Annual metric / definition</TableHead>{years.map(year => <TableHead key={year} className={`min-w-28 ${year >= latestYear - 2 ? 'bg-primary/5 font-semibold text-foreground' : ''}`}>FY{year}</TableHead>)}</TableRow></TableHeader>
          <TableBody>{CORE_METRICS.map(metric => <TableRow key={metric.key}>
            <TableCell className="sticky left-0 z-10 bg-card align-top"><div className="font-medium">{metric.label}</div><div className="mt-1 max-w-52 text-xs text-muted-foreground">{metric.description}</div>
              {(pivot.metricStates[metric.key] ?? []).map(row => <div key={row.row_key} className="mt-2 text-xs text-amber-800">Whole metric: {stateText(row)}</div>)}
            </TableCell>
            {years.map(year => {
              const cell = pivot.cells[metric.key][year];
              return <TableCell key={year} className={`align-top ${year >= latestYear - 2 ? 'bg-primary/5' : ''}`}>
                <div className="space-y-3">{cell.observations.map(row => {
                  const value = formatBillions(row);
                  return <div key={row.row_key}>
                    <Button type="button" size="sm" variant="link" className="h-auto p-0 tabular-nums" onClick={() => onSelect(row)} aria-label={`Inspect ${metric.label} FY${year} fact ${row.fact_id}`}>{value.text}</Button>
                    <div className="text-xs text-muted-foreground">{row.unit === 'currency' ? row.currency ?? 'Currency unknown' : row.unit === 'shares' ? 'shares' : `Unscaled · ${value.unitLabel}`}</div>
                    {cell.observations.length > 1 || row.source_type !== 'sec' || row.source_role !== 'primary_as_filed_actual' || row.fact_nature !== 'actual' || readings.find(r => r.metric.key === metric.key)?.points.find(p => p.year === year)?.reason ? <><div className="my-1 text-xs">{row.source_type ?? 'source unknown'} · {row.source_role ?? 'role unknown'} · {row.fact_nature ?? 'nature unknown'}</div><Period row={row} /></> : null}
                  </div>;
                })}{cell.states.map(row => <div key={row.row_key} className="text-xs text-muted-foreground">{stateText(row)}</div>)}
                  {!cell.observations.length && !cell.states.length ? <div className="text-xs text-muted-foreground">See metric/filing scope above; no separate cell observation.</div> : null}
                </div>
              </TableCell>;
            })}
          </TableRow>)}</TableBody>
        </Table><p className="text-xs text-muted-foreground">Unless an exception is shown, observations are SEC primary as-filed actuals. Different fact IDs are never merged. Long-term debt components are not total debt; weighted-average diluted shares are not period-end shares outstanding.</p></div> : null}
      {showDetails ? <div className="min-w-0 max-w-full space-y-3">
        <div className="text-xs text-muted-foreground">Evaluated {history.evaluated_at} · {history.available_fact_count} facts + {history.state_count} states = {history.total_rows} detail rows. All views use this same response. {pivot.otherRows.length} rows are outside core annual cells. Comparison policy: annual-reading-v1.</div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span>Rows {detail.start}–{detail.end} of {detail.total} · Page {detail.page} of {detail.pageCount}</span>
          <div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={detail.page <= 1} onClick={() => setPage(detail.page - 1)}><ChevronLeft className="h-4 w-4" />Previous</Button><Button type="button" size="sm" variant="outline" disabled={detail.page >= detail.pageCount} onClick={() => setPage(detail.page + 1)}>Next<ChevronRight className="h-4 w-4" /></Button></div>
        </div>
        <Table><TableHeader><TableRow><TableHead>Metric / identity</TableHead><TableHead>Exact base value / state</TableHead><TableHead>Period</TableHead><TableHead>Source / evidence</TableHead></TableRow></TableHeader>
          <TableBody>{detail.rows.map(row => <TableRow key={row.row_key}>
            <TableCell className="text-xs"><div>{row.metric_key ?? 'Filing-cycle state'}</div><div className="mt-1 break-all font-mono text-muted-foreground">{row.row_key}</div></TableCell>
            <TableCell className="text-xs">{row.row_kind === 'fact' ? <><div className="break-all font-mono">{row.value_numeric_exact ?? row.value_text ?? 'No numeric or text value'}</div><div>{row.unit ?? 'unit unknown'} · {row.currency ?? 'currency unknown / not applicable'}</div></> : stateText(row)}</TableCell>
            <TableCell><Period row={row} /></TableCell>
            <TableCell className="text-xs"><div>{row.source_type ?? 'source unknown'} · {row.source_role ?? 'role unknown'} · {row.fact_nature ?? 'nature unknown'}</div><Badge variant="outline" className="my-1">{row.row_kind}</Badge>{row.row_kind === 'fact' ? <div><Button type="button" size="sm" variant="outline" onClick={() => onSelect(row)}>Inspect fact / evidence</Button><div className="mt-1">{row.evidence_capability.replaceAll('_', ' ')}</div></div> : null}</TableCell>
          </TableRow>)}</TableBody>
        </Table>
      </div> : null}
    </CardContent>
  </Card>;
}
