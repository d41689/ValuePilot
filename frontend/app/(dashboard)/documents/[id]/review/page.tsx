'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, Check, Edit3, Loader2, X } from 'lucide-react';

import apiClient from '@/lib/api/client';
import documentReviewHelpers from '@/lib/documentReview';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { useToast } from '@/components/ui/use-toast';

type ReviewLineage = {
  extraction_id: number;
  document_id: number;
  page_number: number | null;
  original_text_snippet: string | null;
};

type ReviewItem = {
  metric_key: string;
  label: string;
  fact_id: number;
  stock_ticker: string | null;
  display_value: string | null;
  value_numeric: number | null;
  value_text: string | null;
  unit: string | null;
  period: string | null;
  period_type: string | null;
  period_end_date: string | null;
  as_of_date: string | null;
  source_type: string;
  is_current: boolean;
  lineage_available: boolean;
  lineage: ReviewLineage | null;
  editable: boolean;
  valueLabel?: string;
  meta?: string | null;
  evidenceLabel?: string;
};

type ReviewGroup = {
  key: string;
  label: string;
  items: ReviewItem[];
};

type ReviewPayload = {
  document: {
    id: number;
    file_name: string;
    ticker: string | null;
    company_name: string | null;
    report_date: string | null;
  };
  groups: ReviewGroup[];
};

type ReviewTable = {
  columns: Array<{ key: string; label: string }>;
  rows: Array<{
    key: string;
    label: string;
    metric_key: string;
    cells: Array<ReviewItem | null>;
  }>;
};

type ReviewReportModel = {
  sections: ReviewGroup[];
  headerMetrics: ReviewItem[];
  ratingMetrics: ReviewItem[];
  qualityMetrics: ReviewItem[];
  targetMetrics: ReviewItem[];
  annualTable: ReviewTable;
  quarterlyTable: ReviewTable;
  narrativeItems: ReviewItem[];
  institutionalItems: ReviewItem[];
  capitalItems: ReviewItem[];
  rateItems: ReviewItem[];
  leftoverSections: ReviewGroup[];
  displayedFactIds: Set<number>;
};

type ApiError = {
  response?: {
    data?: {
      detail?: string | { value?: string };
    };
  };
  message?: string;
};

const { buildDocumentReviewReportModel, findDocumentReviewItemByFactId } = documentReviewHelpers;

function getErrorMessage(error: unknown, fallback: string) {
  if (typeof error === 'object' && error !== null) {
    const apiError = error as ApiError;
    const detail = apiError.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (detail?.value) return detail.value;
    return apiError.message ?? fallback;
  }
  return fallback;
}

function formatDateOnly(iso: string | null) {
  if (!iso) return '—';
  const dt = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleDateString();
}

function formatEvidenceValue(item: ReviewItem | null) {
  if (!item) return '—';
  if (item.value_numeric === null || item.value_numeric === undefined) {
    return item.unit ? `— ${item.unit}` : '—';
  }
  return `${item.value_numeric}${item.unit ? ` ${item.unit}` : ''}`;
}

function ReviewMetricButton({
  item,
  selected,
  onSelect,
  emphasis = 'default',
}: {
  item: ReviewItem;
  selected: boolean;
  onSelect: (item: ReviewItem) => void;
  emphasis?: 'default' | 'hero';
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(item)}
      className={cn(
        'w-full rounded-lg border px-3 py-3 text-left transition-colors',
        emphasis === 'hero' ? 'min-h-[88px]' : 'min-h-[72px]',
        selected
          ? 'border-slate-900 bg-slate-900 text-white shadow-sm'
          : 'border-border/60 bg-background/85 text-foreground hover:border-slate-400 hover:bg-muted/40'
      )}
    >
      <div
        className={cn(
          'text-[11px] uppercase tracking-[0.16em]',
          selected ? 'text-slate-200' : 'text-muted-foreground'
        )}
      >
        {item.label}
      </div>
      <div
        className={cn(
          'mt-2 break-words font-semibold tracking-tight',
          emphasis === 'hero' ? 'text-2xl' : 'text-base',
          selected ? 'text-white' : 'text-foreground'
        )}
      >
        {item.valueLabel}
      </div>
      {item.meta ? (
        <div className={cn('mt-1 text-[11px]', selected ? 'text-slate-300' : 'text-muted-foreground')}>
          {item.meta}
        </div>
      ) : null}
    </button>
  );
}

