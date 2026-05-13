/**
 * MVP7-04: MOS × 13F cross-signal glyph for the existing MOS cell
 * on `/watchlist`. Per Pre-MVP7-01 D5 — visual enhancement on the
 * MOS column, NOT a new column.
 *
 * Renders nothing on the ``'neutral'`` signal (most rows). For the
 * three non-neutral signals, renders a small lucide icon next to
 * the MOS value with a native ``title`` tooltip explaining the
 * cross-signal in one sentence.
 */
'use client';

import { Check, TriangleAlert } from 'lucide-react';

import {
  mosCrossSignalTooltip,
  type MosCrossSignal,
} from '@/lib/watchlist13f';

interface MosCrossSignalGlyphProps {
  signal: MosCrossSignal;
}

export function MosCrossSignalGlyph({ signal }: MosCrossSignalGlyphProps) {
  if (signal === 'neutral') return null;
  const tooltip = mosCrossSignalTooltip(signal);
  if (signal === 'aligned') {
    return (
      <Check
        className="ml-1 inline-block h-3.5 w-3.5 text-emerald-600"
        aria-label={tooltip}
      >
        <title>{tooltip}</title>
      </Check>
    );
  }
  // exit-divergence and buy-divergence both render the same amber
  // warning glyph; the tooltip differentiates them in copy.
  return (
    <TriangleAlert
      className="ml-1 inline-block h-3.5 w-3.5 text-amber-600"
      aria-label={tooltip}
    >
      <title>{tooltip}</title>
    </TriangleAlert>
  );
}
