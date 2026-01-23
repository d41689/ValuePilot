'use client';

import { useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import { HelpCircle } from 'lucide-react';

import TickerSearchBox from '@/components/TickerSearchBox';
import { Card } from '@/components/ui/card';
import { normalizeTicker } from '@/lib/stockRoutes';
import { computeGrowthValue, computeTerminalValue, computeTotalValue } from '@/lib/dcfMath';

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

  const [stockPrice, setStockPrice] = useState('451.14');
  const [netProfitPerShare, setNetProfitPerShare] = useState('12.00');
  const [depreciationPerShare, setDepreciationPerShare] = useState('3.00');
  const [capexPerShare, setCapexPerShare] = useState('0.45');
  const [basedOnOverride, setBasedOnOverride] = useState('');

  const [discountRate, setDiscountRate] = useState(10);
  const [growthYears, setGrowthYears] = useState(10);
  const [growthRate, setGrowthRate] = useState(20);
  const [terminalYears, setTerminalYears] = useState(1000);
  const [terminalRate, setTerminalRate] = useState(4);

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

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <h1 className="text-xl font-semibold tracking-tight">DCF</h1>
        <TickerSearchBox destination="dcf" defaultValue={displayTicker} />
      </div>

      <Card className="overflow-hidden border-border/70 bg-background/80">
        <div className="divide-y divide-border/70">
          <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-4 text-sm font-medium">
            <span>Stock Price</span>
            <div className="flex items-center gap-2 rounded-lg border border-border/70 bg-card/80 px-4 py-2">
              <span className="text-muted-foreground">$</span>
              <input
                value={stockPrice}
                onChange={(event) => setStockPrice(event.target.value)}
                inputMode="decimal"
                className="w-28 bg-transparent text-right text-base font-semibold outline-none"
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-4 text-sm font-medium">
            <div className="flex flex-wrap items-center gap-3">
              <span>Based on</span>
              <div className="flex items-center gap-1 rounded-full border border-border/70 bg-muted/40 p-1">
                <button className="rounded-full bg-background px-4 py-1 text-sm font-semibold text-primary shadow-sm">
                  EPS w/o NRI
                </button>
                <button className="rounded-full px-4 py-1 text-sm text-muted-foreground">FCF</button>
                <button className="rounded-full px-4 py-1 text-sm text-muted-foreground">
                  Adjusted Dividend
                </button>
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
                <div className="flex items-center justify-between">
                  <span>Growth Rate</span>
                  <div className="flex items-center overflow-hidden rounded-lg border border-border/70 bg-background">
                    <button
                      type="button"
                      onClick={() => setGrowthRate((value) => clampNonNegative(value - 1))}
                      className="px-4 py-2 text-muted-foreground"
                    >
                      -
                    </button>
                    <input
                      value={growthRate}
                      onChange={(event) =>
                        setGrowthRate(clampNonNegative(toNumber(event.target.value)))
                      }
                      inputMode="numeric"
                      className="w-14 bg-transparent text-center text-base font-semibold outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setGrowthRate((value) => value + 1)}
                      className="px-4 py-2 text-muted-foreground"
                    >
                      +
                    </button>
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

          <div className="flex items-center justify-between px-6 py-4 text-base font-semibold">
            <span>Total Value</span>
            <span>$ {formatMoney(totalValue)}</span>
          </div>
        </div>
      </Card>
    </div>
  );
}
