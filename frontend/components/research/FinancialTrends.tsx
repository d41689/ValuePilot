'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { chartGeometry, cashQuestion, formatBillions, type AnnualPoint, type AnnualReading } from '@/lib/financialTrends';
import type { FinancialHistoryRow } from '@/lib/financialHistory';

const REASONS: Record<string, string> = {
  missing_observation: 'No comparable observation returned', not_returned: 'No fact returned; reason unknown',
  multiple_observations: 'Multiple observations — inspect the annual table', blocked_or_conflicting: 'Blocked or conflicting evidence — inspect the annual table',
  identity_unproven: 'Comparable identity not proven', annual_period_unproven: 'Full fiscal-year period not proven',
  incompatible_identity: 'Definition, source, dimensions or units differ', nonadjacent_fiscal_years: 'Fiscal years are not adjacent',
  noncontiguous_fiscal_periods: 'Fiscal periods are not continuous/comparable', nonpositive_base_or_loss: 'N/M: prior value is zero/negative or current year is a loss',
  no_valid_numeric_value: 'No valid numeric value', incompatible_period_basis: 'Period basis differs from this metric',
  share_split_basis_unproven: 'Share split basis unverified — YoY unavailable',
};
export const readingReason = (reason: string | null) => REASONS[reason || ''] || 'Comparison unavailable';

export function AnnualValue({ point, label, previous, onSelect, headline = false }: {
  point: AnnualPoint; label: string; previous?: AnnualPoint; onSelect: (row: FinancialHistoryRow) => void; headline?: boolean;
}) {
  const row = point.row;
  if (!row) return <div className="text-sm text-amber-800">{readingReason(point.reason)}</div>;
  const value = formatBillions(row);
  return <div>
    <Button variant="link" size="sm" className={`h-auto whitespace-normal p-0 text-left tabular-nums ${headline ? 'text-2xl font-semibold tracking-tight' : 'text-base font-semibold'}`}
      onClick={() => onSelect(row)} aria-label={`Inspect ${label} FY${point.year} fact ${row.fact_id}`}>{value.text}</Button>
    <div className="text-xs text-muted-foreground">{value.unitLabel}</div>
    <div className="mt-2 text-sm tabular-nums">{point.change.status === 'available' ? <><span className="font-medium">{point.change.text}</span> <span className="text-muted-foreground">YoY</span></> : <span className="text-xs text-muted-foreground">{readingReason(point.change.reason)}</span>}</div>
    {previous?.row ? <Button variant="link" size="sm" className="mt-1 h-auto p-0 text-xs text-muted-foreground" onClick={() => onSelect(previous.row!)}
      aria-label={`Inspect comparison ${label} FY${previous.year} fact ${previous.row.fact_id}`}>{point.change.status === 'available' ? 'Compare' : 'Inspect'} FY{previous.year}</Button> : null}
    {point.change.caveat ? <div className="mt-1 text-xs text-amber-800">{point.change.caveat}</div> : null}
  </div>;
}

const GROUPS = [
  { id: 'growth', label: 'Growth', question: 'Are revenue and profit growing together?', keys: ['is.revenue', 'is.net_income'], note: 'Reported revenue and net income share one currency axis. Growth alone does not prove a durable moat.' },
  { id: 'cash', label: 'Cash conversion', question: 'Does profit turn into cash?', keys: ['is.net_income', 'is.operating_cash_flow', 'cf.capital_expenditures'], note: 'Capex is reported purchases of property, plant and equipment, not maintenance capex. Operating cash flow is not owner earnings.' },
  { id: 'balance', label: 'Financial buffer', question: 'How have cash and long-term debt components changed?', keys: ['bs.cash_and_equivalents', 'cap.long_term_debt_current', 'cap.long_term_debt_noncurrent'], note: 'These are long-term debt components, NOT total debt. Cash excludes other liquid investments. This is not a complete solvency assessment.' },
  { id: 'shares', label: 'Shares & SBC', question: 'What do reported share counts and stock compensation show?', keys: ['equity.weighted_average_diluted_shares', 'cf.stock_based_compensation'], note: 'Weighted-average diluted shares are NOT period-end shares outstanding. Split comparability is unverified: share counts remain separate reported points, with no connecting line or YoY. A jump may reflect a split, not issuance. SBC uses a separate currency axis.' },
];
const COLORS = ['#2563eb', '#0f766e', '#b45309'];

