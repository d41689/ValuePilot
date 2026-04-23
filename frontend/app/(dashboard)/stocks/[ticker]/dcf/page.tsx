'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import { HelpCircle } from 'lucide-react';
import axios from 'axios';

import TickerSearchBox from '@/components/TickerSearchBox';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { toast } from '@/components/ui/use-toast';
import provenanceHelpers from '@/lib/factProvenance';
import { normalizeTicker } from '@/lib/stockRoutes';
import { computeGrowthValue, computeTerminalValue, computeTotalValue } from '@/lib/dcfMath';
import { resolveDcfDefaults } from '@/lib/dcfDefaults';
import {
  resolveDcfComponentInputs,
  resolveDcfInputsPayload,
  type DcfInputsResponsePayload,
} from '@/lib/dcfInputsSeries';
import apiClient from '@/lib/api/client';

const { formatFactProvenanceLabel, formatComputedFactProvenanceLabel } = provenanceHelpers;

const DEFAULT_NET_PROFIT_PER_SHARE = '12.00';
const DEFAULT_DEPRECIATION_PER_SHARE = '3.00';
const DEFAULT_CAPEX_PER_SHARE = '0.45';
const DEFAULT_DISCOUNT_RATE = 10;
const DEFAULT_GROWTH_YEARS = 10;
const DEFAULT_GROWTH_RATE = 20;
const DEFAULT_TERMINAL_YEARS = 1000;
const DEFAULT_TERMINAL_RATE = 4;

