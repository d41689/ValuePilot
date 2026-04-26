'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Loader2 } from 'lucide-react';

import apiClient from '@/lib/api/client';
import documentReviewHelpers from '@/lib/documentReview';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';

type ReviewSummaryMetric = {
  metric_key?: string | null;
  label: string;
  display_value?: string | null;
  value_numeric?: number | null;
  unit?: string | null;
  key?: string;
  displayValue?: string;
};

type ReviewRatingMetric = {
  key: string;
  label: string;
  displayValue: string;
};

type ReviewQualityMetric = ReviewRatingMetric;

type ReviewTargetRangeMetric = {
  key: string;
  label: string;
  displayValue: string;
};

type ReviewCapitalStructureMetric = ReviewTargetRangeMetric;

type ReviewProjectionTable = {
  columns: Array<{
    key: string;
    label: string;
  }>;
  rows: Array<{
    key: string;
    label: string;
    cells: Array<{
      key: string;
      label: string;
      displayValue: string;
      isEstimate?: boolean;
    }>;
  }>;
};

type ReviewInstitutionalDecisionTable = ReviewProjectionTable;

type ReviewCurrentPositionTable = ReviewProjectionTable & {
  unit: string | null;
  rows: Array<ReviewProjectionTable['rows'][number] & { section: string }>;
};

type ReviewAnnualFinancialsTable = {
  columns: ReviewProjectionTable['columns'];
  rows: Array<ReviewProjectionTable['rows'][number] & { section?: string | null }>;
};

type ReviewParserTable = ReviewProjectionTable & {
  unit: string | null;
};

type ReviewNarrativeCard = {
  key: string;
  title: string;
  body: string;
  meta: string | null;
};

type ReviewGroup = {
  key: string;
  label: string;
  items: Array<Record<string, unknown>>;
};

type ReviewEvidenceItem = {
  mapping_id: string;
  value_text: string | null;
  period_end_date: string | null;
};

type ReviewPayload = {
  document: {
    id: number;
    file_name: string;
    ticker: string | null;
    exchange: string | null;
    company_name: string | null;
    report_date: string | null;
  };
  summary: Record<string, ReviewSummaryMetric | null>;
  annual_rates: Record<string, unknown> | null;
  quarterly_sales: Record<string, unknown> | null;
  earnings_per_share: Record<string, unknown> | null;
  quarterly_dividends_paid: Record<string, unknown> | null;
  annual_financials: Record<string, unknown> | null;
  capital_structure: Record<string, unknown> | null;
  current_position: Record<string, unknown> | null;
  groups: ReviewGroup[];
};

type EvidencePayload = {
  document_id: number;
  evidence: ReviewEvidenceItem[];
};

type ApiError = {
  response?: {
    data?: {
      detail?: string | { value?: string };
    };
  };
  message?: string;
};

const {
  buildDocumentReviewSummary,
  buildDocumentReviewRatings,
  buildDocumentReviewQuality,
  buildDocumentReviewNarrativeCards,
  buildDocumentReviewTargetRange,
  buildDocumentReviewProjections,
  buildDocumentReviewInstitutionalDecisions,
  buildDocumentReviewAnnualFinancials,
  buildDocumentReviewAnnualRates,
  buildDocumentReviewQuarterlyTable,
  buildDocumentReviewCapitalStructure,
  buildDocumentReviewCurrentPosition,
} = documentReviewHelpers;

