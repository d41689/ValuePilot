/**
 * MVP6-01 Tier 2: shared block-level loading state.
 *
 * Use at section level — for inline button-pending spinners keep the
 * existing ``<Loader2 className="..." />`` inside the Button.
 */
import { Loader2 } from 'lucide-react';

interface AdminLoadingStateProps {
  /** Optional label shown next to the spinner. */
  label?: string;
  /** Pass ``"compact"`` for in-row loaders; default is centered with padding. */
  variant?: 'compact' | 'centered';
}

export function AdminLoadingState({ label, variant = 'centered' }: AdminLoadingStateProps) {
  if (variant === 'compact') {
    return (
      <div className="inline-flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        {label ? <span>{label}</span> : null}
      </div>
    );
  }
  return (
    <div className="flex items-center justify-center gap-2 p-6 text-sm text-muted-foreground">
      <Loader2 className="h-5 w-5 animate-spin" />
      {label ? <span>{label}</span> : <span>Loading…</span>}
    </div>
  );
}
