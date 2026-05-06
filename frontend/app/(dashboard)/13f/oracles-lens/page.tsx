'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, FileText, Info, PanelRightOpen, Search, SlidersHorizontal, X } from 'lucide-react';

import apiClient from '@/lib/api/client';
import oracleLensHelpers from '@/lib/oraclesLens';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
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

const {
  buildOracleLensQueryParams,
  cautionTone,
  missingDataReasons,
  normalizeOracleLensRows,
  radarBubbles,
  suggestedResearchSteps,
} = oracleLensHelpers;

const RADAR_SIZE_CLASSES: Record<string, string> = {
  'h-14 w-14': 'h-14 w-14',
  'h-16 w-16': 'h-16 w-16',
  'h-20 w-20': 'h-20 w-20',
  'h-24 w-24': 'h-24 w-24',
};

const RADAR_TONE_CLASSES: Record<string, string> = {
  'border-slate-300 bg-slate-50 text-slate-950': 'border-slate-300 bg-slate-50 text-slate-950',
  'border-emerald-300 bg-emerald-50 text-emerald-950':
    'border-emerald-300 bg-emerald-50 text-emerald-950',
  'border-amber-300 bg-amber-50 text-amber-950': 'border-amber-300 bg-amber-50 text-amber-950',
};

type OracleLensPayload = {
  period: string | null;
  period_end_date: string | null;
  latest_complete_period: string | null;
  baseline_notice: string;
  coverage: {
    manager_count: number;
    holding_count: number;
    linked_holding_count: number;
    manager_signal_quality_coverage?: number;
    price_coverage_count?: number;
    value_line_coverage_count?: number;
    valuation_reference_coverage_count?: number;
    candidate_count?: number;
    price_context?: string;
    price_target_date?: string | null;
    price_missing_count?: number;
    price_coverage_ratio?: number;
    price_backfill_required?: boolean;
    price_backfill_hint?: string | null;
  };
  periods?: Array<{
    label: string;
    period_end_date: string;
    manager_count: number;
    is_selected: boolean;
    is_latest_complete: boolean;
  }>;
  items: unknown[];
};

