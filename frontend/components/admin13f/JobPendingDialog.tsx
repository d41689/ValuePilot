/**
 * MVP6-06: shared dry-run-preview confirm dialog for admin job
 * enqueue flows.
 *
 * Lifts the inline ``<Dialog>`` that previously lived on
 * ``/admin/13f`` (index page lines 2033–2095). Both the index
 * page (Tasks Card retries, Manual Trigger CTAs) and the new
 * ``/admin/13f/jobs`` route mount this component; each owns its
 * own ``pendingJob`` state + ``triggerJob`` mutation and passes
 * the relevant props.
 *
 * Pure presentational. Matches the ``ManagerCikDialogs.tsx``
 * precedent — no internal state, no API calls.
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
import thirteenfAdmin from '@/lib/thirteenfAdmin';

const { jobPreviewRows } = thirteenfAdmin as {
  jobPreviewRows: (
    preview: Record<string, unknown>,
  ) => Array<{ label: string; value: unknown }>;
};

export interface PendingJob {
  label: string;
  payload: Record<string, unknown>;
  preview: Record<string, unknown>;
  previewFailed?: boolean;
}

interface JobPendingDialogProps {
  pendingJob: PendingJob | null;
  triggerJobPending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function JobPendingDialog({
  pendingJob,
  triggerJobPending,
  onCancel,
  onConfirm,
}: JobPendingDialogProps) {
  return (
    <Dialog
      open={pendingJob !== null}
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Confirm Job</DialogTitle>
          <DialogDescription>
            Review the dry-run preview before queueing this operation.
          </DialogDescription>
        </DialogHeader>
        {pendingJob ? (
          <div className="space-y-4">
            <div className="rounded-md border border-border/70 p-3">
              <div className="text-xs uppercase text-muted-foreground">Action</div>
              <div className="mt-1 font-medium">{pendingJob.label}</div>
              <div className="mt-1 font-mono text-xs text-muted-foreground">
                {String(pendingJob.payload.job_type ?? '—')}
              </div>
            </div>
            {pendingJob.previewFailed ? (
              <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
                Preview failed. The backend will still enforce locks before queueing.
              </div>
            ) : null}
            <div>
              <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                Impact Summary
              </div>
              <div className="grid gap-2 text-sm">
                {jobPreviewRows(pendingJob.preview).map(({ label, value }) => (
                  <div
                    key={String(label)}
                    className="flex justify-between gap-4 rounded-md border border-border/70 px-3 py-2"
                  >
                    <span className="text-muted-foreground">{String(label)}</span>
                    <span className="break-all text-right font-medium">
                      {String(value)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
            {pendingJob.preview.rate_limit_warning ? (
              <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
                {String(pendingJob.preview.rate_limit_warning)}
              </div>
            ) : null}
          </div>
        ) : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={!pendingJob || triggerJobPending}
            onClick={onConfirm}
          >
            Queue job
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
