import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

type StockSummaryCardProps = {
  companyName: string;
  ticker: string;
  exchange?: string | null;
  price?: number | null;
  pe?: number | null;
  activeReportDate?: string | null;
  activeReportDocumentId?: number | null;
  priceProvenanceLabel?: string | null;
  peProvenanceLabel?: string | null;
  actualConflictCount?: number;
  actualConflictItems?: Array<{
    metricLabel: string;
    periodLabel: string;
    latestValueLabel: string;
    previousValueLabel: string;
    latestReportLabel: string | null;
    previousReportLabel: string | null;
    observationCount: number;
  }>;
  className?: string;
};

const formatNumber = (value: number | null | undefined, digits: number) => {
  if (value === null || value === undefined) {
    return '—';
  }
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
};

export default function StockSummaryCard({
  companyName,
  ticker,
  exchange,
  price,
  pe,
  activeReportDate,
  activeReportDocumentId,
  priceProvenanceLabel,
  peProvenanceLabel,
  actualConflictCount = 0,
  actualConflictItems = [],
  className,
}: StockSummaryCardProps) {
  return (
    <Card className={cn('border-border/70 bg-background/80', className)}>
      <CardHeader>
        <CardTitle>{companyName}</CardTitle>
        <div className="text-sm text-muted-foreground">
          {(exchange || '—').toUpperCase()}:{ticker.toUpperCase()}
        </div>
        {activeReportDate || activeReportDocumentId ? (
          <div className="text-xs text-muted-foreground">
            Active report
            {activeReportDate ? ` · ${activeReportDate}` : ''}
            {Number.isInteger(activeReportDocumentId) ? ` · doc #${activeReportDocumentId}` : ''}
          </div>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-border/60 bg-card/80 p-4">
          <div className="text-xs uppercase text-muted-foreground">现价</div>
          <div className="mt-2 text-2xl font-semibold">${formatNumber(price, 2)}</div>
          {priceProvenanceLabel ? (
            <div className="mt-2 text-xs text-muted-foreground">{priceProvenanceLabel}</div>
          ) : null}
        </div>
        <div className="rounded-xl border border-border/60 bg-card/80 p-4">
          <div className="text-xs uppercase text-muted-foreground">P/E</div>
          <div className="mt-2 text-2xl font-semibold">{formatNumber(pe, 1)}</div>
          {peProvenanceLabel ? (
            <div className="mt-2 text-xs text-muted-foreground">{peProvenanceLabel}</div>
          ) : null}
        </div>
        </div>
        <div className="rounded-xl border border-amber-300/60 bg-amber-50/60 p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs uppercase text-amber-900/80">Historical Value Conflicts</div>
            <div className="text-sm font-semibold text-amber-950">
              {actualConflictCount > 0 ? `${actualConflictCount} detected` : 'None detected'}
            </div>
          </div>
          {actualConflictCount > 0 ? (
            <div className="mt-3 space-y-3">
              {actualConflictItems.map((item) => (
                <div
                  key={`${item.metricLabel}-${item.periodLabel}`}
                  className="rounded-lg border border-amber-300/50 bg-white/70 p-3"
                >
                  <div className="text-sm font-medium text-foreground">{item.metricLabel}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{item.periodLabel}</div>
                  <div className="mt-2 text-sm text-foreground">
                    {item.latestValueLabel} vs {item.previousValueLabel}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {item.latestReportLabel ? `Latest report ${item.latestReportLabel}` : 'Latest report'}
                    {item.previousReportLabel ? ` · Previous report ${item.previousReportLabel}` : ''}
                    {item.observationCount > 2 ? ` · ${item.observationCount} report versions` : ''}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-2 text-sm text-amber-950/80">
              No cross-report actual-value conflicts detected for this stock.
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
