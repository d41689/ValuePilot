/**
 * MVP6-06: shared stale-lock release confirm dialog.
 *
 * Lifts the inline ``<Dialog>`` that previously lived on
 * ``/admin/13f`` (index page lines 2097–2132). Both the index
 * page (Tasks Card stale-lock surfacing) and the new
 * ``/admin/13f/jobs`` route (Job Detail drawer's release affordance)
 * mount this component; each owns its own
 * ``pendingStaleReleaseJobId`` state + ``releaseStaleLock`` mutation.
 *
 * Pure presentational.
 */
'use client';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

interface ReleaseStaleLockDialogProps {
  pendingJobId: number | null;
  releasePending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function ReleaseStaleLockDialog({
  pendingJobId,
  releasePending,
  onCancel,
  onConfirm,
}: ReleaseStaleLockDialogProps) {
  return (
    <Dialog
      open={pendingJobId !== null}
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Release Stale Lock</DialogTitle>
          <DialogDescription>
            This marks a stale running job as failed and releases its active lock.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
            Only continue after confirming the worker is no longer running this job.
          </div>
          <div className="rounded-md border border-border/70 p-3 text-sm">
            <div className="text-xs uppercase text-muted-foreground">Job ID</div>
            <div className="mt-1 font-medium">#{pendingJobId ?? '—'}</div>
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={pendingJobId === null || releasePending}
            onClick={onConfirm}
          >
            Release lock
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
