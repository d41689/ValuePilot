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
      <CardContent className="grid gap-4 sm:grid-cols-2">
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
      </CardContent>
    </Card>
  );
}
