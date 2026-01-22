'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import apiClient from '@/lib/api/client';

import { Search, Loader2 } from 'lucide-react';

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
        <textarea 
          value={ruleText}
          onChange={(e) => setRuleText(e.target.value)}
          className="w-full h-48 font-mono text-sm p-4 border rounded-md bg-gray-50 focus:ring-2 focus:ring-blue-500 outline-none"
        />
        
        <div className="mt-4 flex justify-end">
          <button
            onClick={() => screenMutation.mutate()}
            disabled={screenMutation.isPending}
            className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            {screenMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            Run Screen
          </button>
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
              <table className="min-w-max divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Ticker</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Company Name</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Net Profit</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Depreciation</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Cap’l Spending / Sh</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Common Shs Outst’g</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">TIMELINESS</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">SAFETY</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Avg Ann’l Div’d Yield</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Company’s Financial Strength</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Stock’s Price Stability</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Price Growth Persistence</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Earnings Predictability</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
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
                    <tr key={stock.id ?? `${stock.ticker}-${stock.company_name}`}>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{stock.ticker ?? '—'}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{stock.company_name ?? '—'}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{formatUSDMillions(netProfit)}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{formatUSDMillions(depreciation)}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{formatUSD(capexPerSh, 2)}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{formatMillions(commonShs)}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{formatText(timeliness)}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{formatText(safety)}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{formatPct(avgDivYield)}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{formatText(finStrength)}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{formatText(priceStability)}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{formatText(priceGrowthPersistence)}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{formatText(earningsPredictability)}</td>
                    </tr>
                  );
                })}
              </tbody>
              </table>
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
