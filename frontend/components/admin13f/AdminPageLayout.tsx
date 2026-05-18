/**
 * MVP6-01 Tier 2: shared admin/13f page layout shell.
 *
 * Renders a top-of-page navigation bar linking to all eight
 * admin/13f surfaces, plus a title / description / actions slot
 * and a children region.
 *
 * MVP6-01 ships this with anchor-link fallbacks for the seven
 * not-yet-created functional routes (``/admin/13f#managers`` etc.).
 * As each MVP6-02..07 ticket lands its corresponding route, that
 * ticket updates the entry here to point at the real route. The
 * ``Overview`` entry is real on day one because it's the existing
 * ``/admin/13f`` route.
 *
 * Per Pre-MVP6-02 D7 soft-dep convention: never point a nav entry
 * at a 404. If a route isn't built yet, keep the anchor fallback.
 */
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { type ReactNode } from 'react';

import { cn } from '@/lib/utils';

interface NavEntry {
  /** Display label. */
  label: string;
  /** Active route once shipped, OR an anchor on /admin/13f until the
   * route is built. */
  href: string;
  /** When true, this entry resolves to a real route already. False
   * means it's still an anchor on /admin/13f (pre-MVP6-02..07). */
  shipped: boolean;
}

const NAV_ENTRIES: NavEntry[] = [
  { label: 'Overview', href: '/admin/13f', shipped: true },
  { label: 'Managers', href: '/admin/13f/managers', shipped: true },
  { label: 'Daily Sync', href: '/admin/13f/sync', shipped: true },
  { label: 'Filings', href: '/admin/13f/filings', shipped: true },
  { label: 'Holdings', href: '/admin/13f/holdings', shipped: true },
  { label: 'Jobs', href: '/admin/13f/jobs', shipped: true },
  { label: 'Readiness', href: '/admin/13f/readiness', shipped: true },
];

interface AdminPageLayoutProps {
  title: string;
  description?: string;
  /** Optional right-aligned action buttons in the header. */
  actions?: ReactNode;
  children: ReactNode;
}

export function AdminPageLayout({
  title,
  description,
  actions,
  children,
}: AdminPageLayoutProps) {
  const pathname = usePathname();
  return (
    <div className="space-y-6">
      <nav
        aria-label="13F admin navigation"
        className="flex flex-wrap items-center gap-2 border-b border-border/70 pb-3"
      >
        {NAV_ENTRIES.map((entry) => {
          // Active when on the exact route or one of its sub-routes
          // (so e.g. /admin/13f/managers/123 highlights "Managers"),
          // and only for shipped routes — anchor fallbacks never light
          // up as active.
          const baseHref = entry.href.split('#')[0];
          let active = false;
          if (entry.shipped && pathname) {
            if (baseHref === '/admin/13f') {
              active = pathname === '/admin/13f';
            } else {
              active = pathname === baseHref || pathname.startsWith(`${baseHref}/`);
            }
          }
          return (
            <Link
              key={entry.label}
              href={entry.href}
              className={cn(
                'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                active
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground',
                !entry.shipped && !active ? 'opacity-70' : '',
              )}
              title={
                entry.shipped
                  ? undefined
                  : 'Route not yet implemented — anchor fallback per MVP6 D7'
              }
            >
              {entry.label}
              {!entry.shipped ? (
                <span className="ml-1 text-[10px] text-muted-foreground/70">↓</span>
              ) : null}
            </Link>
          );
        })}
      </nav>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {description ? (
            <p className="text-sm text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>
      {children}
    </div>
  );
}
