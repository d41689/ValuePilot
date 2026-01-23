'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import axios from 'axios';

import apiClient from '@/lib/api/client';
import TickerSearchBox from '@/components/TickerSearchBox';
import StockSummaryCard from '@/components/StockSummaryCard';

type StockSummary = {
  id: number;
  ticker: string;
  exchange: string | null;
  company_name: string;
  price: number | null;
  pe: number | null;
};

export default function StockSummaryPage() {
  const params = useParams();
  const tickerParam = Array.isArray(params?.ticker) ? params.ticker[0] : params?.ticker;
  const [summary, setSummary] = useState<StockSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
        />
      )}
    </div>
  );
}
