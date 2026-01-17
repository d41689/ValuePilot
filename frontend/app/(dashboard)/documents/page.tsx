'use client';

import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import apiClient from '@/lib/api/client';
import { Loader2, RefreshCcw, FileText, FileSearch, X } from 'lucide-react';

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

const STATUS_META: Record<string, { label: string; className: string }> = {
  uploaded: { label: 'Uploaded', className: 'bg-gray-100 text-gray-700' },
  parsing: { label: 'Parsing...', className: 'bg-blue-100 text-blue-700' },
  parsed: { label: 'Parsed', className: 'bg-green-100 text-green-700' },
  parsed_partial: { label: 'Partially Parsed', className: 'bg-orange-100 text-orange-700' },
  failed: { label: 'Failed', className: 'bg-red-100 text-red-700' },
};

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
  const [detail, setDetail] = useState<DetailView | null>(null);
  const [detailData, setDetailData] = useState<string>('');
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

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
      documentsQuery.refetch();
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
    } catch (err: any) {
      setDetailError(err?.message ?? 'Failed to load document data.');
    } finally {
      setDetailLoading(false);
    }
  };

  const documents = documentsQuery.data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Documents</h1>
        <p className="text-gray-600">Research input registry for uploaded reports and parsing outcomes.</p>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="p-4 border-b bg-gray-50 font-semibold text-gray-700 flex items-center justify-between">
          <span>Documents ({documents.length})</span>
          {documentsQuery.isFetching && (
            <span className="text-xs text-gray-500 flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              Refreshing
            </span>
          )}
        </div>
        {documentsQuery.isLoading ? (
          <div className="p-8 text-center text-gray-500 flex items-center justify-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading documents...
          </div>
        ) : documents.length === 0 ? (
          <div className="p-8 text-center text-gray-500">No documents found.</div>
        ) : (
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">File Name</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Template</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Companies</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Pages</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Uploaded</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {documents.map((doc) => {
                const meta = STATUS_META[doc.parse_status] ?? {
                  label: doc.parse_status,
                  className: 'bg-gray-100 text-gray-700',
                };
                return (
                  <tr key={doc.id}>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{doc.file_name}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">{doc.template_label || 'Unknown'}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">{formatCompanies(doc.companies)}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">{doc.page_count}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${meta.className}`}>
                        {meta.label}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{formatDate(doc.upload_time)}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50"
                          onClick={() => handleView(doc, 'parsed')}
                        >
                          <FileSearch className="h-3 w-3" />
                          View Parsed Data
                        </button>
                        <button
                          className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50"
                          onClick={() => handleView(doc, 'raw')}
                        >
                          <FileText className="h-3 w-3" />
                          View Raw Text
                        </button>
                        <button
                          className="inline-flex items-center gap-1 rounded-md border border-blue-200 px-2 py-1 text-xs text-blue-700 hover:bg-blue-50"
                          onClick={() => reparseMutation.mutate(doc.id)}
                          disabled={reparseMutation.isPending}
                        >
                          {reparseMutation.isPending ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <RefreshCcw className="h-3 w-3" />
                          )}
                          Reparse
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {detail && (
        <div className="bg-white border border-gray-200 rounded-lg shadow-sm">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <div>
              <div className="text-sm text-gray-500">{detail.type === 'parsed' ? 'Parsed Data' : 'Raw Text'}</div>
              <div className="text-base font-semibold text-gray-900">{detail.doc.file_name}</div>
            </div>
            <button
              className="rounded-md border border-gray-200 p-1 text-gray-500 hover:text-gray-700"
              onClick={() => setDetail(null)}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="p-4">
            {detailLoading ? (
              <div className="flex items-center gap-2 text-gray-500">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading...
              </div>
            ) : detailError ? (
              <div className="text-sm text-red-600">{detailError}</div>
            ) : detailData ? (
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-gray-50 p-4 text-xs text-gray-700">
                {detailData}
              </pre>
            ) : (
              <div className="text-sm text-gray-500">No data available.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