function TrendChart({ readings }: { readings: AnnualReading[] }) {
  const geometry = chartGeometry(readings);
  if (geometry.reason) return <div className="rounded border border-dashed p-5 text-sm text-muted-foreground">{geometry.reason === 'mixed_units_or_sources'
    ? 'Chart withheld: units, currencies, source roles or comparison scope differ. All observations remain in the annual table.'
    : geometry.reason === 'unaligned_fiscal_periods' ? 'Chart withheld: the same FY labels refer to different reporting periods. Inspect the separate observations in the annual table.'
      : 'No comparable annual observations to chart. Inspect the visible gaps and annual table.'}</div>;
  const years = readings[0].points.map(point => point.year);
  const anyRow = readings.flatMap(reading => reading.points).find(point => point.row)?.row;
  const label = anyRow ? formatBillions(anyRow).unitLabel : '';
  const top = geometry.maxRow ? formatBillions(geometry.maxRow).text : '0';
  const bottom = geometry.minRow ? formatBillions(geometry.minRow).text : '0';
  return <div className="min-w-0">
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">{readings.map((reading, i) => <div key={reading.metric.key} className="flex items-center gap-2"><span aria-hidden="true" className="inline-block w-5 border-t-2" style={{ borderColor: COLORS[i], borderStyle: i === 1 ? 'dashed' : i === 2 ? 'dotted' : 'solid' }} />{reading.metric.label}</div>)}</div>
    <div className="mt-3 text-xs text-muted-foreground">{label} · zero-based axis · {anyRow?.unit === 'shares' ? 'split basis unverified; reported points only' : 'gaps are not zero'}</div>
    <svg viewBox="0 0 600 230" role="img" aria-label={`${readings.map(r => r.metric.label).join(', ')} ${anyRow?.unit === 'shares' ? 'as-reported annual observations, split basis unverified' : 'annual trends'}. Use the year selector and value buttons below for accessible values and evidence.`} className="mt-1 w-full text-muted-foreground">
      <line x1="62" x2="570" y1={18 + geometry.zeroY * 1.65} y2={18 + geometry.zeroY * 1.65} stroke="currentColor" opacity="0.4" />
      <line x1="62" x2="570" y1="18" y2="18" stroke="currentColor" opacity="0.15" />
      <text x="55" y="23" textAnchor="end" fontSize="11" fill="currentColor">{top}</text>
      <text x="55" y="188" textAnchor="end" fontSize="11" fill="currentColor">{bottom}</text>
      {geometry.zeroY > 2 && geometry.zeroY < 98 ? <text x="55" y={23 + geometry.zeroY * 1.65} textAnchor="end" fontSize="11" fill="currentColor">0</text> : null}
      {years.map((year, i) => <text key={year} x={62 + i * 508 / Math.max(1, years.length - 1)} y="211" fontSize="11" textAnchor="middle" fill="currentColor">{year}</text>)}
      {geometry.series.map((series, i) => <g key={series.key}>
        {series.segments.map((segment, j) => <g key={j}>
          <polyline points={segment.map(p => `${62 + p.x * 5.08},${18 + p.y * 1.65}`).join(' ')} fill="none" stroke={COLORS[i]} strokeWidth="2.5" strokeDasharray={i === 1 ? '7 4' : i === 2 ? '2 4' : undefined} />
          {segment.map(p => <circle key={p.row.row_key} cx={62 + p.x * 5.08} cy={18 + p.y * 1.65} r="3" fill={COLORS[i]}><title>{readings[i].metric.label} FY{p.year}: {formatBillions(p.row).text} {label}</title></circle>)}
        </g>)}
      </g>)}
    </svg>
  </div>;
}

export function FinancialTrends({ readings, onSelect }: { readings: AnnualReading[]; onSelect: (row: FinancialHistoryRow) => void }) {
  const [groupId, setGroupId] = useState('cash');
  const years = readings[0]?.points.map(point => point.year) || [];
  const [year, setYear] = useState(years.at(-1));
  const group = GROUPS.find(item => item.id === groupId)!;
  const selected = group.keys.map(key => readings.find(reading => reading.metric.key === key)!);
  const caveats = [...new Set(selected.flatMap(reading => reading.points.filter(point => point.change.caveat).map(point => `FY${point.year}: ${point.change.caveat}`)))];
  return <section className="space-y-4 rounded-xl border p-4" aria-label="Financial trends">
    <div className="flex flex-wrap gap-2" role="group" aria-label="Research question">
      {GROUPS.map(item => <Button key={item.id} size="sm" variant={groupId === item.id ? 'default' : 'outline'} aria-pressed={groupId === item.id} onClick={() => setGroupId(item.id)}>{item.label}</Button>)}
    </div>
    <div><h4 className="font-semibold">{group.question}</h4><p className="mt-1 text-sm text-muted-foreground">{group.id === 'cash' ? cashQuestion(readings.find(r => r.metric.key === 'is.net_income')!, readings.find(r => r.metric.key === 'is.operating_cash_flow')!) : group.note}</p></div>
    {group.id === 'shares' ? <div className="grid gap-5">{selected.map(reading => <TrendChart key={reading.metric.key} readings={[reading]} />)}</div> : <TrendChart readings={selected} />}
    {years.length ? <div className="flex items-center gap-3"><span className="text-xs font-medium">Inspect a fiscal year</span><Select value={String(year)} onValueChange={value => setYear(Number(value))}><SelectTrigger className="w-32" aria-label="Trend fiscal year"><SelectValue /></SelectTrigger><SelectContent>{[...years].reverse().map(value => <SelectItem key={value} value={String(value)}>FY{value}</SelectItem>)}</SelectContent></Select></div> : null}
    <div className="grid gap-4 sm:grid-cols-3">{selected.map(reading => {
      const index = reading.points.findIndex(point => point.year === year); const point = reading.points[index];
      return point ? <div key={reading.metric.key}><div className="mb-2 text-xs font-medium">{reading.metric.label} · FY{year}</div><AnnualValue point={point} previous={reading.points[index - 1]} label={reading.metric.label} onSelect={onSelect} /></div> : null;
    })}</div>
    {group.id === 'cash' ? <p className="text-xs text-muted-foreground">{group.note}</p> : null}
    {caveats.length ? <p className="text-xs text-amber-800">Period-length differences: {caveats.join(' ')}</p> : null}
    <p className="text-xs text-muted-foreground">Lines stop at missing or incompatible periods. Chart coordinates are rounded; use values to open exact evidence. No source is selected by display order.</p>
  </section>;
}