const toNumber = (value: string, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const clampNonNegative = (value: number) => (value < 0 ? 0 : value);

const formatMoney = (value: number) =>
  value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

const formatInputMoney = (value: number) =>
  value.toLocaleString('en-US', {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  });

type FactProvenance = {
  source_type?: string | null;
  source_document_id?: number | null;
  source_report_date?: string | null;
  period_end_date?: string | null;
  is_active_report?: boolean;
};

type ComputedFactProvenance = {
  inputs?: Array<
    {
      metric_key?: string;
    } & FactProvenance
  >;
};

type DcfValueWithProvenance = {
  value?: number;
  source?: string;
  provenance?: FactProvenance | ComputedFactProvenance | null;
};

type StockDcfPayload = {
  id?: number;
  latest_price?: number | null;
  latest_price_updated_at?: string | null;
  active_report_document_id?: number | null;
  active_report_date?: string | null;
  oeps_normalized_provenance?: FactProvenance | null;
  growth_rate_options?: Array<{
    key: string;
    label: string;
    value: number;
    provenance?: FactProvenance | null;
  }> | null;
};

export default function StockDcfPage() {
  const params = useParams();
  const tickerParam = Array.isArray(params?.ticker) ? params.ticker[0] : params?.ticker;
  const displayTicker = normalizeTicker((tickerParam || '').toString());

  const [latestPrice, setLatestPrice] = useState<number | null>(null);
  const [latestPriceUpdatedAt, setLatestPriceUpdatedAt] = useState<string | null>(null);
  const [manualPrice, setManualPrice] = useState('');
  const [stockId, setStockId] = useState<number | null>(null);
  const [stockPayload, setStockPayload] = useState<StockDcfPayload | null>(null);
  const [isSavingFairValue, setIsSavingFairValue] = useState(false);
  const [hasResolvedStockDefaults, setHasResolvedStockDefaults] = useState(false);
  const [netProfitPerShare, setNetProfitPerShare] = useState(DEFAULT_NET_PROFIT_PER_SHARE);
  const [depreciationPerShare, setDepreciationPerShare] = useState(DEFAULT_DEPRECIATION_PER_SHARE);
  const [capexPerShare, setCapexPerShare] = useState(DEFAULT_CAPEX_PER_SHARE);
  const [basedOnOverride, setBasedOnOverride] = useState('');
  const [dcfInputsPayload, setDcfInputsPayload] = useState<DcfInputsResponsePayload | null>(null);
  const [oepsSeries, setOepsSeries] = useState<Array<{ year: number; value: number }>>([]);
  const [oepsNormalized, setOepsNormalized] = useState<number | null>(null);
  const [basedOnSelection, setBasedOnSelection] = useState<'norm' | number>('norm');
  const [growthRateOptions, setGrowthRateOptions] = useState<
    Array<{ key: string; label: string; value: number }>
  >([]);
  const [growthRateSelection, setGrowthRateSelection] = useState<string | null>(null);

  const [discountRate, setDiscountRate] = useState(DEFAULT_DISCOUNT_RATE);
  const [growthYears, setGrowthYears] = useState(DEFAULT_GROWTH_YEARS);
  const [growthRate, setGrowthRate] = useState(DEFAULT_GROWTH_RATE);
  const [terminalYears, setTerminalYears] = useState(DEFAULT_TERMINAL_YEARS);
  const [terminalRate, setTerminalRate] = useState(DEFAULT_TERMINAL_RATE);

  useEffect(() => {
    if (!displayTicker) {
      return;
    }
    let isActive = true;
    setHasResolvedStockDefaults(false);
    setLatestPrice(null);
    setLatestPriceUpdatedAt(null);
    setManualPrice('');
    setStockId(null);
    setStockPayload(null);
    setNetProfitPerShare(DEFAULT_NET_PROFIT_PER_SHARE);
    setDepreciationPerShare(DEFAULT_DEPRECIATION_PER_SHARE);
    setCapexPerShare(DEFAULT_CAPEX_PER_SHARE);
    setBasedOnOverride('');
    setDcfInputsPayload(null);
    setOepsSeries([]);
    setOepsNormalized(null);
    setBasedOnSelection('norm');
    setGrowthRateOptions([]);
    setGrowthRateSelection(null);
    setDiscountRate(DEFAULT_DISCOUNT_RATE);
    setGrowthYears(DEFAULT_GROWTH_YEARS);
    setGrowthRate(DEFAULT_GROWTH_RATE);
    setTerminalYears(DEFAULT_TERMINAL_YEARS);
    setTerminalRate(DEFAULT_TERMINAL_RATE);
    const hydrate = async () => {
      try {
        const response = await apiClient.get(`/stocks/by_ticker/${encodeURIComponent(displayTicker)}`);
        if (!isActive) {
          return;
        }
        const payload = (response.data ?? {}) as StockDcfPayload & Record<string, unknown>;
        setStockPayload(payload);
        const defaults = resolveDcfDefaults(payload);
        const nextDcfInputsPayload: DcfInputsResponsePayload = {
          dcf_inputs: payload?.dcf_inputs ?? null,
          dcf_inputs_series: payload?.dcf_inputs_series ?? null,
        };
        if (typeof payload.id === 'number') {
          setStockId(payload.id);
        }
        const fetchedLatest = payload.latest_price;
        if (typeof fetchedLatest === 'number' && Number.isFinite(fetchedLatest)) {
          setLatestPrice(fetchedLatest);
          setLatestPriceUpdatedAt(payload.latest_price_updated_at ?? null);
        }
        setDcfInputsPayload(nextDcfInputsPayload);
        setOepsSeries(defaults.oepsSeries);
        setOepsNormalized(defaults.oepsNormalized);
        setGrowthRateOptions(defaults.growthRateOptions);
        setBasedOnSelection(defaults.basedOnSelection);
        const resolvedInputs = resolveDcfComponentInputs(
          nextDcfInputsPayload,
          defaults.basedOnSelection
        );
        const hasResolvedInputs = [
          resolvedInputs.netProfitPerShare,
          resolvedInputs.depreciationPerShare,
          resolvedInputs.capexPerShare,
        ].some((value) => value !== '');
        if (hasResolvedInputs) {
          setNetProfitPerShare(resolvedInputs.netProfitPerShare);
          setDepreciationPerShare(resolvedInputs.depreciationPerShare);
          setCapexPerShare(resolvedInputs.capexPerShare);
          setBasedOnOverride('');
        } else if (defaults.basedOnOverride) {
          setBasedOnOverride(defaults.basedOnOverride);
        }
        if (defaults.growthRateSelection && defaults.growthRate !== null) {
          setGrowthRateSelection(defaults.growthRateSelection);
          setGrowthRate(defaults.growthRate);
        }
        setHasResolvedStockDefaults(true);
        const stockId = payload?.id;
        if (typeof stockId === 'number') {
          try {
            await apiClient.post('/stocks/prices/refresh', {
              stock_ids: [stockId],
              reason: 'dcf_page',
            });
            const refreshed = await apiClient.get(
              `/stocks/by_ticker/${encodeURIComponent(displayTicker)}`
            );
            if (!isActive) {
              return;
            }
            const refreshedPayload = (refreshed.data ?? {}) as StockDcfPayload & Record<string, unknown>;
            setStockPayload(refreshedPayload);
            if (typeof refreshedPayload.id === 'number') {
              setStockId(refreshedPayload.id);
            }
            const refreshedPrice = refreshedPayload.latest_price;
            if (typeof refreshedPrice === 'number' && Number.isFinite(refreshedPrice)) {
              setLatestPrice(refreshedPrice);
              setLatestPriceUpdatedAt(refreshedPayload.latest_price_updated_at ?? null);
            }
          } catch {
            // best-effort refresh; keep existing price if refresh fails
          }
        }
      } catch (err) {
        if (!isActive) {
          return;
        }
        setHasResolvedStockDefaults(true);
        if (axios.isAxiosError(err)) {
          return;
        }
      }
    };
    hydrate();
    return () => {
      isActive = false;
    };
  }, [displayTicker]);

  const computedBasedOn = useMemo(() => {
    const base =
      toNumber(netProfitPerShare) + toNumber(depreciationPerShare) - toNumber(capexPerShare);
    return Math.max(0, base);
  }, [netProfitPerShare, depreciationPerShare, capexPerShare]);

  const basedOnValue = basedOnOverride.trim()
    ? Math.max(0, toNumber(basedOnOverride))
    : hasResolvedStockDefaults
      ? computedBasedOn
      : 0;

  const growthValue = useMemo(
    () => computeGrowthValue(basedOnValue, discountRate, growthYears, growthRate),
    [basedOnValue, discountRate, growthYears, growthRate]
  );

  const terminalValue = useMemo(
    () =>
      computeTerminalValue(
        basedOnValue,
        discountRate,
        growthYears,
        growthRate,
        terminalYears,
        terminalRate
      ),
    [basedOnValue, discountRate, growthYears, growthRate, terminalYears, terminalRate]
  );

  const totalValue = useMemo(
    () => computeTotalValue(growthValue, terminalValue),
    [growthValue, terminalValue]
  );
  const basedOnInputValue = basedOnOverride.trim()
    ? basedOnOverride
    : hasResolvedStockDefaults
      ? formatInputMoney(computedBasedOn)
      : '';
  const effectivePrice = useMemo(() => {
    if (latestPrice !== null) {
      return Math.max(0, latestPrice);
    }
    const parsed = Number(manualPrice);
    if (!Number.isFinite(parsed)) {
      return null;
    }
    return Math.max(0, parsed);
  }, [latestPrice, manualPrice]);

  const safeMarginPct = useMemo(() => {
    const price = effectivePrice;
    if (price === null) {
      return null;
    }
    if (totalValue <= 0) {
      return null;
    }
    return 100 * (1 - price / totalValue);
  }, [effectivePrice, totalValue]);

  const priceUpdatedLabel = useMemo(() => {
    if (!latestPriceUpdatedAt) {
      return null;
    }
    const dt = new Date(latestPriceUpdatedAt);
    if (Number.isNaN(dt.getTime())) {
      return null;
    }
    return dt.toLocaleString();
  }, [latestPriceUpdatedAt]);

  const activeReportLabel = useMemo(() => {
    if (!stockPayload) {
      return null;
    }
    const segments = [];
    if (stockPayload.active_report_date) {
      const parsed = new Date(`${stockPayload.active_report_date}T00:00:00`);
      segments.push(
        Number.isNaN(parsed.getTime())
          ? stockPayload.active_report_date
          : parsed.toLocaleDateString()
      );
    }
    if (Number.isInteger(stockPayload.active_report_document_id)) {
      segments.push(`doc #${stockPayload.active_report_document_id}`);
    }
    return segments.length > 0 ? `Active report · ${segments.join(' · ')}` : null;
  }, [stockPayload]);

  const selectedBasedOnPayload = useMemo(
    () =>
      resolveDcfInputsPayload(dcfInputsPayload ?? {}, basedOnSelection) as
        | {
            net_profit_per_share?: DcfValueWithProvenance | null;
            depreciation_per_share?: DcfValueWithProvenance | null;
          }
        | null,
    [basedOnSelection, dcfInputsPayload]
  );

  const basedOnProvenanceLabel = useMemo(() => {
    if (basedOnSelection === 'norm') {
      return formatFactProvenanceLabel(stockPayload?.oeps_normalized_provenance);
    }
    const factLabel = formatFactProvenanceLabel(
      (selectedBasedOnPayload?.net_profit_per_share?.provenance as FactProvenance | null) ?? null
    );
    if (factLabel) {
      return factLabel;
    }
    return formatComputedFactProvenanceLabel(
      (selectedBasedOnPayload?.depreciation_per_share?.provenance as ComputedFactProvenance | null) ??
        null
    );
  }, [basedOnSelection, selectedBasedOnPayload, stockPayload]);

  const growthRateProvenanceLabel = useMemo(() => {
    if (!stockPayload || !growthRateSelection || !Array.isArray(stockPayload.growth_rate_options)) {
      return null;
    }
    const option = stockPayload.growth_rate_options.find((item) => item?.key === growthRateSelection);
    return formatFactProvenanceLabel(option?.provenance ?? null);
  }, [growthRateSelection, stockPayload]);

  const handleSaveFairValue = async () => {
    if (stockId === null) {
      toast({
        title: 'Save failed',
        description: 'Unable to resolve stock ID.',
        variant: 'destructive',
      });
      return;
    }
    if (!Number.isFinite(totalValue) || totalValue <= 0) {
      toast({
        title: 'Invalid value',
        description: 'Total Value must be a positive number.',
        variant: 'destructive',
      });
      return;
    }
    setIsSavingFairValue(true);
    try {
      await apiClient.put(`/stocks/${stockId}/facts`, {
        metric_key: 'val.fair_value',
        value_numeric: totalValue,
      });
      toast({
        title: 'Saved',
        description: 'Fair Value updated from Total Value.',
      });
    } catch {
      toast({
        title: 'Save failed',
        description: 'Unable to update Fair Value.',
        variant: 'destructive',
      });
    } finally {
      setIsSavingFairValue(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <h1 className="text-xl font-semibold tracking-tight">DCF</h1>
        <TickerSearchBox destination="dcf" defaultValue={displayTicker} />
        {activeReportLabel ? (
          <div className="text-sm text-muted-foreground">{activeReportLabel}</div>
        ) : null}
      </div>

      <Card className="overflow-hidden border-border/70 bg-background/80">
        <div className="divide-y divide-border/70">
          <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-4 text-sm font-medium">
            <div className="flex flex-wrap items-center gap-3">
              <span>Based on</span>
              <div className="flex flex-wrap items-center gap-1 rounded-full border border-border/70 bg-muted/40 p-1">
                <button
                  type="button"
                  onClick={() => {
                    if (oepsNormalized === null) {
                      return;
                    }
                    setBasedOnSelection('norm');
                    const resolvedInputs = resolveDcfComponentInputs(dcfInputsPayload ?? {}, 'norm');
                    const hasResolvedInputs = [
                      resolvedInputs.netProfitPerShare,
                      resolvedInputs.depreciationPerShare,
                      resolvedInputs.capexPerShare,
                    ].some((value) => value !== '');
                    if (hasResolvedInputs) {
                      setNetProfitPerShare(resolvedInputs.netProfitPerShare);
                      setDepreciationPerShare(resolvedInputs.depreciationPerShare);
                      setCapexPerShare(resolvedInputs.capexPerShare);
                      setBasedOnOverride('');
                      return;
                    }
                    setBasedOnOverride(oepsNormalized.toFixed(3));
                  }}
                  className={[
                    'rounded-full px-4 py-1 text-sm',
                    basedOnSelection === 'norm'
                      ? 'bg-background font-semibold text-primary shadow-sm'
                      : 'text-muted-foreground',
                  ].join(' ')}
                >
                  OEPS Norm
                </button>
                {oepsSeries.map((item) => (
                  <button
                    key={item.year}
                    type="button"
                    onClick={() => {
                      setBasedOnSelection(item.year);
                      const resolvedInputs = resolveDcfComponentInputs(
                        dcfInputsPayload ?? {},
                        item.year
                      );
                      const hasResolvedInputs = [
                        resolvedInputs.netProfitPerShare,
                        resolvedInputs.depreciationPerShare,
                        resolvedInputs.capexPerShare,
                      ].some((value) => value !== '');
                      if (hasResolvedInputs) {
                        setNetProfitPerShare(resolvedInputs.netProfitPerShare);
                        setDepreciationPerShare(resolvedInputs.depreciationPerShare);
                        setCapexPerShare(resolvedInputs.capexPerShare);
                        setBasedOnOverride('');
                        return;
                      }
                      setBasedOnOverride(item.value.toFixed(3));
                    }}
                    className={[
                      'rounded-full px-4 py-1 text-sm',
                      basedOnSelection === item.year
                        ? 'bg-background font-semibold text-primary shadow-sm'
                        : 'text-muted-foreground',
                    ].join(' ')}
                  >
                    {item.year}
                  </button>
                ))}
              </div>
              {basedOnProvenanceLabel ? (
                <div className="text-xs font-normal text-muted-foreground">
                  {basedOnProvenanceLabel}
                </div>
              ) : null}
            </div>
            <div className="flex items-center gap-2 rounded-lg border border-border/70 bg-card/80 px-4 py-2">
              <span className="text-muted-foreground">$</span>
              <input
                value={basedOnInputValue}
                onChange={(event) => setBasedOnOverride(event.target.value)}
                onBlur={() => setBasedOnOverride((value) => value.trim())}
                inputMode="decimal"
                className="w-28 bg-transparent text-right text-base font-semibold outline-none"
              />
            </div>
          </div>

          <div className="grid gap-3 px-6 pb-2 text-xs text-muted-foreground md:grid-cols-3">
            <label className="flex items-center justify-between gap-2 rounded-xl border border-border/70 bg-muted/30 px-3 py-2">
              <span>Net profit / sh</span>
              <input
                value={netProfitPerShare}
                onChange={(event) => {
                  setNetProfitPerShare(event.target.value);
                  setBasedOnOverride('');
                }}
                inputMode="decimal"
                className="w-20 bg-transparent text-right text-sm font-medium text-foreground outline-none"
              />
            </label>
            <label className="flex items-center justify-between gap-2 rounded-xl border border-border/70 bg-muted/30 px-3 py-2">
              <span>Depreciation / sh</span>
              <input
                value={depreciationPerShare}
                onChange={(event) => {
                  setDepreciationPerShare(event.target.value);
                  setBasedOnOverride('');
                }}
                inputMode="decimal"
                className="w-20 bg-transparent text-right text-sm font-medium text-foreground outline-none"
              />
            </label>
            <label className="flex items-center justify-between gap-2 rounded-xl border border-border/70 bg-muted/30 px-3 py-2">
              <span>Cap’l spending / sh</span>
              <input
                value={capexPerShare}
                onChange={(event) => {
                  setCapexPerShare(event.target.value);
                  setBasedOnOverride('');
                }}
                inputMode="decimal"
                className="w-20 bg-transparent text-right text-sm font-medium text-foreground outline-none"
              />
            </label>
          </div>

          <div className="flex items-center justify-between gap-4 px-6 py-4 text-sm font-medium">
            <div className="flex items-center gap-2">
              Discount Rate %
              <HelpCircle className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="flex items-center overflow-hidden rounded-lg border border-border/70 bg-card/80">
              <button
                type="button"
                onClick={() => setDiscountRate((value) => clampNonNegative(value - 1))}
                className="px-4 py-2 text-muted-foreground"
              >
                -
              </button>
              <input
                value={discountRate}
                onChange={(event) => setDiscountRate(clampNonNegative(toNumber(event.target.value)))}
                inputMode="numeric"
                className="w-16 bg-transparent text-center text-base font-semibold outline-none"
              />
              <button
                type="button"
                onClick={() => setDiscountRate((value) => value + 1)}
                className="px-4 py-2 text-muted-foreground"
              >
                +
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between gap-4 px-6 py-4 text-sm font-medium">
            <div className="flex items-center gap-2">
              Tangible Book Value
              <HelpCircle className="h-4 w-4 text-muted-foreground" />
              <label className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <input
                  type="checkbox"
                  className="h-5 w-5 rounded-md border border-border/70 accent-primary"
                />
                Add to Fair Value
              </label>
            </div>
            <div className="rounded-lg border border-border/70 bg-card/80 px-4 py-2 text-base font-semibold">
              $ 29.91
            </div>
          </div>

          <div className="grid gap-4 px-6 py-6 lg:grid-cols-2">
            <div className="rounded-2xl border border-border/70 bg-card/80 p-5">
              <div className="flex items-center justify-center gap-2 text-sm font-semibold">
                Growth Stage
                <HelpCircle className="h-4 w-4 text-muted-foreground" />
              </div>
              <div className="mt-5 grid gap-4 text-sm font-medium">
                <div className="flex items-center justify-between">
                  <span>Years</span>
                  <div className="flex items-center overflow-hidden rounded-lg border border-border/70 bg-background">
                    <button
                      type="button"
                      onClick={() => setGrowthYears((value) => clampNonNegative(value - 1))}
                      className="px-4 py-2 text-muted-foreground"
                    >
                      -
                    </button>
                    <input
                      value={growthYears}
                      onChange={(event) =>
                        setGrowthYears(clampNonNegative(toNumber(event.target.value)))
                      }
                      inputMode="numeric"
                      className="w-14 bg-transparent text-center text-base font-semibold outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setGrowthYears((value) => value + 1)}
                      className="px-4 py-2 text-muted-foreground"
                    >
                      +
                    </button>
                  </div>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>Growth Rate</span>
                  <div className="flex flex-col items-end gap-2">
                    <div className="flex items-center overflow-hidden rounded-lg border border-border/70 bg-background">
                      <button
                        type="button"
                        onClick={() => {
                          setGrowthRateSelection(null);
                          setGrowthRate((value) => clampNonNegative(value - 1));
                        }}
                        className="px-4 py-2 text-muted-foreground"
                      >
                        -
                      </button>
                      <input
                        value={growthRate}
                        onChange={(event) => {
                          setGrowthRateSelection(null);
                          setGrowthRate(clampNonNegative(toNumber(event.target.value)));
                        }}
                        inputMode="numeric"
                        className="w-14 bg-transparent text-center text-base font-semibold outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          setGrowthRateSelection(null);
                          setGrowthRate((value) => value + 1);
                        }}
                        className="px-4 py-2 text-muted-foreground"
                      >
                        +
                      </button>
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      {growthRateOptions.map((option) => (
                        <button
                          key={option.key}
                          type="button"
                          onClick={() => {
                            setGrowthRateSelection(option.key);
                            setGrowthRate(option.value);
                          }}
                          className={[
                            'rounded-full border border-border/70 px-3 py-1 text-xs',
                            growthRateSelection === option.key
                              ? 'bg-background font-semibold text-primary shadow-sm'
                              : 'text-muted-foreground',
                          ].join(' ')}
                        >
                          {option.label} {option.value.toFixed(1)}
                        </button>
                      ))}
                    </div>
                    {growthRateProvenanceLabel ? (
                      <div className="text-xs font-normal text-muted-foreground">
                        {growthRateProvenanceLabel}
                      </div>
                    ) : null}
                  </div>
                </div>
                <div className="flex items-center justify-between text-base font-semibold">
                  <span>Growth Value</span>
                  <span>{hasResolvedStockDefaults ? `$ ${formatMoney(growthValue)}` : '—'}</span>
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-border/70 bg-card/80 p-5">
              <div className="flex items-center justify-center gap-2 text-sm font-semibold">
                Terminal Stage
                <HelpCircle className="h-4 w-4 text-muted-foreground" />
              </div>
              <div className="mt-5 grid gap-4 text-sm font-medium">
                <div className="flex items-center justify-between">
                  <span>Years</span>
                  <div className="flex items-center overflow-hidden rounded-lg border border-border/70 bg-background">
                    <button
                      type="button"
                      onClick={() => setTerminalYears((value) => clampNonNegative(value - 1))}
                      className="px-4 py-2 text-muted-foreground"
                    >
                      -
                    </button>
                    <input
                      value={terminalYears}
                      onChange={(event) =>
                        setTerminalYears(clampNonNegative(toNumber(event.target.value)))
                      }
                      inputMode="numeric"
                      className="w-14 bg-transparent text-center text-base font-semibold outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setTerminalYears((value) => value + 1)}
                      className="px-4 py-2 text-muted-foreground"
                    >
                      +
                    </button>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span>Growth Rate</span>
                  <div className="flex items-center overflow-hidden rounded-lg border border-border/70 bg-background">
                    <button
                      type="button"
                      onClick={() => setTerminalRate((value) => clampNonNegative(value - 1))}
                      className="px-4 py-2 text-muted-foreground"
                    >
                      -
                    </button>
                    <input
                      value={terminalRate}
                      onChange={(event) =>
                        setTerminalRate(clampNonNegative(toNumber(event.target.value)))
                      }
                      inputMode="numeric"
                      className="w-14 bg-transparent text-center text-base font-semibold outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setTerminalRate((value) => value + 1)}
                      className="px-4 py-2 text-muted-foreground"
                    >
                      +
                    </button>
                  </div>
                </div>
                <div className="flex items-center justify-between text-base font-semibold">
                  <span>Terminal Value</span>
                  <span>{hasResolvedStockDefaults ? `$ ${formatMoney(terminalValue)}` : '—'}</span>
                </div>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-4 text-sm font-medium">
            <div className="flex items-center gap-3">
              <span>Stock Price</span>
              <div className="flex items-center gap-2 rounded-lg border border-border/70 bg-card/80 px-4 py-2">
                <span className="text-muted-foreground">$</span>
                <input
                  value={latestPrice !== null ? latestPrice.toFixed(2) : manualPrice}
                  onChange={(event) => setManualPrice(event.target.value)}
                  inputMode="decimal"
                  disabled={latestPrice !== null}
                  className="w-28 bg-transparent text-right text-base font-semibold outline-none"
                />
                {priceUpdatedLabel && latestPrice !== null && (
                  <span className="text-xs text-muted-foreground">Updated {priceUpdatedLabel}</span>
                )}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-4 text-base font-semibold">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-muted-foreground">Total Value</span>
                <span>{hasResolvedStockDefaults ? `$ ${formatMoney(totalValue)}` : '—'}</span>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleSaveFairValue}
                  disabled={isSavingFairValue || !hasResolvedStockDefaults}
                  type="button"
                >
                  Save
                </Button>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-muted-foreground">Safe Margin</span>
                <span>
                  {safeMarginPct === null
                    ? '—'
                    : `${safeMarginPct.toLocaleString('en-US', {
                        minimumFractionDigits: 1,
                        maximumFractionDigits: 1,
                      })}%`}
                </span>
              </div>
            </div>
          </div>

        </div>
      </Card>
    </div>
  );
}
