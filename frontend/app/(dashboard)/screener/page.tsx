'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import apiClient from '@/lib/api/client';

import { Search, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

type HeaderRatingValue = string | number | null;
type HeaderRatingEntry = { value?: HeaderRatingValue } | HeaderRatingValue;

type HeaderRatings = {
  timeliness?: HeaderRatingEntry;
  safety?: HeaderRatingEntry;
  company_financial_strength?: HeaderRatingValue;
  stock_price_stability?: HeaderRatingValue;
  price_growth_persistence?: HeaderRatingValue;
  earnings_predictability?: HeaderRatingValue;
};

type StockResult = {
  id?: number | string;
  ticker?: string;
  company_name?: string;
  metrics?: Record<string, unknown>;
  header_ratings?: HeaderRatings;
  [key: string]: unknown;
};

function unwrapRating(entry: HeaderRatingEntry | undefined) {
  if (entry && typeof entry === 'object' && 'value' in entry) {
    return entry.value;
  }
  return entry;
}

function formatUSD(value: unknown, digits: number = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function formatUSDMillions(value: unknown) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `${n.toLocaleString(undefined, { maximumFractionDigits: 1 })} M`;
}

function pickFirstDefined<T>(...vals: Array<T | null | undefined>): T | undefined {
  return vals.find((v) => v !== undefined && v !== null) as T | undefined;
}

function formatPct(value: unknown) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  const pct = n <= 1 ? n * 100 : n;
  return `${pct.toFixed(1)}%`;
}

function formatMillions(value: unknown) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `${n.toLocaleString(undefined, { maximumFractionDigits: 1 })} M`;
}

function formatText(value: unknown) {
  if (value === undefined || value === null || value === '') return '—';
  return String(value);
}

