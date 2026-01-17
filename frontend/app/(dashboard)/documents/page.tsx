'use client';

import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { FileSearch, FileText, Loader2, RefreshCcw, X } from 'lucide-react';

import apiClient from '@/lib/api/client';
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

const USER_ID = 1;

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
  page_count: number;
  companies: Company[];
  company_count: number;
};

type DetailView = {
  type: 'parsed' | 'raw';
  doc: DocumentRow;
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

export default function DocumentsPage() {
  const { toast } = useToast();
  const [detail, setDetail] = useState<DetailView | null>(null);
  const [detailData, setDetailData] = useState<string>('');
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeReparseId, setActiveReparseId] = useState<number | null>(null);

  const documentsQuery = useQuery({
    queryKey: ['documents', USER_ID],
    queryFn: async () => {
      const res = await apiClient.get(`/documents?user_id=${USER_ID}`);
      return res.data as DocumentRow[];
    },
  });

  const reparseMutation = useMutation({
    mutationFn: async (docId: number) => {
      const res = await apiClient.post(`/documents/${docId}/reparse?user_id=${USER_ID}`);
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

  const handleView = async (doc: DocumentRow, type: 'parsed' | 'raw') => {
    setDetail({ doc, type });
    setDetailError(null);
    setDetailData('');
    setDetailLoading(true);
    try {
      if (type === 'parsed') {
        const res = await apiClient.get(`/extractions/document/${doc.id}`);
        setDetailData(JSON.stringify(res.data, null, 2));
      } else {
        const res = await apiClient.get(`/documents/${doc.id}/raw_text?user_id=${USER_ID}`);
        setDetailData(res.data.raw_text || '');
      }
    } catch (err: unknown) {
      setDetailError(getErrorMessage(err, 'Failed to load document data.'));
    } finally {
      setDetailLoading(false);
    }
  };

  const documents = documentsQuery.data ?? [];

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-500">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">Documents</h1>
          <p className="text-sm text-muted-foreground">
            Research input registry for uploaded reports and parsing outcomes.
          </p>
        </div>
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
                  <TableHead>File Name</TableHead>
                  <TableHead>Template</TableHead>
                  <TableHead>Companies</TableHead>
                  <TableHead>Pages</TableHead>
                  <TableHead>Status</TableHead>
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
                      <TableCell className="font-medium text-foreground">
                        {doc.file_name}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {doc.template_label || 'Unknown'}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatCompanies(doc.companies)}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{doc.page_count}</TableCell>
                      <TableCell>
                        <Badge variant={meta.variant}>{meta.label}</Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(doc.upload_time)}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-2">
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

      {detail && (
        <Card className="border-border/60 bg-card/90">
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div>
              <CardDescription>
                {detail.type === 'parsed' ? 'Parsed Data' : 'Raw Text'}
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