function formatInteger(value: number | null | undefined) {
  if (typeof value !== 'number') {
    return '—';
  }
  return value.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

function formatCoveragePercent(value: number | null | undefined) {
  if (typeof value !== 'number') {
    return '—';
  }
  return `${Math.round(value * 100)}%`;
}

function formatPercentValue(value: number | null | undefined, digits = 1) {
  if (typeof value !== 'number') {
    return '—';
  }
  return `${(value * 100).toFixed(digits)}%`;
}

function formatCurrency(value: number | null | undefined) {
  if (typeof value !== 'number') {
    return '—';
  }
  return `$${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
}

export default function OraclesLensPage() {
  const [selectedStockId, setSelectedStockId] = useState<number | null>(null);
  const [filters, setFilters] = useState({
    period: '',
    minHolders: '3',
    minSignalScore: '',
    superinvestorOnly: true,
    sort: 'signal_weighted_consensus',
  });
  const queryParams = useMemo(
    () =>
      buildOracleLensQueryParams({
        period: filters.period.trim() || undefined,
        minHolders: filters.minHolders ? Number(filters.minHolders) : undefined,
        minSignalScore: filters.minSignalScore ? Number(filters.minSignalScore) : undefined,
        superinvestorOnly: filters.superinvestorOnly,
        sort: filters.sort,
      }),
    [filters]
  );
  const dashboardQuery = useQuery({
    queryKey: ['oracles-lens-dashboard', queryParams],
    queryFn: async () => {
      const path = queryParams ? `/13f/oracles-lens?${queryParams}` : '/13f/oracles-lens';
      const res = await apiClient.get(path);
      return res.data as OracleLensPayload;
    },
  });

  const payload = dashboardQuery.data;
  const rows = useMemo(() => normalizeOracleLensRows(payload?.items ?? []), [payload?.items]);
  const bubbles = useMemo(() => radarBubbles(rows), [rows]);
  const selectedRow = useMemo(
    () => rows.find((row) => row.stockId === selectedStockId) ?? null,
    [rows, selectedStockId]
  );
  const researchSteps = useMemo(
    () => (selectedRow ? suggestedResearchSteps(selectedRow) : []),
    [selectedRow]
  );
  const selectedMissingReasons = useMemo(
    () => (selectedRow ? missingDataReasons(selectedRow) : []),
    [selectedRow]
  );
  const coverage = payload?.coverage;
  const periodOptions = payload?.periods ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase text-muted-foreground">
            13F Research Funnel
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Oracle&apos;s Lens</h1>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            Signal-ranked research candidates from reported 13F ownership behavior.
          </p>
        </div>
        <div className="rounded-md border border-border/70 bg-background px-3 py-2 text-sm">
          <div className="text-xs uppercase text-muted-foreground">Latest complete period</div>
          <div className="mt-1 font-medium">{payload?.latest_complete_period ?? '—'}</div>
        </div>
      </div>

      <div className="flex gap-3 rounded-md border border-amber-300/70 bg-amber-50 px-4 py-3 text-sm text-amber-950">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div>{payload?.baseline_notice ?? '13F filings are delayed snapshots.'}</div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <Card className="rounded-md">
          <CardContent className="p-4">
            <div className="text-xs uppercase text-muted-foreground">Selected period</div>
            <div className="mt-2 text-xl font-semibold">{payload?.period ?? '—'}</div>
          </CardContent>
        </Card>
        <Card className="rounded-md">
          <CardContent className="p-4">
            <div className="text-xs uppercase text-muted-foreground">Managers</div>
            <div className="mt-2 text-xl font-semibold">{formatInteger(coverage?.manager_count)}</div>
          </CardContent>
        </Card>
        <Card className="rounded-md">
          <CardContent className="p-4">
            <div className="text-xs uppercase text-muted-foreground">Linked holdings</div>
            <div className="mt-2 text-xl font-semibold">
              {formatInteger(coverage?.linked_holding_count)}
            </div>
          </CardContent>
        </Card>
        <Card className="rounded-md">
          <CardContent className="p-4">
            <div className="text-xs uppercase text-muted-foreground">Candidates</div>
            <div className="mt-2 text-xl font-semibold">{formatInteger(rows.length)}</div>
          </CardContent>
        </Card>
      </div>

      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Price Coverage</CardTitle>
          <p className="text-sm text-muted-foreground">
            Local EOD price coverage for the selected snapshot. Missing historical prices require
            an explicit backfill.
          </p>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-4">
            <div>
              <div className="text-xs uppercase text-muted-foreground">Context</div>
              <div className="mt-1 font-medium">
                {coverage?.price_context === 'historical_snapshot'
                  ? 'Historical snapshot'
                  : 'Latest local price'}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase text-muted-foreground">Target date</div>
              <div className="mt-1 font-medium">{coverage?.price_target_date ?? 'Latest'}</div>
            </div>
            <div>
              <div className="text-xs uppercase text-muted-foreground">Coverage</div>
              <div className="mt-1 font-medium">
                {formatInteger(coverage?.price_coverage_count)} /{' '}
                {formatInteger(coverage?.candidate_count)} candidates
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {formatCoveragePercent(coverage?.price_coverage_ratio)}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase text-muted-foreground">Missing</div>
              <div className="mt-1 font-medium">{formatInteger(coverage?.price_missing_count)}</div>
              {coverage?.price_backfill_required ? (
                <Badge variant="warning" className="mt-2 rounded-md">
                  Backfill needed
                </Badge>
              ) : (
                <Badge variant="secondary" className="mt-2 rounded-md">
                  No price backfill flag
                </Badge>
              )}
            </div>
          </div>
          {coverage?.price_backfill_hint ? (
            <div className="mt-4 rounded-md border border-border/70 bg-muted/40 px-3 py-2 font-mono text-xs text-muted-foreground">
              {coverage.price_backfill_hint}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <SlidersHorizontal className="h-4 w-4" />
            Filters
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Narrow the research candidates without treating the ranking as a buy signal.
          </p>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-[1.2fr_1fr_1fr_1.2fr_1.2fr_auto] md:items-end">
            <div>
              <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="period-filter">
                Period
              </label>
              {periodOptions.length ? (
                <Select
                  value={filters.period || '__latest'}
                  onValueChange={(value) =>
                    setFilters((current) => ({
                      ...current,
                      period: value === '__latest' ? '' : value,
                    }))
                  }
                >
                  <SelectTrigger id="period-filter" className="mt-2">
                    <SelectValue placeholder="Latest complete" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__latest">Latest complete</SelectItem>
                    {periodOptions.map((periodOption) => (
                      <SelectItem key={periodOption.label} value={periodOption.label}>
                        {periodOption.label}
                        {periodOption.is_latest_complete ? ' · latest complete' : ''}
                        {periodOption.manager_count ? ` · ${periodOption.manager_count} managers` : ''}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  id="period-filter"
                  className="mt-2"
                  placeholder={payload?.latest_complete_period ?? 'YYYY-Qn'}
                  value={filters.period}
                  onChange={(event) =>
                    setFilters((current) => ({ ...current, period: event.target.value }))
                  }
                />
              )}
            </div>
            <div>
              <label
                className="text-xs font-semibold uppercase text-muted-foreground"
                htmlFor="min-holders-filter"
              >
                Min holders
              </label>
              <Input
                id="min-holders-filter"
                className="mt-2"
                type="number"
                min="1"
                max="50"
                value={filters.minHolders}
                onChange={(event) =>
                  setFilters((current) => ({ ...current, minHolders: event.target.value }))
                }
              />
            </div>
            <div>
              <label
                className="text-xs font-semibold uppercase text-muted-foreground"
                htmlFor="min-signal-filter"
              >
                Min signal
              </label>
              <Input
                id="min-signal-filter"
                className="mt-2"
                type="number"
                min="0"
                step="0.1"
                placeholder="Any"
                value={filters.minSignalScore}
                onChange={(event) =>
                  setFilters((current) => ({ ...current, minSignalScore: event.target.value }))
                }
              />
            </div>
            <label className="flex items-center gap-3 rounded-md border border-border/70 px-3 py-2 text-sm">
              <Checkbox
                checked={filters.superinvestorOnly}
                onCheckedChange={(checked) =>
                  setFilters((current) => ({ ...current, superinvestorOnly: Boolean(checked) }))
                }
              />
              <span>
                <span className="block font-medium">Superinvestors only</span>
                <span className="text-xs text-muted-foreground">Noise filter</span>
              </span>
            </label>
            <div>
              <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="sort-filter">
                Sort
              </label>
              <Select
                value={filters.sort}
                onValueChange={(value) =>
                  setFilters((current) => ({ ...current, sort: value }))
                }
              >
                <SelectTrigger id="sort-filter" className="mt-2">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="signal_weighted_consensus">Signal score</SelectItem>
                  <SelectItem value="conviction">Conviction</SelectItem>
                  <SelectItem value="distinctive_consensus">Distinctive consensus</SelectItem>
                  <SelectItem value="add_intensity">Add intensity</SelectItem>
                  <SelectItem value="aggregate_weight">Aggregate weight</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                setFilters({
                  period: '',
                  minHolders: '3',
                  minSignalScore: '',
                  superinvestorOnly: true,
                  sort: 'signal_weighted_consensus',
                })
              }
            >
              Reset
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Smart Money Clusters</CardTitle>
          <p className="text-sm text-muted-foreground">
            Compact ownership-signal view. Bubble size reflects aggregate reported weight; tone
            reflects add/reduce context.
          </p>
        </CardHeader>
        <CardContent>
          {bubbles.length ? (
            <div className="flex flex-wrap items-end gap-4">
              {bubbles.map((bubble) => (
                <div key={bubble.stockId} className="group relative">
                  <Button
                    type="button"
                    variant="outline"
                    className={`${RADAR_SIZE_CLASSES[bubble.sizeClass] ?? RADAR_SIZE_CLASSES['h-14 w-14']} ${
                      RADAR_TONE_CLASSES[bubble.toneClass] ?? RADAR_TONE_CLASSES['border-slate-300 bg-slate-50 text-slate-950']
                    } flex-col rounded-full border text-center shadow-none hover:bg-muted/60`}
                    title={`${bubble.ticker}: ${bubble.holderActionLabel}`}
                    onClick={() => setSelectedStockId(bubble.stockId)}
                  >
                    <span className="text-xs font-semibold">{bubble.ticker}</span>
                    <span className="text-[10px] text-current/70">{bubble.aggregateWeightLabel}</span>
                  </Button>
                  <div className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 hidden w-56 -translate-x-1/2 rounded-md border border-border bg-popover p-3 text-xs text-popover-foreground shadow-md group-focus-within:block group-hover:block">
                    <div className="font-semibold">{bubble.companyName}</div>
                    <div className="mt-1 text-muted-foreground">{bubble.holderActionLabel}</div>
                    <div className="mt-1 text-muted-foreground">
                      Signal {bubble.signalScoreLabel} · {bubble.confidence} confidence
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              No ownership-signal clusters are available for the current filters.
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="rounded-md">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Search className="h-4 w-4" />
            Signal-Ranked Candidates
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Signal Score is the primary rank. Conviction, streak, holder count, and caution
            flags are supporting context.
          </p>
        </CardHeader>
        <CardContent className="p-0">
          {dashboardQuery.isLoading ? (
            <div className="p-6 text-sm text-muted-foreground">Loading 13F signals…</div>
          ) : rows.length === 0 ? (
            <div className="flex gap-2 p-6 text-sm text-muted-foreground">
              <Info className="h-4 w-4" />
              No signal-ranked candidates are available for the selected coverage rules.
            </div>
          ) : (
            <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Company</TableHead>
                  <TableHead className="text-right">Signal Score</TableHead>
                  <TableHead>Why It Appears</TableHead>
                  <TableHead>Quality</TableHead>
                  <TableHead>Valuation Ref.</TableHead>
                  <TableHead>Context</TableHead>
                  <TableHead>Caution</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.stockId}>
                    <TableCell>
                      <div className="font-semibold">{row.ticker}</div>
                      <div className="mt-1 text-xs text-muted-foreground">{row.companyName}</div>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="mt-3"
                        onClick={() => setSelectedStockId(row.stockId)}
                      >
                        <PanelRightOpen className="h-3.5 w-3.5" />
                        Review
                      </Button>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="text-xl font-semibold tabular-nums">{row.signalScoreLabel}</div>
                      <Badge variant={row.confidenceTone} className="mt-2">
                        {row.confidence} confidence
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1.5">
                        {row.reasonChips.map((reason) => (
                          <Badge key={reason} variant="outline" className="rounded-md">
                            {reason}
                          </Badge>
                        ))}
                      </div>
                      <div className="mt-2 text-xs text-muted-foreground">
                        Manager signal coverage: {row.unknownCoverageLabel}
                      </div>
                    </TableCell>
                    <TableCell>
                      {row.quality.hasValueLineQuality ? (
                        <div className="space-y-1 text-sm">
                          <div className="tabular-nums">
                            F-Score {row.quality.piotroskiLabel} · ROTC{' '}
                            {row.quality.returnOnCapitalLabel}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            NPM {row.quality.netMarginLabel} · Debt/Cap{' '}
                            {row.quality.debtToCapitalLabel}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            Owner yield {row.quality.ownerEarningsYieldLabel}
                          </div>
                        </div>
                      ) : (
                        <div className="text-sm text-muted-foreground">No quality facts</div>
                      )}
                      <div className="mt-2">
                        <Badge variant="outline" className="rounded-md">
                          {row.quality.qualityCoverageLabel}
                        </Badge>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="space-y-1 text-sm">
                        <div className="tabular-nums">
                          Price {row.valuation.currentPriceLabel} · Ref{' '}
                          {row.valuation.referenceLabel}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          Discount to ref {row.valuation.discountLabel}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {row.valuation.priceContextLabel} · {row.valuation.currentPriceDateLabel}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          Holder estimate {row.valuation.holderRangeLabel}
                        </div>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <Badge variant="outline" className="rounded-md">
                          {row.valuation.referenceConfidence}
                        </Badge>
                        {row.valuation.belowSelectedReference ? (
                          <Badge variant="success" className="rounded-md">
                            Below selected reference
                          </Badge>
                        ) : null}
                      </div>
                      <div className="mt-2 text-xs text-muted-foreground">
                        {row.valuation.referenceSourceLabel}
                      </div>
                      {row.valuation.unavailableReasons.length ? (
                        <div className="mt-1 text-xs text-muted-foreground">
                          {row.valuation.unavailableReasons[0]}
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <div className="text-sm">{row.convictionLabel} conviction</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {row.holdingStreakLabel} · {row.rawHoldersLabel} holders
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">{row.addReduceLabel}</div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1.5">
                        {row.cautionFlags.length ? (
                          row.cautionFlags.map((flag) => (
                            <Badge key={flag.key} variant={cautionTone(flag)} className="rounded-md">
                              {flag.label ?? flag.key}
                            </Badge>
                          ))
                        ) : (
                          <Badge variant="secondary" className="rounded-md">
                            No primary caution
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {selectedRow ? (
        <div className="fixed inset-0 z-50 flex justify-end bg-background/60 backdrop-blur-sm">
          <div
            aria-hidden="true"
            className="absolute inset-0 cursor-default"
            onClick={() => setSelectedStockId(null)}
          />
          <Card className="relative h-full w-full max-w-[460px] overflow-hidden rounded-none border-y-0 border-r-0 shadow-xl">
            <CardHeader className="border-b border-border/70 pb-3">
              <CardTitle className="flex items-center justify-between gap-2 text-base">
                <span>Candidate Review</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label="Close candidate review"
                  onClick={() => setSelectedStockId(null)}
                >
                  <X className="h-4 w-4" />
                </Button>
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                {selectedRow.ticker} · {selectedRow.companyName}
              </p>
            </CardHeader>
            <CardContent className="h-[calc(100%-84px)] space-y-5 overflow-y-auto p-5">
              <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
                Review the counter-evidence before treating this 13F signal as a research candidate.
              </div>

              <div className="space-y-3">
                {selectedRow.cautionGroups.length ? (
                  selectedRow.cautionGroups.map((group) => (
                    <div key={group.group}>
                      <div className="text-xs font-semibold uppercase text-muted-foreground">
                        {group.label}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {group.flags.map((flag) => (
                          <Badge key={flag.key} variant={cautionTone(flag)} className="rounded-md">
                            {flag.label ?? flag.key}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-sm text-muted-foreground">
                    No primary caution flags are currently attached to this signal.
                  </div>
                )}
              </div>

              <div>
                <div className="text-xs font-semibold uppercase text-muted-foreground">
                  Missing or weak data
                </div>
                <div className="mt-2 space-y-1 text-sm text-muted-foreground">
                  {selectedMissingReasons.length ? (
                    selectedMissingReasons.map((reason) => <div key={reason.key}>{reason.label}</div>)
                  ) : (
                    <div>No quality or valuation gaps surfaced for the current row.</div>
                  )}
                </div>
              </div>

              <div>
                <div className="text-xs font-semibold uppercase text-muted-foreground">
                  Value Line provenance
                </div>
                {selectedRow.quality.primarySourceDocumentId ? (
                  <div className="mt-2 space-y-3">
                    <Button asChild variant="outline" size="sm">
                      <Link href={`/documents/${selectedRow.quality.primarySourceDocumentId}/review`}>
                        <FileText className="h-3.5 w-3.5" />
                        Open source report
                      </Link>
                    </Button>
                    <div className="space-y-1 text-xs text-muted-foreground">
                      {selectedRow.quality.provenanceFacts.slice(0, 6).map((fact) => (
                        <div
                          key={`${fact.metric_key}:${fact.source_document_id ?? 'none'}:${fact.period_end_date ?? 'none'}`}
                          className="flex items-center justify-between gap-3 rounded-md border border-border/70 px-2 py-1.5"
                        >
                          <span>{fact.label?.replaceAll('_', ' ') ?? fact.metric_key}</span>
                          <span className="font-mono">
                            doc {fact.source_document_id ?? '—'} · {fact.period_end_date ?? '—'}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="mt-2 text-sm text-muted-foreground">
                    No source document is linked to the current quality facts.
                  </div>
                )}
              </div>

              <div>
                <div className="text-xs font-semibold uppercase text-muted-foreground">
                  Top holders
                </div>
                <div className="mt-2 space-y-2">
                  {selectedRow.topHolders.slice(0, 3).map((holder) => (
                    <div key={holder.manager_id} className="rounded-md border border-border/70 p-2 text-sm">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="font-medium">{holder.manager_name}</div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            Rank {holder.position_rank ?? '—'} · {holder.action} ·{' '}
                            {holder.holding_streak_quarters ?? '—'}Q streak
                          </div>
                        </div>
                        <Badge variant="outline" className="rounded-md">
                          {formatPercentValue(holder.position_weight)}
                        </Badge>
                      </div>
                      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                        <div>
                          <div className="uppercase">Shares</div>
                          <div className="mt-1 text-foreground">
                            {formatInteger(holder.current_shares)}
                          </div>
                        </div>
                        <div>
                          <div className="uppercase">Previous</div>
                          <div className="mt-1 text-foreground">
                            {formatInteger(holder.previous_shares)}
                          </div>
                        </div>
                        <div>
                          <div className="uppercase">Share delta</div>
                          <div className="mt-1 text-foreground">
                            {formatPercentValue(holder.share_delta_pct)}
                          </div>
                        </div>
                        <div>
                          <div className="uppercase">Holder estimate</div>
                          <div className="mt-1 text-foreground">
                            {formatCurrency(holder.holder_price_estimate)}
                          </div>
                        </div>
                        <div>
                          <div className="uppercase">Filed</div>
                          <div className="mt-1 text-foreground">{holder.filing_date ?? '—'}</div>
                        </div>
                        <div>
                          <div className="uppercase">Signal weight</div>
                          <div className="mt-1 text-foreground">
                            {formatPercentValue(holder.manager_signal_weight, 0)}
                          </div>
                        </div>
                        <div>
                          <div className="uppercase">Manager type</div>
                          <div className="mt-1 text-foreground">
                            {holder.manager_type?.replaceAll('_', ' ') ?? 'unknown'}
                          </div>
                        </div>
                        <div>
                          <div className="uppercase">Portfolio concentration</div>
                          <div className="mt-1 text-foreground">
                            {formatPercentValue(holder.portfolio_concentration)}
                          </div>
                        </div>
                        <div>
                          <div className="uppercase">Avg holding period</div>
                          <div className="mt-1 text-foreground">
                            {holder.average_holding_period_quarters ?? '—'}Q
                          </div>
                        </div>
                      </div>
                      <div className="mt-2 truncate font-mono text-[11px] text-muted-foreground">
                        {holder.manager_profile_source ?? 'unknown profile'} ·{' '}
                        {holder.accession_no ?? 'No accession'}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <div className="text-xs font-semibold uppercase text-muted-foreground">
                  Suggested next steps
                </div>
                <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
                  {researchSteps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
