'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { AlertTriangle, FileSearch, FileText, Loader2, RefreshCcw, Upload, X } from 'lucide-react';

import apiClient from '@/lib/api/client';
import activeReportHelpers from '@/lib/documentActiveReport';
import documentCompareHelpers from '@/lib/documentCompare';
import documentEvidenceHelpers from '@/lib/documentEvidence';
import { canUploadDocuments, getDocumentsUploadNotice } from '@/lib/documentsAccess';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useToast } from '@/components/ui/use-toast';

type Company = {
  ticker: string;
  company_name: string;
};

type DocumentRow = {
  id: number;
  file_name: string;
  source: string;
  template_label: string;
  parse_status: string;
  upload_time: string | null;
  report_date: string | null;
  page_count: number;
  parsed_page_count: number;
  companies: Company[];
  company_count: number;
  is_active_report: boolean;
  active_for_tickers: string[];
};

type DetailView = {
  type: 'parsed' | 'raw' | 'evidence';
  doc: DocumentRow;
};

type EvidenceItem = {
  mapping_id: string;
  metric_key: string;
  fact_nature: string | null;
  storage_role: string | null;
  source: string;
  field_key: string;
  extraction_id: number;
  page_number: number | null;
  period_type: string | null;
  period_end_date: string | null;
  value_text: string | null;
  value_json: { raw?: string } | null;
  original_text_snippet: string | null;
};

type EvidenceSectionItem = {
  label: string;
  value: string;
  meta: string | null;
  detail: string | null;
};

type EvidenceSection = {
  id: string;
  title: string;
  items: EvidenceSectionItem[];
};

type CompareItem = {
  stock_ticker: string | null;
  metric_key: string | null;
  mapping_id: string | null;
  period_type: string | null;
  period_end_date: string | null;
  label: string;
  change_type: string;
  left_value: string | null;
  right_value: string | null;
  meta?: string | null;
};

type CompareSection = {
  fact_nature: string;
  title: string;
  items: CompareItem[];
};

type CompareDocumentMeta = {
  id: number;
  file_name: string;
  report_date: string | null;
};

type CompareResponse = {
  left_document: CompareDocumentMeta;
  right_document: CompareDocumentMeta;
  shared_tickers: string[];
  sections: CompareSection[];
};

type StatusMeta = {
  label: string;
  variant: 'default' | 'secondary' | 'success' | 'warning' | 'danger';
};

const STATUS_META: Record<string, StatusMeta> = {
  uploaded: { label: 'Uploaded', variant: 'secondary' },
  parsing: { label: 'Parsing...', variant: 'secondary' },
  parsed: { label: 'Parsed', variant: 'success' },
  parsed_partial: { label: 'Partially Parsed', variant: 'warning' },
  failed: { label: 'Failed', variant: 'danger' },
};

type ApiError = {
  response?: {
    data?: {
      detail?: string;
    };
  };
  message?: string;
};

function getErrorMessage(error: unknown, fallback: string) {
  if (typeof error === 'object' && error !== null) {
    const apiError = error as ApiError;
    return apiError.response?.data?.detail ?? apiError.message ?? fallback;
  }
  return fallback;
}

function formatCompanies(companies: Company[], max: number = 3) {
  if (!companies || companies.length === 0) return '—';
  const tickers = companies.map((c) => c.ticker).filter(Boolean);
  if (tickers.length <= max) return tickers.join(', ');
  const shown = tickers.slice(0, max);
  return `${shown.join(', ')} (+${tickers.length - max})`;
}

function formatDate(iso: string | null) {
  if (!iso) return '—';
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return '—';
  return dt.toLocaleString();
}

function formatDateOnly(iso: string | null) {
  if (!iso) return '—';
  const dt = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(dt.getTime())) return '—';
  return dt.toLocaleDateString();
}

function formatPageCount(total: number, parsed?: number) {
  if (!total) return '—';
  const parsedCount = typeof parsed === 'number' ? parsed : 0;
  return `${parsedCount} / ${total}`;
}

const { buildVisibleDocumentCompareSections } = documentCompareHelpers;
const { buildDocumentEvidenceSections } = documentEvidenceHelpers;
const { formatActiveReportTickers, getActiveReportBadgeLabel } = activeReportHelpers;