export default function ScreenerPage() {
  const [results, setResults] = useState<StockResult[]>([]);
  
  // Hardcoded rule for V0.1 demo
  const defaultRule = JSON.stringify({
    type: "AND",
    conditions: [
        {"metric": "pe_ratio", "operator": "<", "value": 25},
        {"metric": "dividend_yield", "operator": ">", "value": 0.01}
    ]
  }, null, 2);

  const [ruleText, setRuleText] = useState(defaultRule);

  const screenMutation = useMutation({
    mutationFn: async () => {
      const rule = JSON.parse(ruleText);
      const res = await apiClient.post('/screener/run', rule);
      return res.data;
    },
    onSuccess: (data) => {
      setResults(Array.isArray(data) ? data : []);
    }
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Stock Screener</h1>
      
      <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
        <label className="block text-sm font-medium text-gray-700 mb-2">Screening Rules (JSON)</label>
        <Textarea
          value={ruleText}
          onChange={(e) => setRuleText(e.target.value)}
          className="h-48 font-mono bg-gray-50"
        />
        
        <div className="mt-4 flex justify-end">
          <Button
            onClick={() => screenMutation.mutate()}
            disabled={screenMutation.isPending}
          >
            {screenMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            Run Screen
          </Button>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-gray-200">
        <div className="p-4 border-b bg-gray-50 font-semibold text-gray-700">Results ({results.length})</div>
        {results.length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            No stocks found matching criteria.
          </div>
        ) : (
          <div className="relative">
            <div className="pointer-events-none absolute inset-y-0 left-0 w-6 bg-gradient-to-r from-white to-transparent" />
            <div className="pointer-events-none absolute inset-y-0 right-0 w-6 bg-gradient-to-l from-white to-transparent" />
            <div className="overflow-x-auto">
              <Table className="min-w-max">
              <TableHeader className="bg-gray-50">
                <TableRow>
                  <TableHead>Ticker</TableHead>
                  <TableHead>Company Name</TableHead>
                  <TableHead>Net Profit</TableHead>
                  <TableHead>Depreciation</TableHead>
                  <TableHead>Cap’l Spending / Sh</TableHead>
                  <TableHead>Common Shs Outst’g</TableHead>
                  <TableHead>TIMELINESS</TableHead>
                  <TableHead>SAFETY</TableHead>
                  <TableHead>Avg Ann’l Div’d Yield</TableHead>
                  <TableHead>Company’s Financial Strength</TableHead>
                  <TableHead>Stock’s Price Stability</TableHead>
                  <TableHead>Price Growth Persistence</TableHead>
                  <TableHead>Earnings Predictability</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className="bg-white">
                {results.map((stock) => {
                  const metrics = (stock?.metrics ?? {}) as Record<string, unknown>;
                  const netProfit = pickFirstDefined(
                    metrics.net_profit_usd_millions,
                    metrics.net_profit,
                    stock.net_profit_usd_millions,
                    stock.net_profit
                  );
                  const depreciation = pickFirstDefined(
                    metrics.depreciation_usd_millions,
                    metrics.depreciation,
                    stock.depreciation_usd_millions,
                    stock.depreciation
                  );
                  const capexPerSh = pickFirstDefined(
                    metrics.capital_spending_per_share_usd,
                    metrics.capex_per_share_usd,
                    stock.capital_spending_per_share_usd,
                    stock.capex_per_share_usd
                  );

                  const commonShs = pickFirstDefined(
                    metrics.common_shares_outstanding_millions,
                    metrics.common_shs_outstg_millions,
                    stock.common_shares_outstanding_millions,
                    stock.common_shs_outstg_millions
                  );

                  const timeliness = pickFirstDefined(
                    metrics.timeliness,
                    stock.timeliness,
                    unwrapRating(stock.header_ratings?.timeliness)
                  );

                  const safety = pickFirstDefined(
                    metrics.safety,
                    stock.safety,
                    unwrapRating(stock.header_ratings?.safety)
                  );

                  const avgDivYield = pickFirstDefined(
                    metrics.avg_annual_dividend_yield_pct,
                    metrics.avg_annl_divd_yield_pct,
                    stock.avg_annual_dividend_yield_pct,
                    stock.avg_annl_divd_yield_pct
                  );

                  const finStrength = pickFirstDefined(
                    metrics.company_financial_strength,
                    stock.company_financial_strength,
                    stock.header_ratings?.company_financial_strength
                  );

                  const priceStability = pickFirstDefined(
                    metrics.stock_price_stability,
                    stock.stock_price_stability,
                    stock.header_ratings?.stock_price_stability
                  );

                  const priceGrowthPersistence = pickFirstDefined(
                    metrics.price_growth_persistence,
                    stock.price_growth_persistence,
                    stock.header_ratings?.price_growth_persistence
                  );

                  const earningsPredictability = pickFirstDefined(
                    metrics.earnings_predictability,
                    stock.earnings_predictability,
                    stock.header_ratings?.earnings_predictability
                  );

                  return (
                    <TableRow key={stock.id ?? `${stock.ticker}-${stock.company_name}`}>
                      <TableCell className="whitespace-nowrap font-medium text-gray-900">{stock.ticker ?? '—'}</TableCell>
                      <TableCell className="whitespace-nowrap text-gray-500">{stock.company_name ?? '—'}</TableCell>
                      <TableCell className="whitespace-nowrap text-gray-900">{formatUSDMillions(netProfit)}</TableCell>
                      <TableCell className="whitespace-nowrap text-gray-900">{formatUSDMillions(depreciation)}</TableCell>
                      <TableCell className="whitespace-nowrap text-gray-900">{formatUSD(capexPerSh, 2)}</TableCell>
                      <TableCell className="whitespace-nowrap text-gray-900">{formatMillions(commonShs)}</TableCell>
                      <TableCell className="whitespace-nowrap text-gray-900">{formatText(timeliness)}</TableCell>
                      <TableCell className="whitespace-nowrap text-gray-900">{formatText(safety)}</TableCell>
                      <TableCell className="whitespace-nowrap text-gray-900">{formatPct(avgDivYield)}</TableCell>
                      <TableCell className="whitespace-nowrap text-gray-900">{formatText(finStrength)}</TableCell>
                      <TableCell className="whitespace-nowrap text-gray-900">{formatText(priceStability)}</TableCell>
                      <TableCell className="whitespace-nowrap text-gray-900">{formatText(priceGrowthPersistence)}</TableCell>
                      <TableCell className="whitespace-nowrap text-gray-900">{formatText(earningsPredictability)}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
              </Table>
            </div>
            <div className="flex items-center justify-center gap-2 py-2 text-xs text-gray-400">
              <span aria-hidden>←</span>
              <span className="h-1 w-24 rounded-full bg-gradient-to-r from-gray-200 via-gray-400 to-gray-200" />
              <span>Scroll horizontally to see more</span>
              <span aria-hidden>→</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
