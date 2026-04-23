'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import axios from 'axios';

import apiClient from '@/lib/api/client';
import TickerSearchBox from '@/components/TickerSearchBox';
import StockSummaryCard from '@/components/StockSummaryCard';
import actualConflictHelpers from '@/lib/actualConflicts';
import provenanceHelpers from '@/lib/factProvenance';
import { buildStockRoute, normalizeTicker } from '@/lib/stockRoutes';

const { buildActualConflictDisplayItems } = actualConflictHelpers;
const { formatFactProvenanceLabel } = provenanceHelpers;

type FactProvenance = {
  source_type?: string | null;
  source_document_id?: number | null;
  source_report_date?: string | null;
  period_end_date?: string | null;
  is_active_report?: boolean;
};

type StockSummary = {
  id: number;
  ticker: string;
  exchange: string | null;
  company_name: string;
  price: number | null;
  pe: number | null;
  active_report_document_id?: number | null;
  active_report_date?: string | null;
  price_provenance?: FactProvenance | null;
  pe_provenance?: FactProvenance | null;
  actual_conflict_count?: number;
  actual_conflicts?: Array<{
    metric_key: string;
    period_type: string | null;
    period_end_date: string | null;
    observations: Array<{
      value_numeric: number | null;
      value_text: string | null;
      source_report_date: string | null;
    }>;
  }>;
};

export default function StockSummaryPage() {
  const params = useParams();
  const tickerParam = Array.isArray(params?.ticker) ? params.ticker[0] : params?.ticker;
  const [summary, setSummary] = useState<StockSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tickerForLink = summary?.ticker ?? (tickerParam || '').toString();
  const dcfRoute = buildStockRoute(normalizeTicker(tickerForLink), 'dcf');
  const actualConflictItems = buildActualConflictDisplayItems(summary?.actual_conflicts ?? []);

  useEffect(() => {
    if (!tickerParam) {
      return;
    }

    let isActive = true;
    setLoading(true);
    setError(null);

    apiClient
      .get(`/stocks/by_ticker/${encodeURIComponent(tickerParam)}`)
      .then((response) => {
        if (!isActive) {
          return;
        }
        setSummary(response.data);
        setLoading(false);
      })
      .catch((err) => {
        if (!isActive) {
          return;
        }
        if (axios.isAxiosError(err) && err.response?.status === 404) {
          setError('not_found');
        } else {
          setError('unknown');
        }
        setSummary(null);
        setLoading(false);
      });

    return () => {
      isActive = false;
    };
  }, [tickerParam]);

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <h1 className="text-xl font-semibold tracking-tight">股票摘要</h1>
        <TickerSearchBox defaultValue={(tickerParam || '').toString().toUpperCase()} />
      </div>

      {loading && <div className="text-sm text-muted-foreground">加载中...</div>}

      {!loading && error === 'not_found' && (
        <div className="rounded-2xl border border-dashed border-border/70 bg-background/70 p-6 text-sm text-muted-foreground">
          未找到该 ticker，请确认后重试。
        </div>
      )}

      {!loading && error === 'unknown' && (
        <div className="rounded-2xl border border-dashed border-border/70 bg-background/70 p-6 text-sm text-muted-foreground">
          当前无法加载该股票数据，请稍后再试。
        </div>
      )}

      {!loading && !error && summary && (
        <StockSummaryCard
          companyName={summary.company_name}
          ticker={summary.ticker}
          exchange={summary.exchange}
          price={summary.price}
          pe={summary.pe}
          activeReportDate={summary.active_report_date}
          activeReportDocumentId={summary.active_report_document_id}
          priceProvenanceLabel={formatFactProvenanceLabel(summary.price_provenance)}
          peProvenanceLabel={formatFactProvenanceLabel(summary.pe_provenance)}
          actualConflictCount={summary.actual_conflict_count ?? 0}
          actualConflictItems={actualConflictItems}
        />
      )}

      <div className="pt-4">
        {dcfRoute ? (
          <Link
            href={dcfRoute}
            className="text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            DCF
          </Link>
        ) : null}
      </div>
    </div>
  );
}
