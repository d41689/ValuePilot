/**
 * MVP6-01 Tier 2: shared block-level error state.
 *
 * Use for query failures (persistent state). For action-result
 * failures (transient), keep the existing toast pattern from
 * ``useToast``.
 */
import { AlertTriangle } from 'lucide-react';

import { Button } from '@/components/ui/button';

interface AdminErrorStateProps {
  error: unknown;
  onRetry?: () => void;
  /** Optional title; defaults to "Failed to load data". */
  title?: string;
}

function formatError(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object' && 'message' in error) {
    const value = (error as { message?: unknown }).message;
    if (typeof value === 'string') return value;
  }
  return 'Unknown error.';
}

export function AdminErrorState({ error, onRetry, title }: AdminErrorStateProps) {
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-md border border-rose-300/70 bg-rose-50 px-4 py-3 text-sm text-rose-900"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="flex-1 space-y-2">
        <div className="font-medium">{title ?? 'Failed to load data'}</div>
        <div className="text-xs text-rose-900/80">{formatError(error)}</div>
        {onRetry ? (
          <Button type="button" size="sm" variant="outline" onClick={onRetry}>
            Retry
          </Button>
        ) : null}
      </div>
    </div>
  );
}