export default function DocumentsPage() {
  const { toast } = useToast();
  const [role, setRole] = useState<string | null>(null);
  const [detail, setDetail] = useState<DetailView | null>(null);
  const [detailData, setDetailData] = useState<string>('');
  const [detailEvidence, setDetailEvidence] = useState<EvidenceSection[]>([]);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeReparseId, setActiveReparseId] = useState<number | null>(null);
  const [compareLeftId, setCompareLeftId] = useState<number | null>(null);
  const [compareRightId, setCompareRightId] = useState<number | null>(null);
  const [compareData, setCompareData] = useState<CompareResponse | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);

  useEffect(() => {
    if (typeof document === 'undefined') return;
    const cookiePart = document.cookie
      .split('; ')
      .find((item) => item.startsWith('vp_role='));
    setRole(cookiePart ? decodeURIComponent(cookiePart.split('=')[1]) : null);
  }, []);

  const documentsQuery = useQuery({
    queryKey: ['documents'],
    queryFn: async () => {
      const res = await apiClient.get('/documents');
      return res.data as DocumentRow[];
    },
  });

  const reparseMutation = useMutation({
    mutationFn: async (docId: number) => {
      const res = await apiClient.post(`/documents/${docId}/reparse`);
      return res.data;
    },
    onSuccess: () => {
      setActiveReparseId(null);
      documentsQuery.refetch();
      toast({
        title: 'Reparse complete',
        description: 'Latest parsed data is now available in the screener.',
      });
    },
    onError: (error: unknown) => {
      setActiveReparseId(null);
      const message = getErrorMessage(error, 'Reparse failed. Please try again.');
      toast({
        title: 'Reparse failed',
        description: message,
        variant: 'destructive',
      });
    },
  });

  const handleView = async (doc: DocumentRow, type: 'parsed' | 'raw' | 'evidence') => {
    setDetail({ doc, type });
    setDetailError(null);
    setDetailData('');
    setDetailEvidence([]);
    setDetailLoading(true);
    try {
      if (type === 'parsed') {
        const res = await apiClient.get(`/extractions/document/${doc.id}`);
        setDetailData(JSON.stringify(res.data, null, 2));
      } else if (type === 'evidence') {
        const res = await apiClient.get(`/documents/${doc.id}/evidence`);
        setDetailEvidence(
          buildDocumentEvidenceSections((res.data?.evidence ?? []) as EvidenceItem[])
        );
      } else {
        const res = await apiClient.get(`/documents/${doc.id}/raw_text`);
        setDetailData(res.data.raw_text || '');
      }
    } catch (err: unknown) {
      setDetailError(getErrorMessage(err, 'Failed to load document data.'));
    } finally {
      setDetailLoading(false);
    }
  };

  const documents = documentsQuery.data ?? [];
  const canUpload = canUploadDocuments(role);
  const uploadNotice = getDocumentsUploadNotice(role);
  const compareLeftDoc = documents.find((doc) => doc.id === compareLeftId) ?? null;
  const compareRightDoc = documents.find((doc) => doc.id === compareRightId) ?? null;
  const compareSections = buildVisibleDocumentCompareSections(compareData?.sections ?? []);

  useEffect(() => {
    if (!compareLeftId || !compareRightId || compareLeftId === compareRightId) {
      setCompareData(null);
      setCompareError(
        compareLeftId && compareRightId && compareLeftId === compareRightId
          ? 'Choose two different documents to compare.'
          : null
      );
      setCompareLoading(false);
      return;
    }

    let isActive = true;
    setCompareLoading(true);
    setCompareError(null);

    apiClient
      .get(
        `/documents/compare?left_document_id=${encodeURIComponent(compareLeftId)}&right_document_id=${encodeURIComponent(compareRightId)}`
      )
      .then((res) => {
        if (!isActive) {
          return;
        }
        setCompareData(res.data as CompareResponse);
        setCompareLoading(false);
      })
      .catch((err: unknown) => {
        if (!isActive) {
          return;
        }
        setCompareData(null);
        setCompareError(getErrorMessage(err, 'Failed to compare documents.'));
        setCompareLoading(false);
      });

    return () => {
      isActive = false;
    };
  }, [compareLeftId, compareRightId]);

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-500">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">Documents</h1>
          <p className="text-sm text-muted-foreground">
            Research input registry for uploaded reports and parsing outcomes.
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {canUpload ? (
            <Button asChild>
              <Link href="/upload">
                <Upload className="h-4 w-4" />
                Upload Document
              </Link>
            </Button>
          ) : null}
          <div className="flex items-center gap-2 rounded-full border border-border/60 bg-card/80 px-4 py-2 text-xs text-muted-foreground">
            <span className="font-semibold text-foreground">{documents.length}</span>
            documents tracked
            {documentsQuery.isFetching && (
              <span className="flex items-center gap-1 text-primary">
                <Loader2 className="h-3 w-3 animate-spin" />
                Refreshing
              </span>
            )}
          </div>
        </div>
      </div>

      {uploadNotice && (
        <Card className="border-amber-300/60 bg-amber-50/70">
          <CardContent className="flex items-start gap-3 p-4 text-sm text-amber-900">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div className="font-medium">Upload access restricted</div>
              <p>{uploadNotice}</p>
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="border-border/60 bg-card/85">
        <CardHeader className="flex flex-row items-start justify-between">
          <div>
            <CardTitle>Document Register</CardTitle>
            <CardDescription>Container-level view of uploads and parsing health.</CardDescription>
          </div>
          <div className="text-xs text-muted-foreground">
            {documentsQuery.isLoading ? 'Loading...' : 'Latest snapshot'}
          </div>
        </CardHeader>
        <CardContent>
          {documentsQuery.isLoading ? (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading documents...
            </div>
          ) : documents.length === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              No documents found.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[72px]">ID</TableHead>
                  <TableHead>File Name</TableHead>
                  <TableHead>Template</TableHead>
                  <TableHead>Companies</TableHead>
                  <TableHead>Pages</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Active Report</TableHead>
                  <TableHead>Report Date</TableHead>
                  <TableHead>Uploaded</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((doc, index) => {
                  const meta = STATUS_META[doc.parse_status] ?? {
                    label: doc.parse_status,
                    variant: 'secondary',
                  };
                  return (
                    <TableRow
                      key={doc.id}
                      className="animate-in fade-in slide-in-from-bottom-1 duration-500"
                      style={{ animationDelay: `${index * 40}ms` }}
                    >
                      <TableCell className="text-muted-foreground">{doc.id}</TableCell>
                      <TableCell className="font-medium text-foreground">
                        {doc.file_name}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {doc.template_label || 'Unknown'}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        <div className="space-y-1">
                          <div>{formatCompanies(doc.companies)}</div>
                          {doc.active_for_tickers.length > 0 ? (
                            <div className="text-xs text-emerald-700">
                              {formatActiveReportTickers(doc.active_for_tickers)}
                            </div>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatPageCount(doc.page_count, doc.parsed_page_count)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={meta.variant}>{meta.label}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant={doc.is_active_report ? 'success' : 'secondary'}>
                          {getActiveReportBadgeLabel(doc.is_active_report)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDateOnly(doc.report_date)}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(doc.upload_time)}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-2">
                          <Button asChild variant="outline" size="sm">
                            <Link href={`/documents/${doc.id}/review`}>
                              <FileSearch className="h-3 w-3" />
                              Review Extracted Data
                            </Link>
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleView(doc, 'parsed')}
                          >
                            <FileSearch className="h-3 w-3" />
                            View Parsed Data
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleView(doc, 'evidence')}
                          >
                            <FileSearch className="h-3 w-3" />
                            View Evidence
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleView(doc, 'raw')}
                          >
                            <FileText className="h-3 w-3" />
                            View Raw Text
                          </Button>
                          <Button
                            size="sm"
                            onClick={() => {
                              setActiveReparseId(doc.id);
                              reparseMutation.mutate(doc.id);
                            }}
                            disabled={reparseMutation.isPending && activeReparseId === doc.id}
                          >
                            {reparseMutation.isPending && activeReparseId === doc.id ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <RefreshCcw className="h-3 w-3" />
                            )}
                            Reparse
                          </Button>
                          <Button
                            variant={compareLeftId === doc.id ? 'default' : 'secondary'}
                            size="sm"
                            onClick={() => setCompareLeftId(doc.id)}
                          >
                            Set Left
                          </Button>
                          <Button
                            variant={compareRightId === doc.id ? 'default' : 'secondary'}
                            size="sm"
                            onClick={() => setCompareRightId(doc.id)}
                          >
                            Set Right
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card className="border-border/60 bg-card/85">
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Document Compare</CardTitle>
            <CardDescription>
              Compare two report versions for the same company across actual, estimate, snapshot,
              and opinion fields.
            </CardDescription>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setCompareLeftId(null);
              setCompareRightId(null);
              setCompareData(null);
              setCompareError(null);
            }}
          >
            Clear Compare
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
              <div className="text-xs uppercase text-muted-foreground">Left Report</div>
              <div className="mt-2 text-sm font-medium text-foreground">
                {compareLeftDoc ? compareLeftDoc.file_name : 'Select a document'}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {compareLeftDoc ? formatDateOnly(compareLeftDoc.report_date) : '—'}
              </div>
            </div>
            <div className="rounded-xl border border-border/60 bg-muted/20 p-4">
              <div className="text-xs uppercase text-muted-foreground">Right Report</div>
              <div className="mt-2 text-sm font-medium text-foreground">
                {compareRightDoc ? compareRightDoc.file_name : 'Select a document'}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {compareRightDoc ? formatDateOnly(compareRightDoc.report_date) : '—'}
              </div>
            </div>
          </div>

          {compareLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Comparing documents...
            </div>
          ) : compareError ? (
            <div className="text-sm text-destructive">{compareError}</div>
          ) : compareData ? (
            <div className="space-y-4">
              <div className="text-sm text-muted-foreground">
                Shared tickers: {compareData.shared_tickers.join(', ') || '—'}
              </div>
              {compareSections.length > 0 ? (
                compareSections.map((section) => (
                  <div
                    key={section.id}
                    className="rounded-xl border border-border/60 bg-muted/20 p-4"
                  >
                    <div className="mb-3 text-sm font-semibold text-foreground">
                      {section.title}
                    </div>
                    <div className="space-y-3">
                      {section.items.map((item) => (
                        <div
                          key={`${section.id}-${item.label}-${item.meta}`}
                          className="rounded-lg border border-border/40 bg-background/80 p-3"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="text-sm font-medium text-foreground">{item.label}</div>
                            {item.meta ? (
                              <div className="text-xs text-muted-foreground">{item.meta}</div>
                            ) : null}
                          </div>
                          <div className="mt-2 grid gap-3 md:grid-cols-2">
                            <div>
                              <div className="text-xs uppercase text-muted-foreground">Left</div>
                              <div className="mt-1 text-sm text-foreground">
                                {item.left_value ?? 'Not present'}
                              </div>
                            </div>
                            <div>
                              <div className="text-xs uppercase text-muted-foreground">Right</div>
                              <div className="mt-1 text-sm text-foreground">
                                {item.right_value ?? 'Not present'}
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-sm text-muted-foreground">
                  No structured differences detected between the selected reports.
                </div>
              )}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              Select one left report and one right report from the register to compare them.
            </div>
          )}
        </CardContent>
      </Card>

      {detail && (
        <Card className="border-border/60 bg-card/90">
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div>
              <CardDescription>
                {detail.type === 'parsed'
                  ? 'Parsed Data'
                  : detail.type === 'evidence'
                    ? 'Evidence View'
                    : 'Raw Text'}
              </CardDescription>
              <CardTitle>{detail.doc.file_name}</CardTitle>
            </div>
            <Button variant="ghost" size="icon" onClick={() => setDetail(null)}>
              <X className="h-4 w-4" />
            </Button>
          </CardHeader>
          <CardContent>
            {detailLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading...
              </div>
            ) : detailError ? (
              <div className="text-sm text-destructive">{detailError}</div>
            ) : detail.type === 'evidence' ? (
              detailEvidence.length > 0 ? (
                <div className="space-y-4">
                  {detailEvidence.map((section) => (
                    <div
                      key={section.id}
                      className="rounded-xl border border-border/60 bg-muted/20 p-4"
                    >
                      <div className="mb-3 text-sm font-semibold text-foreground">
                        {section.title}
                      </div>
                      <div className="space-y-3">
                        {section.items.map((item) => (
                          <div
                            key={`${section.id}-${item.label}-${item.value}`}
                            className="space-y-1 rounded-lg border border-border/40 bg-background/80 p-3"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="text-sm font-medium text-foreground">
                                {item.label}
                              </div>
                              {item.meta ? (
                                <div className="text-xs text-muted-foreground">{item.meta}</div>
                              ) : null}
                            </div>
                            <div className="text-sm text-foreground whitespace-pre-wrap">
                              {item.value}
                            </div>
                            {item.detail && item.detail !== item.value ? (
                              <div className="text-xs text-muted-foreground whitespace-pre-wrap">
                                {item.detail}
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">
                  No evidence-only fields available for this document.
                </div>
              )
            ) : detailData ? (
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-xl border border-border/60 bg-muted/30 p-4 text-xs text-foreground">
                {detailData}
              </pre>
            ) : (
              <div className="text-sm text-muted-foreground">No data available.</div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