function ReviewTableCard({
  title,
  table,
  minWidth = 'min-w-[560px]',
}: {
  title: string;
  table: ReviewParserTable;
  minWidth?: string;
}) {
  if (!table.rows.length) {
    return null;
  }

  return (
    <Card className="border-border/60 bg-card/90">
      <CardContent className="p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="font-display text-xl font-semibold tracking-tight text-foreground">
            {title}
          </h2>
          {table.unit ? (
            <div className="text-xs uppercase text-muted-foreground">
              {table.unit.replaceAll('_', ' ')}
            </div>
          ) : null}
        </div>

        <div className="mt-5 overflow-x-auto rounded-lg border border-border/60 bg-background/70">
          <table className={`w-full ${minWidth} border-collapse text-sm`}>
            <thead>
              <tr className="border-b border-border/60">
                <th className="w-40 px-4 py-3 text-left font-medium text-muted-foreground" />
                {table.columns.map((column) => (
                  <th
                    key={column.key}
                    className="px-4 py-3 text-right text-xs font-medium uppercase text-muted-foreground"
                  >
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row) => (
                <tr key={row.key} className="border-b border-border/60 last:border-0">
                  <th className="px-4 py-3 text-left font-semibold text-foreground">
                    {row.label}
                  </th>
                  {row.cells.map((cell) => (
                    <td
                      key={cell.key}
                      className={`px-4 py-3 text-right ${
                        cell.isEstimate
                          ? 'font-semibold text-red-600'
                          : 'font-semibold text-foreground'
                      }`}
                    >
                      {cell.displayValue}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function NarrativeCard({ card }: { card: ReviewNarrativeCard }) {
  return (
    <Card className="border-border/60 bg-card/90">
      <CardContent className="p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="font-display text-xl font-semibold tracking-tight text-foreground">
            {card.title}
          </h2>
          {card.meta ? <div className="text-xs uppercase text-muted-foreground">{card.meta}</div> : null}
        </div>
        <p className="mt-5 whitespace-pre-wrap text-sm leading-7 text-foreground">{card.body}</p>
      </CardContent>
    </Card>
  );
}

function getErrorMessage(error: unknown, fallback: string) {
  if (typeof error === 'object' && error !== null) {
    const apiError = error as ApiError;
    const detail = apiError.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (detail?.value) return detail.value;
    return apiError.message ?? fallback;
  }
  return fallback;
}

function formatDateOnly(iso: string | null) {
  if (!iso) return '—';
  const dt = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleDateString();
}

export default function DocumentReviewPage() {
  const params = useParams<{ id: string }>();
  const documentId = params?.id ?? '';

  const reviewQuery = useQuery({
    queryKey: ['document-review', documentId],
    enabled: documentId.length > 0,
    queryFn: async () => {
      const res = await apiClient.get(`/documents/${documentId}/review`);
      return res.data as ReviewPayload;
    },
  });

  const evidenceQuery = useQuery({
    queryKey: ['document-review-evidence', documentId],
    enabled: documentId.length > 0,
    queryFn: async () => {
      const res = await apiClient.get(`/documents/${documentId}/evidence`);
      return res.data as EvidencePayload;
    },
  });

  const summaryMetrics = useMemo<ReviewSummaryMetric[]>(
    () => buildDocumentReviewSummary(reviewQuery.data?.summary ?? {}),
    [reviewQuery.data?.summary]
  );
  const ratingMetrics = useMemo<ReviewRatingMetric[]>(
    () =>
      buildDocumentReviewRatings(
        reviewQuery.data?.groups ?? [],
        evidenceQuery.data?.evidence ?? []
    ),
    [reviewQuery.data?.groups, evidenceQuery.data?.evidence]
  );
  const qualityMetrics = useMemo<ReviewQualityMetric[]>(
    () => buildDocumentReviewQuality(reviewQuery.data?.groups ?? []),
    [reviewQuery.data?.groups]
  );
  const narrativeCards = useMemo<ReviewNarrativeCard[]>(
    () => buildDocumentReviewNarrativeCards(evidenceQuery.data?.evidence ?? []),
    [evidenceQuery.data?.evidence]
  );
  const targetRangeMetrics = useMemo<ReviewTargetRangeMetric[]>(
    () => buildDocumentReviewTargetRange(reviewQuery.data?.groups ?? []),
    [reviewQuery.data?.groups]
  );
  const capitalStructureMetrics = useMemo<ReviewCapitalStructureMetric[]>(
    () =>
      buildDocumentReviewCapitalStructure(
        reviewQuery.data?.groups ?? [],
        reviewQuery.data?.capital_structure ?? null
      ),
    [reviewQuery.data?.groups, reviewQuery.data?.capital_structure]
  );
  const projectionTable = useMemo<ReviewProjectionTable>(
    () => buildDocumentReviewProjections(reviewQuery.data?.groups ?? []),
    [reviewQuery.data?.groups]
  );
  const institutionalDecisionTable = useMemo<ReviewInstitutionalDecisionTable>(
    () => buildDocumentReviewInstitutionalDecisions(reviewQuery.data?.groups ?? []),
    [reviewQuery.data?.groups]
  );
  const annualRatesTable = useMemo<ReviewParserTable>(
    () => buildDocumentReviewAnnualRates(reviewQuery.data?.annual_rates ?? null),
    [reviewQuery.data?.annual_rates]
  );
  const quarterlySalesTable = useMemo<ReviewParserTable>(
    () => buildDocumentReviewQuarterlyTable(reviewQuery.data?.quarterly_sales ?? null),
    [reviewQuery.data?.quarterly_sales]
  );
  const earningsPerShareTable = useMemo<ReviewParserTable>(
    () => buildDocumentReviewQuarterlyTable(reviewQuery.data?.earnings_per_share ?? null),
    [reviewQuery.data?.earnings_per_share]
  );
  const quarterlyDividendsPaidTable = useMemo<ReviewParserTable>(
    () => buildDocumentReviewQuarterlyTable(reviewQuery.data?.quarterly_dividends_paid ?? null),
    [reviewQuery.data?.quarterly_dividends_paid]
  );
  const currentPositionTable = useMemo<ReviewCurrentPositionTable>(
    () => buildDocumentReviewCurrentPosition(reviewQuery.data?.current_position ?? null),
    [reviewQuery.data?.current_position]
  );
  const annualFinancialsTable = useMemo<ReviewAnnualFinancialsTable>(
    () =>
      buildDocumentReviewAnnualFinancials(
        reviewQuery.data?.groups ?? [],
        reviewQuery.data?.annual_financials ?? null
      ),
    [reviewQuery.data?.groups, reviewQuery.data?.annual_financials]
  );

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-500">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <Button asChild variant="ghost" size="sm" className="px-0">
            <Link href="/documents">
              <ArrowLeft className="h-4 w-4" />
              Documents
            </Link>
          </Button>
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">Report Review</h1>
            <p className="text-sm text-muted-foreground">
              {reviewQuery.data
                ? `${reviewQuery.data.document.file_name} · ${
                    reviewQuery.data.document.ticker ?? 'Unlinked'
                  } · ${formatDateOnly(reviewQuery.data.document.report_date)}`
                : 'Loading document review data...'}
            </p>
          </div>
        </div>
      </div>

      {reviewQuery.isLoading ? (
        <Card className="border-border/60 bg-card/85">
          <CardContent className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading review data...
          </CardContent>
        </Card>
      ) : reviewQuery.error ? (
        <Card className="border-rose-200 bg-rose-50/70">
          <CardContent className="p-6 text-sm text-rose-800">
            {getErrorMessage(reviewQuery.error, 'Failed to load document review.')}
          </CardContent>
        </Card>
      ) : (
        <>
          <Card className="border-border/60 bg-card/90">
            <CardContent className="p-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    {reviewQuery.data?.document.exchange ? (
                      <Badge variant="secondary">{reviewQuery.data.document.exchange}</Badge>
                    ) : null}
                    {reviewQuery.data?.document.ticker ? (
                      <Badge variant="outline">{reviewQuery.data.document.ticker}</Badge>
                    ) : null}
                  </div>
                  <div className="space-y-1">
                    <h2 className="font-display text-2xl font-semibold tracking-tight text-foreground">
                      {reviewQuery.data?.document.company_name ||
                        reviewQuery.data?.document.ticker ||
                        'Unlinked document'}
                    </h2>
                    <p className="text-sm text-muted-foreground">
                      {reviewQuery.data?.document.file_name}
                    </p>
                  </div>
                </div>
                <div className="min-w-[160px] text-sm text-muted-foreground">
                  <div className="text-xs uppercase">Report Date</div>
                  <div className="mt-1 font-medium text-foreground">
                    {formatDateOnly(reviewQuery.data?.document.report_date ?? null)}
                  </div>
                </div>
              </div>

              <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {summaryMetrics.map((metric) => (
                  <div
                    key={metric.key}
                    className="rounded-lg border border-border/60 bg-background/70 px-4 py-3"
                  >
                    <div className="text-xs uppercase text-muted-foreground">{metric.label}</div>
                    <div className="mt-2 text-lg font-semibold text-foreground">
                      {metric.displayValue ?? '—'}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
          <Card className="border-border/60 bg-card/90">
            <CardContent className="p-6">
              <div>
                <h2 className="font-display text-xl font-semibold tracking-tight text-foreground">
                  Rating
                </h2>
              </div>

              <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {ratingMetrics.map((rating) => (
                  <div
                    key={rating.key}
                    className="rounded-lg border border-border/60 bg-background/70 px-4 py-3"
                  >
                    <div className="text-xs uppercase text-muted-foreground">{rating.label}</div>
                    <div className="mt-2 text-lg font-semibold text-foreground">
                      {rating.displayValue}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
          <Card className="border-border/60 bg-card/90">
            <CardContent className="p-6">
              <div>
                <h2 className="font-display text-xl font-semibold tracking-tight text-foreground">
                  Quality
                </h2>
              </div>

              <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {qualityMetrics.map((quality) => (
                  <div
                    key={quality.key}
                    className="rounded-lg border border-border/60 bg-background/70 px-4 py-3"
                  >
                    <div className="text-xs uppercase text-muted-foreground">{quality.label}</div>
                    <div className="mt-2 text-lg font-semibold text-foreground">
                      {quality.displayValue}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
          <Card className="border-border/60 bg-card/90">
            <CardContent className="p-6">
              <div>
                <h2 className="font-display text-xl font-semibold tracking-tight text-foreground">
                  18-Month Target Price Range
                </h2>
              </div>

              <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {targetRangeMetrics.map((metric) => (
                  <div
                    key={metric.key}
                    className="rounded-lg border border-border/60 bg-background/70 px-4 py-3"
                  >
                    <div className="text-xs uppercase text-muted-foreground">{metric.label}</div>
                    <div className="mt-2 text-lg font-semibold text-foreground">
                      {metric.displayValue}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
          <Card className="border-border/60 bg-card/90">
            <CardContent className="p-6">
              <div>
                <h2 className="font-display text-xl font-semibold tracking-tight text-foreground">
                  PROJECTIONS
                </h2>
              </div>

              <div className="mt-5 overflow-x-auto rounded-lg border border-border/60 bg-background/70">
                <table className="w-full min-w-[520px] border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-border/60">
                      <th className="w-24 px-4 py-3 text-left font-medium text-muted-foreground" />
                      {projectionTable.columns.map((column) => (
                        <th
                          key={column.key}
                          className="px-4 py-3 text-right text-xs font-medium uppercase text-muted-foreground"
                        >
                          {column.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {projectionTable.rows.map((row) => (
                      <tr key={row.key} className="border-b border-border/60 last:border-0">
                        <th className="px-4 py-3 text-left font-semibold text-foreground">
                          {row.label}
                        </th>
                        {row.cells.map((cell) => (
                          <td
                            key={cell.key}
                            className="px-4 py-3 text-right font-semibold text-foreground"
                          >
                            {cell.displayValue}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
          <Card className="border-border/60 bg-card/90">
            <CardContent className="p-6">
              <div>
                <h2 className="font-display text-xl font-semibold tracking-tight text-foreground">
                  Institutional Decisions
                </h2>
              </div>

              <div className="mt-5 overflow-x-auto rounded-lg border border-border/60 bg-background/70">
                <table className="w-full min-w-[520px] border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-border/60">
                      <th className="w-28 px-4 py-3 text-left font-medium text-muted-foreground" />
                      {institutionalDecisionTable.columns.map((column) => (
                        <th
                          key={column.key}
                          className="px-4 py-3 text-right text-xs font-medium uppercase text-muted-foreground"
                        >
                          {column.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {institutionalDecisionTable.rows.map((row) => (
                      <tr key={row.key} className="border-b border-border/60 last:border-0">
                        <th className="px-4 py-3 text-left font-semibold text-foreground">
                          {row.label}
                        </th>
                        {row.cells.map((cell) => (
                          <td
                            key={cell.key}
                            className="px-4 py-3 text-right font-semibold text-foreground"
                          >
                            {cell.displayValue}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
          <Card className="border-border/60 bg-card/90">
            <CardContent className="p-6">
              <div>
                <h2 className="font-display text-xl font-semibold tracking-tight text-foreground">
                  CAPITAL STRUCTURE
                </h2>
              </div>

              <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {capitalStructureMetrics.map((metric) => (
                  <div
                    key={metric.key}
                    className="rounded-lg border border-border/60 bg-background/70 px-4 py-3"
                  >
                    <div className="text-xs uppercase text-muted-foreground">{metric.label}</div>
                    <div className="mt-2 text-lg font-semibold text-foreground">
                      {metric.displayValue}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
          <ReviewTableCard title="ANNUAL RATES" table={annualRatesTable} />
          <ReviewTableCard
            title="QUARTERLY SALES"
            table={quarterlySalesTable}
            minWidth="min-w-[620px]"
          />
          <ReviewTableCard
            title="EARNINGS PER SHARE"
            table={earningsPerShareTable}
            minWidth="min-w-[620px]"
          />
          <ReviewTableCard
            title="QUARTERLY DIVIDENDS PAID"
            table={quarterlyDividendsPaidTable}
            minWidth="min-w-[620px]"
          />
          <Card className="border-border/60 bg-card/90">
            <CardContent className="p-6">
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <h2 className="font-display text-xl font-semibold tracking-tight text-foreground">
                  CURRENT POSITION
                </h2>
                {currentPositionTable.unit ? (
                  <div className="text-xs uppercase text-muted-foreground">
                    {currentPositionTable.unit.replace('_', ' ')}
                  </div>
                ) : null}
              </div>

              <div className="mt-5 overflow-x-auto rounded-lg border border-border/60 bg-background/70">
                <table className="w-full min-w-[560px] border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-border/60">
                      <th className="w-56 px-4 py-3 text-left font-medium text-muted-foreground" />
                      {currentPositionTable.columns.map((column) => (
                        <th
                          key={column.key}
                          className="px-4 py-3 text-right text-xs font-medium uppercase text-muted-foreground"
                        >
                          {column.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {currentPositionTable.rows.map((row) => (
                      <tr key={row.key} className="border-b border-border/60 last:border-0">
                        <th className="px-4 py-3 text-left font-semibold text-foreground">
                          {row.label}
                        </th>
                        {row.cells.map((cell) => (
                          <td
                            key={cell.key}
                            className="px-4 py-3 text-right font-semibold text-foreground"
                          >
                            {cell.displayValue}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
          <Card className="border-border/60 bg-card/90">
            <CardContent className="p-6">
              <div>
                <h2 className="font-display text-xl font-semibold tracking-tight text-foreground">
                  ANNUAL FINANCIALS
                </h2>
              </div>

              <div className="mt-5 overflow-x-auto rounded-lg border border-border/60 bg-background/70">
                <table className="w-full min-w-[980px] border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-border/60">
                      <th className="sticky left-0 z-10 w-56 bg-background/95 px-4 py-3 text-left font-medium text-muted-foreground" />
                      {annualFinancialsTable.columns.map((column) => (
                        <th
                          key={column.key}
                          className="px-4 py-3 text-right text-xs font-medium uppercase text-muted-foreground"
                        >
                          {column.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(() => {
                      let prevSection: string | null = null;
                      return annualFinancialsTable.rows.flatMap((row) => {
                        const rowSection = row.section ?? null;
                        const elements = [];
                        if (rowSection && rowSection !== prevSection) {
                          prevSection = rowSection;
                          elements.push(
                            <tr key={`section-${rowSection}-${row.key}`} className="border-b border-border/40 bg-muted/40">
                              <th
                                colSpan={annualFinancialsTable.columns.length + 1}
                                className="sticky left-0 z-10 bg-muted/40 px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                              >
                                {rowSection}
                              </th>
                            </tr>
                          );
                        }
                        elements.push(
                          <tr key={row.key} className="border-b border-border/60 last:border-0">
                            <th className="sticky left-0 z-10 bg-background/95 px-4 py-3 text-left font-semibold text-foreground">
                              {row.label}
                            </th>
                            {row.cells.map((cell) => (
                              <td
                                key={cell.key}
                                className={`px-4 py-3 text-right ${
                                  cell.isEstimate
                                    ? 'font-semibold text-red-600'
                                    : 'font-semibold text-foreground'
                                }`}
                              >
                                {cell.displayValue}
                              </td>
                            ))}
                          </tr>
                        );
                        return elements;
                      });
                    })()}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
          {narrativeCards.map((card) => (
            <NarrativeCard key={card.key} card={card} />
          ))}
        </>
      )}
    </div>
  );
}
