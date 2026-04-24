'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, Check, Edit3, FileText, Loader2, X } from 'lucide-react';

import apiClient from '@/lib/api/client';
import documentReviewHelpers from '@/lib/documentReview';
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

type ApiError = {
  response?: {
    data?: {
      detail?: string | { value?: string };
    };
  };
  message?: string;
};

const { buildDocumentReviewSections } = documentReviewHelpers;

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

export default function DocumentReviewPage() {
  const params = useParams<{ id: string }>();
  const documentId = params?.id ?? '';
  const { toast } = useToast();
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

  const rawTextQuery = useQuery({
    queryKey: ['document-review-raw-text', documentId],
    enabled: documentId.length > 0,
    queryFn: async () => {
      const res = await apiClient.get(`/documents/${documentId}/raw_text`);
      return (res.data?.raw_text || '') as string;
    },
  });

  const correctionMutation = useMutation({
    mutationFn: async ({ factId, value, note }: { factId: number; value: string; note: string }) => {
      const res = await apiClient.post(
        `/documents/${documentId}/review/facts/${factId}/corrections`,
        {
          value,
          note: note || undefined,
        }
      );
      return res.data;
    },
    onSuccess: () => {
      setEditingFactId(null);
      setCorrectionValue('');
      setCorrectionNote('');
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

  const sections = useMemo(
    () => buildDocumentReviewSections(reviewQuery.data?.groups ?? []) as ReviewGroup[],
    [reviewQuery.data?.groups]
  );

  const startEdit = (item: ReviewItem) => {
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
            <h1 className="font-display text-3xl font-semibold tracking-tight">
              Extracted Data Review
            </h1>
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
      ) : sections.length === 0 ? (
        <Card className="border-border/60 bg-card/85">
          <CardContent className="p-6 text-sm text-muted-foreground">
            No fact-backed review data is available for this document.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="space-y-5">
            {sections.map((section) => (
              <Card key={section.key} className="border-border/60 bg-card/85">
                <CardHeader>
                  <CardTitle>{section.label}</CardTitle>
                  <CardDescription>{section.items.length} reviewed fields</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  {section.items.map((item) => {
                    const isEditing = editingFactId === item.fact_id;
                    return (
                      <div
                        key={item.fact_id}
                        className="rounded-lg border border-border/60 bg-background/80 p-4"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <div className="text-sm font-semibold text-foreground">
                                {item.label}
                              </div>
                              <Badge variant={item.is_current ? 'success' : 'secondary'}>
                                {item.is_current ? 'Current' : 'Historical'}
                              </Badge>
                              {item.source_type === 'manual' ? (
                                <Badge variant="warning">Manual</Badge>
                              ) : null}
                            </div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              {item.metric_key}
                              {item.meta ? ` · ${item.meta}` : ''}
                            </div>
                          </div>
                          {item.editable ? (
                            <Button variant="outline" size="sm" onClick={() => startEdit(item)}>
                              <Edit3 className="h-3 w-3" />
                              Edit
                            </Button>
                          ) : null}
                        </div>

                        <div className="mt-3 grid gap-3 md:grid-cols-[220px_minmax(0,1fr)]">
                          <div>
                            <div className="text-xs uppercase text-muted-foreground">Parsed</div>
                            <div className="mt-1 break-words text-sm font-medium text-foreground">
                              {item.valueLabel}
                            </div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              Normalized:{' '}
                              {item.value_numeric === null ? '—' : item.value_numeric}
                              {item.unit ? ` ${item.unit}` : ''}
                            </div>
                          </div>
                          <div>
                            <div className="flex items-center gap-2 text-xs uppercase text-muted-foreground">
                              <FileText className="h-3 w-3" />
                              Evidence {item.evidenceLabel ? `· ${item.evidenceLabel}` : ''}
                            </div>
                            <div className="mt-1 whitespace-pre-wrap break-words rounded-md bg-muted/40 p-3 text-xs text-foreground">
                              {item.lineage?.original_text_snippet || 'No source snippet available.'}
                            </div>
                          </div>
                        </div>

                        {isEditing ? (
                          <div className="mt-4 rounded-md border border-border/60 bg-muted/20 p-3">
                            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                              <label className="space-y-1 text-xs text-muted-foreground">
                                Corrected value
                                <input
                                  className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground"
                                  value={correctionValue}
                                  onChange={(event) => setCorrectionValue(event.target.value)}
                                />
                              </label>
                              <label className="space-y-1 text-xs text-muted-foreground">
                                Note
                                <input
                                  className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground"
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
                                disabled={
                                  correctionMutation.isPending ||
                                  correctionValue.trim().length === 0
                                }
                                onClick={() =>
                                  correctionMutation.mutate({
                                    factId: item.fact_id,
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
                        ) : null}
                      </div>
                    );
                  })}
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="space-y-4 xl:sticky xl:top-6 xl:self-start">
            <Card className="border-border/60 bg-card/85">
              <CardHeader>
                <CardTitle>Review Context</CardTitle>
                <CardDescription>Use evidence snippets to compare against the report.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div>
                  <div className="text-xs uppercase text-muted-foreground">Document</div>
                  <div className="mt-1 font-medium text-foreground">
                    {reviewQuery.data?.document.file_name}
                  </div>
                </div>
                <div>
                  <div className="text-xs uppercase text-muted-foreground">Company</div>
                  <div className="mt-1 text-foreground">
                    {reviewQuery.data?.document.ticker ?? '—'}
                    {reviewQuery.data?.document.company_name
                      ? ` · ${reviewQuery.data.document.company_name}`
                      : ''}
                  </div>
                </div>
                <div>
                  <div className="text-xs uppercase text-muted-foreground">Report Date</div>
                  <div className="mt-1 text-foreground">
                    {formatDateOnly(reviewQuery.data?.document.report_date ?? null)}
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card className="border-border/60 bg-card/85">
              <CardHeader>
                <CardTitle>Report Text</CardTitle>
                <CardDescription>Original extracted text for side-by-side review.</CardDescription>
              </CardHeader>
              <CardContent>
                {rawTextQuery.isLoading ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Loading report text...
                  </div>
                ) : rawTextQuery.data ? (
                  <pre className="max-h-[620px] overflow-auto whitespace-pre-wrap rounded-md border border-border/60 bg-muted/30 p-3 text-xs leading-relaxed text-foreground">
                    {rawTextQuery.data}
                  </pre>
                ) : (
                  <div className="text-sm text-muted-foreground">
                    No raw report text is available for this document.
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
