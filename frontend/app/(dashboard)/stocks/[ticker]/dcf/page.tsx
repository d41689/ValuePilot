'use client';

import { useParams } from 'next/navigation';
import { HelpCircle } from 'lucide-react';

import TickerSearchBox from '@/components/TickerSearchBox';
import { Card } from '@/components/ui/card';
import { normalizeTicker } from '@/lib/stockRoutes';

export default function StockDcfPage() {
  const params = useParams();
  const tickerParam = Array.isArray(params?.ticker) ? params.ticker[0] : params?.ticker;
  const displayTicker = normalizeTicker((tickerParam || '').toString());

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <h1 className="text-xl font-semibold tracking-tight">DCF</h1>
        <TickerSearchBox destination="dcf" defaultValue={displayTicker} />
      </div>

      <Card className="overflow-hidden border-border/70 bg-background/80">
        <div className="divide-y divide-border/70">
          <div className="flex items-center justify-between px-6 py-4 text-sm font-medium">
            <span>Stock Price</span>
            <div className="rounded-lg border border-border/70 bg-card/80 px-4 py-2 text-base font-semibold text-foreground">
              $ 451.14
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
            <div className="rounded-lg border border-border/70 bg-card/80 px-4 py-2 text-base font-semibold">
              $ 14.550
            </div>
          </div>

          <div className="flex items-center justify-between gap-4 px-6 py-4 text-sm font-medium">
            <div className="flex items-center gap-2">
              Discount Rate %
              <HelpCircle className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="flex items-center overflow-hidden rounded-lg border border-border/70 bg-card/80">
              <button className="px-4 py-2 text-muted-foreground">-</button>
              <div className="px-6 py-2 text-base font-semibold">11</div>
              <button className="px-4 py-2 text-muted-foreground">+</button>
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
                    <button className="px-4 py-2 text-muted-foreground">-</button>
                    <div className="px-6 py-2 text-base font-semibold">10</div>
                    <button className="px-4 py-2 text-muted-foreground">+</button>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span>Growth Rate</span>
                  <div className="flex items-center overflow-hidden rounded-lg border border-border/70 bg-background">
                    <button className="px-4 py-2 text-muted-foreground">-</button>
                    <div className="px-6 py-2 text-base font-semibold">20</div>
                    <button className="px-4 py-2 text-muted-foreground">+</button>
                  </div>
                </div>
                <div className="flex items-center justify-between text-base font-semibold">
                  <span>Growth Value</span>
                  <span>$ 229.04</span>
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
                    <button className="px-4 py-2 text-muted-foreground">-</button>
                    <div className="px-6 py-2 text-base font-semibold">10</div>
                    <button className="px-4 py-2 text-muted-foreground">+</button>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span>Growth Rate</span>
                  <div className="flex items-center overflow-hidden rounded-lg border border-border/70 bg-background">
                    <button className="px-4 py-2 text-muted-foreground">-</button>
                    <div className="px-6 py-2 text-base font-semibold">4</div>
                    <button className="px-4 py-2 text-muted-foreground">+</button>
                  </div>
                </div>
                <div className="flex items-center justify-between text-base font-semibold">
                  <span>Terminal Value</span>
                  <span>$ 225.65</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