function ReviewMetricGroup({
  title,
  items,
  selectedFactId,
  onSelect,
  columns = 2,
}: {
  title: string;
  items: ReviewItem[];
  selectedFactId: number | null;
  onSelect: (item: ReviewItem) => void;
  columns?: 1 | 2;
}) {
  if (items.length === 0) {
    return null;
  }

  return (
    <section className="rounded-xl border border-border/60 bg-card/90 p-4">
      <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        {title}
      </div>
      <div className={cn('grid gap-2', columns === 1 ? 'grid-cols-1' : 'grid-cols-2')}>
        {items.map((item) => (
          <ReviewMetricButton
            key={item.fact_id}
            item={item}
            selected={selectedFactId === item.fact_id}
            onSelect={onSelect}
          />
        ))}
      </div>
    </section>
  );
}

function ReviewTableSection({
  title,
  table,
  selectedFactId,
  onSelect,
}: {
  title: string;
  table: ReviewTable;
  selectedFactId: number | null;
  onSelect: (item: ReviewItem) => void;
}) {
  if (table.columns.length === 0 || table.rows.length === 0) {
    return null;
  }

  return (
    <section className="rounded-xl border border-border/60 bg-card/90 p-4">
      <div className="mb-3 flex items-end justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            {title}
          </div>
          <div className="mt-1 text-sm text-muted-foreground">
            Tap a cell to inspect lineage and correct the value.
          </div>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] border-separate border-spacing-0 text-sm">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-card/95 px-3 py-2 text-left text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                Metric
              </th>
              {table.columns.map((column) => (
                <th
                  key={column.key}
                  className="border-b border-border/60 px-3 py-2 text-right text-[11px] uppercase tracking-[0.16em] text-muted-foreground"
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row) => (
              <tr key={row.key}>
                <th className="sticky left-0 z-10 border-b border-border/50 bg-card/95 px-3 py-3 text-left font-medium text-foreground">
                  {row.label}
                </th>
                {row.cells.map((cell, index) => (
                  <td key={`${row.key}-${table.columns[index]?.key ?? index}`} className="border-b border-border/50 px-1 py-1.5">
                    {cell ? (
                      <button
                        type="button"
                        onClick={() => onSelect(cell)}
                        className={cn(
                          'w-full rounded-md px-2 py-2 text-right transition-colors',
                          selectedFactId === cell.fact_id
                            ? 'bg-slate-900 text-white'
                            : 'bg-background/70 text-foreground hover:bg-muted/40'
                        )}
                      >
                        <div className="font-medium">{cell.valueLabel}</div>
                        <div
                          className={cn(
                            'mt-1 text-[11px]',
                            selectedFactId === cell.fact_id ? 'text-slate-300' : 'text-muted-foreground'
                          )}
                        >
                          {cell.evidenceLabel}
                        </div>
                      </button>
                    ) : (
                      <div className="px-2 py-2 text-right text-muted-foreground">—</div>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function DocumentReviewPage() {
  const params = useParams<{ id: string }>();
  const documentId = params?.id ?? '';
  const { toast } = useToast();
  const [selectedFactId, setSelectedFactId] = useState<number | null>(null);
  const [editingFactId, setEditingFactId] = useState<number | null>(null);
  const [correctionValue, setCorrectionValue] = useState('');
  const [correctionNote, setCorrectionNote] = useState('');

  const reviewQuery = useQuery({
    queryKey: ['document-review', documentId],
    enabled: documentId.length > 0,
    queryFn: async () => {
      const res = await apiClient.get(`/documents/${documentId}/review`);
      return res.data as ReviewPayload;
    },
  });

  const report = useMemo(
    () => buildDocumentReviewReportModel(reviewQuery.data?.groups ?? []) as ReviewReportModel,
    [reviewQuery.data?.groups]
  );

  const fallbackSelectedFactId = report.sections[0]?.items[0]?.fact_id ?? null;
  const effectiveSelectedFactId = selectedFactId ?? fallbackSelectedFactId;
  const selectedItem = useMemo(
    () =>
      effectiveSelectedFactId === null
        ? null
        : (findDocumentReviewItemByFactId(report, effectiveSelectedFactId) as ReviewItem | null),
    [effectiveSelectedFactId, report]
  );

  const correctionMutation = useMutation({
    mutationFn: async ({ factId, value, note }: { factId: number; value: string; note: string }) => {
      const res = await apiClient.post(`/documents/${documentId}/review/facts/${factId}/corrections`, {
        value,
        note: note || undefined,
      });
      return res.data as { fact_id: number };
    },
    onSuccess: (payload) => {
      setEditingFactId(null);
      setCorrectionValue('');
      setCorrectionNote('');
      setSelectedFactId(payload.fact_id);
      reviewQuery.refetch();
      toast({
        title: 'Correction saved',
        description: 'A manual current fact was created for this value.',
      });
    },
    onError: (error: unknown) => {
      toast({
        title: 'Correction failed',
        description: getErrorMessage(error, 'Unable to save correction.'),
        variant: 'destructive',
      });
    },
  });

  const handleSelectItem = (item: ReviewItem) => {
    setSelectedFactId(item.fact_id);
    if (editingFactId !== item.fact_id) {
      setEditingFactId(null);
      setCorrectionValue('');
      setCorrectionNote('');
    }
  };

  const startEdit = (item: ReviewItem) => {
    setSelectedFactId(item.fact_id);
    setEditingFactId(item.fact_id);
    setCorrectionValue(item.display_value ?? item.value_text ?? String(item.value_numeric ?? ''));
    setCorrectionNote('');
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-500">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <Button asChild variant="ghost" size="sm" className="px-0">
            <Link href="/documents">
              <ArrowLeft className="h-4 w-4" />
              Documents
            </Link>
          </Button>
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">Report Review</h1>
            <p className="text-sm text-muted-foreground">
              {reviewQuery.data
                ? `${reviewQuery.data.document.file_name} · ${reviewQuery.data.document.ticker ?? 'Unlinked'} · ${formatDateOnly(reviewQuery.data.document.report_date)}`
                : 'Loading document review data...'}
            </p>
          </div>
        </div>
        {reviewQuery.data?.document.company_name ? (
          <Badge variant="secondary">{reviewQuery.data.document.company_name}</Badge>
        ) : null}
      </div>

      {reviewQuery.isLoading ? (
        <Card className="border-border/60 bg-card/85">
          <CardContent className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading review data...
          </CardContent>
        </Card>
      ) : reviewQuery.error ? (
        <Card className="border-rose-200 bg-rose-50/70">
          <CardContent className="p-6 text-sm text-rose-800">
            {getErrorMessage(reviewQuery.error, 'Failed to load document review.')}
          </CardContent>
        </Card>
      ) : report.sections.length === 0 ? (
        <Card className="border-border/60 bg-card/85">
          <CardContent className="p-6 text-sm text-muted-foreground">
            No fact-backed review data is available for this document.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="space-y-4">
            <section className="rounded-2xl border border-border/60 bg-card/95 p-5 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/60 pb-4">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                    Value Line Review Sheet
                  </div>
                  <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight text-foreground">
                    {reviewQuery.data?.document.company_name ?? reviewQuery.data?.document.file_name}
                  </h2>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                    <span>{reviewQuery.data?.document.ticker ?? 'Unlinked'}</span>
                    <span>{formatDateOnly(reviewQuery.data?.document.report_date ?? null)}</span>
                    <span>{reviewQuery.data?.document.file_name}</span>
                  </div>
                </div>
                <div className="rounded-xl border border-border/60 bg-background/80 px-4 py-3 text-right">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                    Active Fields
                  </div>
                  <div className="mt-1 text-2xl font-semibold tracking-tight text-foreground">
                    {report.displayedFactIds.size}
                  </div>
                </div>
              </div>

              <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {report.headerMetrics.map((item, index) => (
                  <ReviewMetricButton
                    key={item.fact_id}
                    item={item}
                    selected={effectiveSelectedFactId === item.fact_id}
                    onSelect={handleSelectItem}
                    emphasis={index === 0 ? 'hero' : 'default'}
                  />
                ))}
              </div>

              <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_320px]">
                <div className="space-y-4">
                  <ReviewTableSection
                    title="Annual Financials"
                    table={report.annualTable}
                    selectedFactId={effectiveSelectedFactId}
                    onSelect={handleSelectItem}
                  />
                  <ReviewTableSection
                    title="Quarterly Snapshot"
                    table={report.quarterlyTable}
                    selectedFactId={effectiveSelectedFactId}
                    onSelect={handleSelectItem}
                  />

                  {report.narrativeItems.length > 0 ? (
                    <section className="rounded-xl border border-border/60 bg-card/90 p-4">
                      <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        Narrative
                      </div>
                      <div className="grid gap-3 lg:grid-cols-2">
                        {report.narrativeItems.map((item) => (
                          <button
                            key={item.fact_id}
                            type="button"
                            onClick={() => handleSelectItem(item)}
                            className={cn(
                              'rounded-lg border p-4 text-left transition-colors',
                              effectiveSelectedFactId === item.fact_id
                                ? 'border-slate-900 bg-slate-900 text-white'
                                : 'border-border/60 bg-background/85 hover:bg-muted/40'
                            )}
                          >
                            <div
                              className={cn(
                                'text-[11px] uppercase tracking-[0.16em]',
                                effectiveSelectedFactId === item.fact_id
                                  ? 'text-slate-300'
                                  : 'text-muted-foreground'
                              )}
                            >
                              {item.label}
                            </div>
                            <div className="mt-2 line-clamp-6 text-sm leading-6">
                              {item.valueLabel}
                            </div>
                          </button>
                        ))}
                      </div>
                    </section>
                  ) : null}
                </div>

                <div className="space-y-4">
                  <ReviewMetricGroup
                    title="Ratings"
                    items={report.ratingMetrics}
                    selectedFactId={effectiveSelectedFactId}
                    onSelect={handleSelectItem}
                  />
                  <ReviewMetricGroup
                    title="Quality"
                    items={report.qualityMetrics}
                    selectedFactId={effectiveSelectedFactId}
                    onSelect={handleSelectItem}
                  />
                  <ReviewMetricGroup
                    title="Targets & Projection"
                    items={report.targetMetrics}
                    selectedFactId={effectiveSelectedFactId}
                    onSelect={handleSelectItem}
                  />
                  <ReviewMetricGroup
                    title="Capital Structure"
                    items={report.capitalItems}
                    selectedFactId={effectiveSelectedFactId}
                    onSelect={handleSelectItem}
                    columns={1}
                  />
                  <ReviewMetricGroup
                    title="Annual Rates"
                    items={report.rateItems}
                    selectedFactId={effectiveSelectedFactId}
                    onSelect={handleSelectItem}
                    columns={1}
                  />
                  <ReviewMetricGroup
                    title="Institutional Decisions"
                    items={report.institutionalItems}
                    selectedFactId={effectiveSelectedFactId}
                    onSelect={handleSelectItem}
                    columns={1}
                  />
                  {report.leftoverSections.map((section) => (
                    <ReviewMetricGroup
                      key={section.key}
                      title={section.label}
                      items={section.items}
                      selectedFactId={effectiveSelectedFactId}
                      onSelect={handleSelectItem}
                      columns={1}
                    />
                  ))}
                </div>
              </div>
            </section>
          </div>

          <div className="space-y-4 xl:sticky xl:top-6 xl:self-start">
            <Card className="border-border/60 bg-card/95">
              <CardHeader>
                <CardTitle>Evidence Panel</CardTitle>
                <CardDescription>
                  Review one field at a time. Corrections still write a new manual current fact.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {selectedItem ? (
                  <>
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={selectedItem.is_current ? 'success' : 'secondary'}>
                          {selectedItem.is_current ? 'Current' : 'Historical'}
                        </Badge>
                        {selectedItem.source_type === 'manual' ? (
                          <Badge variant="warning">Manual</Badge>
                        ) : null}
                        <Badge variant="outline">{selectedItem.evidenceLabel ?? 'No lineage'}</Badge>
                      </div>
                      <div>
                        <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                          {selectedItem.label}
                        </div>
                        <div className="mt-1 text-2xl font-semibold tracking-tight text-foreground">
                          {selectedItem.valueLabel}
                        </div>
                        <div className="mt-2 text-xs text-muted-foreground">
                          {selectedItem.metric_key}
                        </div>
                      </div>
                    </div>

                    <div className="grid gap-3 rounded-xl border border-border/60 bg-background/70 p-4 text-sm">
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                          Period
                        </div>
                        <div className="mt-1 text-foreground">
                          {selectedItem.period_type ?? '—'}
                          {selectedItem.period_end_date
                            ? ` · ${formatDateOnly(selectedItem.period_end_date)}`
                            : selectedItem.as_of_date
                              ? ` · ${formatDateOnly(selectedItem.as_of_date)}`
                              : ''}
                        </div>
                      </div>
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                          Normalized
                        </div>
                        <div className="mt-1 text-foreground">{formatEvidenceValue(selectedItem)}</div>
                      </div>
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                          Source
                        </div>
                        <div className="mt-1 text-foreground">{selectedItem.source_type}</div>
                      </div>
                    </div>

                    <div>
                      <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                        Source Snippet
                      </div>
                      <div className="mt-2 whitespace-pre-wrap rounded-xl border border-border/60 bg-muted/20 p-4 text-sm leading-6 text-foreground">
                        {selectedItem.lineage?.original_text_snippet || 'No source snippet available.'}
                      </div>
                    </div>

                    <div>
                      <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                        Document Linkage
                      </div>
                      <div className="mt-2 rounded-xl border border-border/60 bg-background/70 p-4 text-sm text-foreground">
                        <div>Document #{reviewQuery.data?.document.id ?? '—'}</div>
                        <div className="mt-1">
                          Page {selectedItem.lineage?.page_number ?? '—'} · Extraction{' '}
                          {selectedItem.lineage?.extraction_id ?? '—'}
                        </div>
                      </div>
                    </div>

                    {selectedItem.editable ? (
                      editingFactId === selectedItem.fact_id ? (
                        <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
                          <div className="grid gap-3">
                            <label className="space-y-1 text-xs text-muted-foreground">
                              Corrected value
                              <input
                                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground"
                                value={correctionValue}
                                onChange={(event) => setCorrectionValue(event.target.value)}
                              />
                            </label>
                            <label className="space-y-1 text-xs text-muted-foreground">
                              Note
                              <input
                                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground"
                                value={correctionNote}
                                onChange={(event) => setCorrectionNote(event.target.value)}
                              />
                            </label>
                          </div>
                          <div className="mt-3 flex flex-wrap justify-end gap-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                setEditingFactId(null);
                                setCorrectionValue('');
                                setCorrectionNote('');
                              }}
                            >
                              <X className="h-3 w-3" />
                              Cancel
                            </Button>
                            <Button
                              size="sm"
                              disabled={correctionMutation.isPending || correctionValue.trim().length === 0}
                              onClick={() =>
                                correctionMutation.mutate({
                                  factId: selectedItem.fact_id,
                                  value: correctionValue,
                                  note: correctionNote,
                                })
                              }
                            >
                              {correctionMutation.isPending ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <Check className="h-3 w-3" />
                              )}
                              Save Correction
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <Button variant="outline" size="sm" onClick={() => startEdit(selectedItem)}>
                          <Edit3 className="h-3 w-3" />
                          Correct Selected Value
                        </Button>
                      )
                    ) : null}
                  </>
                ) : (
                  <div className="rounded-xl border border-dashed border-border/60 bg-background/60 p-4 text-sm text-muted-foreground">
                    Select a field from the report to inspect its lineage and make a correction.
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
