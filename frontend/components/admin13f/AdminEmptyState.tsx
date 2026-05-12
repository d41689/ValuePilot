/**
 * MVP6-01 Tier 2: shared empty-state component.
 *
 * Four canonical reason codes per Pre-MVP6-02 D5. Encoding the
 * reason as a prop forces each call site to pick the right copy
 * instead of inventing its own.
 *
 * - ``not-seeded``: dev / fresh production where no data exists yet.
 *   Hint at the seeder or the upstream ingestion job.
 * - ``pipeline-not-run``: data should exist but no pipeline run has
 *   produced it for the current scope yet. Hint at the trigger
 *   action.
 * - ``filter-empty``: data exists but the current filters return
 *   nothing. Hint at clearing filters.
 * - ``readiness-blocked``: readiness gates make this surface
 *   unavailable. Link to the readiness page for blocker detail.
 */
import Link from 'next/link';

export type AdminEmptyStateReason =
  | 'not-seeded'
  | 'pipeline-not-run'
  | 'filter-empty'
  | 'readiness-blocked';

interface AdminEmptyStateProps {
  reason: AdminEmptyStateReason;
  /** Optional message override; rarely needed — prefer to pick the
   * right reason code instead. */
  message?: string;
  /** Optional call-to-action link. The readiness-blocked default CTA
   * points at the readiness page. */
  cta?: { label: string; href: string };
}

const DEFAULT_COPY: Record<AdminEmptyStateReason, string> = {
  'not-seeded':
    'No data yet — run the dev fixture seeder or wait for production ingestion to populate this section.',
  'pipeline-not-run':
    "The pipeline hasn't produced data for this scope yet. Trigger the relevant job from the Jobs page.",
  'filter-empty':
    'No results match the current filters. Try clearing one or widening the range.',
  'readiness-blocked':
    'Readiness gates currently block this surface. See the Readiness page for blocker detail.',
};

const DEFAULT_CTA: Partial<Record<AdminEmptyStateReason, { label: string; href: string }>> = {
  'readiness-blocked': { label: 'See blockers', href: '/admin/13f/readiness' },
};

export function AdminEmptyState({ reason, message, cta }: AdminEmptyStateProps) {
  const copy = message ?? DEFAULT_COPY[reason];
  const resolvedCta = cta ?? DEFAULT_CTA[reason];
  return (
    <div className="rounded-md border border-dashed border-border/70 bg-muted/30 px-4 py-6 text-sm text-muted-foreground">
      <p>{copy}</p>
      {resolvedCta ? (
        <Link
          href={resolvedCta.href}
          className="mt-2 inline-block text-xs font-medium text-primary hover:underline"
        >
          {resolvedCta.label} →
        </Link>
      ) : null}
    </div>
  );
}
