'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import { HelpCircle } from 'lucide-react';
import axios from 'axios';

import TickerSearchBox from '@/components/TickerSearchBox';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { toast } from '@/components/ui/use-toast';
import { normalizeTicker } from '@/lib/stockRoutes';
import { computeGrowthValue, computeTerminalValue, computeTotalValue } from '@/lib/dcfMath';
import apiClient from '@/lib/api/client';

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

export default function StockDcfPage() {
  const params = useParams();
  const tickerParam = Array.isArray(params?.ticker) ? params.ticker[0] : params?.ticker;
  const displayTicker = normalizeTicker((tickerParam || '').toString());

  const [latestPrice, setLatestPrice] = useState<number | null>(null);
  const [latestPriceUpdatedAt, setLatestPriceUpdatedAt] = useState<string | null>(null);
  const [manualPrice, setManualPrice] = useState('');
  const [stockId, setStockId] = useState<number | null>(null);
  const [isSavingFairValue, setIsSavingFairValue] = useState(false);
  const [netProfitPerShare, setNetProfitPerShare] = useState('12.00');
  const [depreciationPerShare, setDepreciationPerShare] = useState('3.00');
  const [capexPerShare, setCapexPerShare] = useState('0.45');
  const [basedOnOverride, setBasedOnOverride] = useState('');
  const [oepsSeries, setOepsSeries] = useState<Array<{ year: number; value: number }>>([]);
  const [oepsNormalized, setOepsNormalized] = useState<number | null>(null);
  const [basedOnSelection, setBasedOnSelection] = useState<'norm' | number>('norm');
  const [growthRateOptions, setGrowthRateOptions] = useState<
    Array<{ key: string; label: string; value: number }>
  >([]);
  const [growthRateSelection, setGrowthRateSelection] = useState<string | null>(null);

  const [discountRate, setDiscountRate] = useState(10);
  const [growthYears, setGrowthYears] = useState(10);
  const [growthRate, setGrowthRate] = useState(20);
  const [terminalYears, setTerminalYears] = useState(1000);
  const [terminalRate, setTerminalRate] = useState(4);

  useEffect(() => {
    if (!displayTicker) {
      return;
    }
    let isActive = true;
    setLatestPrice(null);
    setLatestPriceUpdatedAt(null);
    setManualPrice('');
    setStockId(null);
    const hydrate = async () => {
      try {
        const response = await apiClient.get(`/stocks/by_ticker/${encodeURIComponent(displayTicker)}`);
        if (!isActive) {
          return;
        }
        const payload = response.data ?? {};
        if (typeof payload.id === 'number') {
          setStockId(payload.id);
        }
        const fetchedLatest = payload.latest_price;
        if (typeof fetchedLatest === 'number' && Number.isFinite(fetchedLatest)) {
          setLatestPrice(fetchedLatest);
          setLatestPriceUpdatedAt(payload.latest_price_updated_at ?? null);
        }
        const normalized = payload?.oeps_normalized;
        const series = Array.isArray(payload?.oeps_series)
          ? payload.oeps_series
              .filter(
                (item: { year?: number; value?: number }) =>
                  typeof item?.year === 'number' && typeof item?.value === 'number'
              )
              .slice(0, 6)
          : [];
        const rateOptions = Array.isArray(payload?.growth_rate_options)
          ? payload.growth_rate_options.filter(
              (item: { key?: string; label?: string; value?: number }) =>
                typeof item?.key === 'string' &&
                typeof item?.label === 'string' &&
                typeof item?.value === 'number'
            )
          : [];
        setOepsSeries(series);
        setGrowthRateOptions(rateOptions);
        if (typeof normalized === 'number' && Number.isFinite(normalized)) {
          setOepsNormalized(normalized);
          setBasedOnSelection('norm');
          setBasedOnOverride((prev) => (prev.trim() ? prev : normalized.toFixed(3)));
        }
        if (series.length > 0 && (typeof normalized !== 'number' || !Number.isFinite(normalized))) {
          setBasedOnSelection(series[0].year);
          setBasedOnOverride(series[0].value.toFixed(3));
        }
        if (rateOptions.length > 0) {
          const lowest = rateOptions.reduce((min, current) =>
            current.value < min.value ? current : min
          );
          setGrowthRateSelection(lowest.key);
          setGrowthRate(lowest.value);
        }
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
            if (typeof refreshed.data?.id === 'number') {
              setStockId(refreshed.data.id);
            }
            const refreshedPrice = refreshed.data?.latest_price;
            if (typeof refreshedPrice === 'number' && Number.isFinite(refreshedPrice)) {
              setLatestPrice(refreshedPrice);
              setLatestPriceUpdatedAt(refreshed.data?.latest_price_updated_at ?? null);
            }
          } catch {
            // best-effort refresh; keep existing price if refresh fails
          }
        }
      } catch (err) {
        if (!isActive) {
          return;
        }
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
    : computedBasedOn;

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
            </div>
            <div className="flex items-center gap-2 rounded-lg border border-border/70 bg-card/80 px-4 py-2">
              <span className="text-muted-foreground">$</span>
              <input
                value={basedOnOverride.trim() ? basedOnOverride : formatInputMoney(computedBasedOn)}
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
                onChange={(event) => setNetProfitPerShare(event.target.value)}
                inputMode="decimal"
                className="w-20 bg-transparent text-right text-sm font-medium text-foreground outline-none"
              />
            </label>
            <label className="flex items-center justify-between gap-2 rounded-xl border border-border/70 bg-muted/30 px-3 py-2">
              <span>Depreciation / sh</span>
              <input
                value={depreciationPerShare}
                onChange={(event) => setDepreciationPerShare(event.target.value)}
                inputMode="decimal"
                className="w-20 bg-transparent text-right text-sm font-medium text-foreground outline-none"
              />
            </label>
            <label className="flex items-center justify-between gap-2 rounded-xl border border-border/70 bg-muted/30 px-3 py-2">
              <span>Cap’l spending / sh</span>
              <input
                value={capexPerShare}
                onChange={(event) => setCapexPerShare(event.target.value)}
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
                  </div>
                </div>
                <div className="flex items-center justify-between text-base font-semibold">
                  <span>Growth Value</span>
                  <span>$ {formatMoney(growthValue)}</span>
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
                  <span>$ {formatMoney(terminalValue)}</span>
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
                <span>$ {formatMoney(totalValue)}</span>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleSaveFairValue}
                  disabled={isSavingFairValue}
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
