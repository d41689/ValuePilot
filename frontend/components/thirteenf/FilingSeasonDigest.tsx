'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { BellRing, CalendarClock, X } from 'lucide-react';

import apiClient from '@/lib/api/client';
import managerHelpers from '@/lib/thirteenfManagers';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

const {
  formatCurrency,
  formatPercentPoints,
  normalizeFilingSeason,
  titleizeCode,
} = managerHelpers;

type Props = {
  showDigest?: boolean;
};

export function FilingSeasonDigest({ showDigest = true }: Props) {
  const [dismissed, setDismissed] = useState(false);
  const query = useQuery({
    queryKey: ['13f-filing-season'],
    queryFn: async () => {
      const response = await apiClient.get('/13f/filing-season');
      return normalizeFilingSeason(response.data);
    },
    staleTime: 5 * 60 * 1000,
  });
  const payload = query.data;
  const dismissalKey = payload?.quarter
    ? `13f-filing-season-dismissed-${payload.quarter}`
    : null;

  useEffect(() => {
    if (!dismissalKey || typeof window === 'undefined') return;
    setDismissed(window.localStorage.getItem(dismissalKey) === 'true');
  }, [dismissalKey]);

  if (!payload?.inSeason) return null;

  const dismiss = () => {
    setDismissed(true);
    if (dismissalKey && typeof window !== 'undefined') {
      window.localStorage.setItem(dismissalKey, 'true');
    }
  };

  return (
    <div id="filing-season-digest" className="space-y-4">
      {!dismissed ? (
        <div className="flex items-start gap-3 rounded-md border border-sky-300/70 bg-sky-50 px-4 py-3 text-sm text-sky-950">
          <CalendarClock className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="font-medium">13F filing season · {payload.quarter}</div>
            <div className="mt-1 text-sky-900/80">
              {payload.coverage.reportedManagerCount} of {payload.coverage.trackedManagerCount}
              {' '}tracked Value DNA managers have reported. The deadline was {payload.deadlineDate};
              new filings and amendments can still change the picture.
            </div>
            {!showDigest ? (
              <Link href="/13f/oracles-lens#filing-season-digest" className="mt-2 inline-block font-medium hover:underline">
                Open the filing-season digest
              </Link>
            ) : null}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="-mr-2 -mt-2 shrink-0"
            aria-label="Dismiss filing-season banner"
            onClick={dismiss}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      ) : null}

      {showDigest ? (
        <Card className="rounded-md">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <BellRing className="h-4 w-4" />
              Filing-season digest
            </CardTitle>
            <p className="text-sm text-muted-foreground">
              Newly ingested reports by reviewed value managers, grouped by the day they became
              visible in ValuePilot. New positions are evidence to investigate, not trade calls.
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            {payload.digests.length === 0 ? (
              <div className="text-sm text-muted-foreground">No digest days are available yet.</div>
            ) : payload.digests.map((digest) => (
              <div key={digest.digestDate ?? 'current'} className="rounded-md border border-border/70">
                <div className="border-b border-border/70 bg-muted/30 px-3 py-2 text-xs font-semibold uppercase text-muted-foreground">
                  {digest.digestDate ?? 'Today'} · {digest.items.length} new manager reports
                </div>
                {digest.items.length === 0 ? (
                  <div className="px-3 py-4 text-sm text-muted-foreground">
                    No tracked value-manager reports became visible on this digest day.
                  </div>
                ) : (
                  <div className="divide-y divide-border/70">
                    {digest.items.map((item) => (
                      <div key={`${digest.digestDate}-${item.manager.id}`} className="grid gap-3 px-3 py-4 md:grid-cols-[1fr_2fr]">
                        <div>
                          <Link href={`/13f/managers/${item.manager.id}`} className="font-medium hover:underline">
                            {item.manager.displayName}
                          </Link>
                          <div className="mt-1 flex flex-wrap gap-1.5">
                            <Badge variant="outline">{titleizeCode(item.manager.stylePrimary)}</Badge>
                            <Badge variant={item.caveats.length ? 'warning' : 'success'}>
                              {item.holdingsCount} holdings
                            </Badge>
                          </div>
                          {item.caveats.length ? (
                            <div className="mt-2 text-xs text-amber-700">
                              {item.caveats.map((caveat) => titleizeCode(caveat.code)).join(' · ')}
                            </div>
                          ) : null}
                        </div>
                        <div>
                          <div className="text-xs font-semibold uppercase text-muted-foreground">Top new positions</div>
                          {item.topNewPositions.length ? (
                            <div className="mt-2 flex flex-wrap gap-2">
                              {item.topNewPositions.map((position) => (
                                <Link
                                  key={`${item.manager.id}-${position.stock.id}`}
                                  href={`/stocks/${position.stock.ticker}/summary`}
                                  className="rounded-md border border-border/70 px-2.5 py-2 text-xs hover:bg-muted/50"
                                >
                                  <div className="font-medium">{position.stock.ticker}</div>
                                  <div className="mt-1 text-muted-foreground">
                                    {formatPercentPoints(position.portfolioWeightPct)} · {formatCurrency(position.currentValueUsd)}
                                  </div>
                                  {!position.includedInScore ? (
                                    <div className="mt-1 text-amber-700">Evidence caveated</div>
                                  ) : null}
                                </Link>
                              ))}
                            </div>
                          ) : (
                            <div className="mt-2 text-sm text-muted-foreground">No eligible new positions identified.</div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
