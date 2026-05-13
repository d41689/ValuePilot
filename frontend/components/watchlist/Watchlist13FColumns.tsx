/**
 * MVP7-03: per-row 13F columns on /watchlist.
 *
 * Renders four `<TableCell>` elements for one watchlist row,
 * driven by the snapshot from MVP7-02's `buildSnapshotsByStockId`
 * Map. Handles the available / unavailable / pending / error
 * snapshot states.
 *
 * Native HTML ``title`` attribute is used for tooltips per the
 * MVP7-03 SR5 (no shadcn Tooltip primitive shipped in V1).
 */
'use client';

import { AlertTriangle } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { TableCell } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import {
  caveatSeverityLabel,
  caveatSeverityTone,
  convictionTone,
  deltaHoldersTone,
  distinctivenessLabel,
  distinctivenessTone,
  formatConvictionLabel,
  formatDeltaHolders,
  responsive13FCellClass,
  unavailableTooltip,
  type Watchlist13FSnapshot,
} from '@/lib/watchlist13f';

type QueryStatus = 'idle' | 'pending' | 'error' | 'success';

interface Watchlist13FColumnsProps {
  snapshot: Watchlist13FSnapshot | undefined;
  /** Period label from the snapshot payload — flows into the
   * unavailable-state tooltip copy. */
  period: string | null;
  /** Universe size from the snapshot payload — flows into the
   * conviction tooltip copy. */
  universeSize: number;
  queryStatus: QueryStatus;
  /** MVP7-04: whether the 13F column group is expanded at md
   * viewport. Controls whether the four cells render at
   * 768–1279px. xl always shows; below md always hides. */
  mdExpanded: boolean;
  /** Class applied to the first 13F column to draw the vertical
   * separator from the main watchlist columns. */
  firstCellLeadingClass?: string;
}

function PlaceholderCells({
  text,
  title,
  responsiveClass,
  firstCellLeadingClass,
}: {
  text: string;
  title?: string;
  responsiveClass: string;
  firstCellLeadingClass?: string;
}) {
  const baseCellClass = cn(responsiveClass, 'text-muted-foreground');
  return (
    <>
      <TableCell title={title} className={cn(baseCellClass, firstCellLeadingClass)}>{text}</TableCell>
      <TableCell title={title} className={baseCellClass}>{text}</TableCell>
      <TableCell title={title} className={baseCellClass}>{text}</TableCell>
      <TableCell title={title} className={baseCellClass}>{text}</TableCell>
    </>
  );
}

export function Watchlist13FColumns({
  snapshot,
  period,
  universeSize,
  queryStatus,
  mdExpanded,
  firstCellLeadingClass,
}: Watchlist13FColumnsProps) {
  const responsiveClass = responsive13FCellClass(mdExpanded);
  if (queryStatus === 'pending' || queryStatus === 'idle') {
    return (
      <PlaceholderCells
        text="—"
        responsiveClass={responsiveClass}
        firstCellLeadingClass={firstCellLeadingClass}
      />
    );
  }

  if (queryStatus === 'error') {
    return (
      <PlaceholderCells
        text="⚠"
        title="13F snapshot failed to load."
        responsiveClass={responsiveClass}
        firstCellLeadingClass={firstCellLeadingClass}
      />
    );
  }

  if (!snapshot) {
    return (
      <PlaceholderCells
        text="—"
        title={unavailableTooltip('no_qualifying_period', period)}
        responsiveClass={responsiveClass}
        firstCellLeadingClass={firstCellLeadingClass}
      />
    );
  }

  if (snapshot.available === false) {
    return (
      <PlaceholderCells
        text="—"
        title={unavailableTooltip(snapshot.unavailable_reason, period)}
        responsiveClass={responsiveClass}
        firstCellLeadingClass={firstCellLeadingClass}
      />
    );
  }

  const convictionLabel = formatConvictionLabel(snapshot.conviction_percentile);
  const periodLabel = period ?? 'latest period';
  const convictionTooltip = `Conviction percentile across ${universeSize} ranked stocks for ${periodLabel}.`;
  const deltaTooltip = `${snapshot.adders_count} adders, ${snapshot.reducers_count} reducers this quarter.`;
  const distinctivenessTooltip = `${snapshot.consensus_count} qualifying ranked holders. Tier derived from coverage × consensus density.`;
  const caveatTooltip =
    snapshot.caveat_severity === 'ok'
      ? 'No caveat flags on this signal.'
      : `Caveat codes: ${snapshot.caveat_codes.join(', ')}`;

  return (
    <>
      <TableCell className={cn(responsiveClass, firstCellLeadingClass)}>
        <Badge
          variant={convictionTone(snapshot.conviction_percentile)}
          title={convictionTooltip}
        >
          {convictionLabel}
        </Badge>
      </TableCell>
      <TableCell className={responsiveClass}>
        <Badge
          variant={deltaHoldersTone(snapshot.delta_holders)}
          title={deltaTooltip}
        >
          {formatDeltaHolders(snapshot.delta_holders)}
        </Badge>
      </TableCell>
      <TableCell className={responsiveClass}>
        <Badge
          variant={distinctivenessTone(snapshot.distinctiveness_tier)}
          title={distinctivenessTooltip}
        >
          {distinctivenessLabel(snapshot.distinctiveness_tier)}
        </Badge>
      </TableCell>
      <TableCell className={responsiveClass}>
        <Badge
          variant={caveatSeverityTone(snapshot.caveat_severity)}
          title={caveatTooltip}
          className="gap-1"
        >
          {snapshot.caveat_severity === 'high-caution' ? (
            <AlertTriangle className="h-3 w-3" aria-hidden="true" />
          ) : null}
          {caveatSeverityLabel(snapshot.caveat_severity)}
        </Badge>
      </TableCell>
    </>
  );
}
