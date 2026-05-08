'use client';

import thirteenfAdmin from '@/lib/thirteenfAdmin';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { SectionLabel } from '@/components/admin13f/Admin13FPrimitives';

const { managerCikReviewDefaults } = thirteenfAdmin;

type ManagerRecord = Record<string, unknown>;

type ManagerCikDialogsProps = {
  pendingConfirmManager: ManagerRecord | null;
  confirmCik: string;
  confirmNote: string;
  confirmPending: boolean;
  onConfirmCikChange: (value: string) => void;
  onConfirmNoteChange: (value: string) => void;
  onCloseConfirm: () => void;
  onSubmitConfirm: () => void;
  pendingRejectManager: ManagerRecord | null;
  rejectNote: string;
  rejectPending: boolean;
  onRejectNoteChange: (value: string) => void;
  onCloseReject: () => void;
  onSubmitReject: () => void;
  pendingRevokeManager: ManagerRecord | null;
  revokeNote: string;
  revokePending: boolean;
  onRevokeNoteChange: (value: string) => void;
  onCloseRevoke: () => void;
  onSubmitRevoke: () => void;
  pendingRetryManager: ManagerRecord | null;
  retrySearchName: string;
  retryNote: string;
  retryPending: boolean;
  onRetrySearchNameChange: (value: string) => void;
  onRetryNoteChange: (value: string) => void;
  onCloseRetry: () => void;
  onSubmitRetry: () => void;
};

export function ManagerCikDialogs({
  pendingConfirmManager,
  confirmCik,
  confirmNote,
  confirmPending,
  onConfirmCikChange,
  onConfirmNoteChange,
  onCloseConfirm,
  onSubmitConfirm,
  pendingRejectManager,
  rejectNote,
  rejectPending,
  onRejectNoteChange,
  onCloseReject,
  onSubmitReject,
  pendingRevokeManager,
  revokeNote,
  revokePending,
  onRevokeNoteChange,
  onCloseRevoke,
  onSubmitRevoke,
  pendingRetryManager,
  retrySearchName,
  retryNote,
  retryPending,
  onRetrySearchNameChange,
  onRetryNoteChange,
  onCloseRetry,
  onSubmitRetry,
}: ManagerCikDialogsProps) {
  return (
    <>
      <Dialog open={pendingConfirmManager !== null} onOpenChange={(open) => !open && onCloseConfirm()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm Manager CIK</DialogTitle>
            <DialogDescription>
              {pendingConfirmManager
                ? managerCikReviewDefaults(pendingConfirmManager).confirmDescription
                : 'Confirm the SEC CIK for this manager.'}
            </DialogDescription>
          </DialogHeader>
          {pendingConfirmManager ? (
            <div className="space-y-4">
              <div className="rounded-md border border-border/70 p-3 text-sm">
                <SectionLabel>Manager</SectionLabel>
                <div className="mt-1 font-medium">
                  {String(managerCikReviewDefaults(pendingConfirmManager).managerName)}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Candidate: {String(managerCikReviewDefaults(pendingConfirmManager).candidateName)}
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="confirm-cik">
                  SEC CIK
                </label>
                <Input
                  id="confirm-cik"
                  className="mt-2"
                  value={confirmCik}
                  onChange={(event) => onConfirmCikChange(event.target.value)}
                  placeholder="0000000000"
                />
              </div>
              <div>
                <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="confirm-note">
                  Optional note
                </label>
                <Textarea
                  id="confirm-note"
                  className="mt-2"
                  value={confirmNote}
                  onChange={(event) => onConfirmNoteChange(event.target.value)}
                  placeholder="Why is this CIK correct?"
                />
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onCloseConfirm}>
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!pendingConfirmManager || !confirmCik.trim() || confirmPending}
              onClick={onSubmitConfirm}
            >
              Confirm CIK
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={pendingRejectManager !== null} onOpenChange={(open) => !open && onCloseReject()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject Manager CIK</DialogTitle>
            <DialogDescription>
              {pendingRejectManager
                ? managerCikReviewDefaults(pendingRejectManager).rejectDescription
                : 'Reject this CIK candidate.'}
            </DialogDescription>
          </DialogHeader>
          {pendingRejectManager ? (
            <div className="space-y-4">
              <div className="rounded-md border border-border/70 p-3 text-sm">
                <SectionLabel>Manager</SectionLabel>
                <div className="mt-1 font-medium">
                  {String(managerCikReviewDefaults(pendingRejectManager).managerName)}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Candidate CIK {String(pendingRejectManager.candidate_cik ?? '—')}
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="reject-note">
                  Optional note
                </label>
                <Textarea
                  id="reject-note"
                  className="mt-2"
                  value={rejectNote}
                  onChange={(event) => onRejectNoteChange(event.target.value)}
                  placeholder="Why is this candidate wrong?"
                />
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onCloseReject}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={!pendingRejectManager || rejectPending}
              onClick={onSubmitReject}
            >
              Reject CIK
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={pendingRevokeManager !== null} onOpenChange={(open) => !open && onCloseRevoke()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke Confirmed CIK</DialogTitle>
            <DialogDescription>
              This excludes the manager from future 13F ingestion until a correct CIK is confirmed.
            </DialogDescription>
          </DialogHeader>
          {pendingRevokeManager ? (
            <div className="space-y-4">
              <div className="rounded-md border border-border/70 p-3 text-sm">
                <SectionLabel>Manager</SectionLabel>
                <div className="mt-1 font-medium">
                  {String(pendingRevokeManager.legal_name ?? 'this manager')}
                </div>
                <div className="mt-1 font-mono text-xs text-muted-foreground">
                  CIK {String(pendingRevokeManager.cik ?? '—')}
                </div>
              </div>
              {(() => {
                const latestEvent =
                  pendingRevokeManager.latest_cik_review_event &&
                  typeof pendingRevokeManager.latest_cik_review_event === 'object'
                    ? (pendingRevokeManager.latest_cik_review_event as Record<string, unknown>)
                    : null;
                return latestEvent?.requires_downstream_review ? (
                  <div className="rounded-md border border-amber-300/70 bg-amber-50 px-3 py-2 text-sm text-amber-950">
                    Existing filings already require downstream review for this manager.
                  </div>
                ) : null;
              })()}
              <div>
                <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="revoke-note">
                  Required note
                </label>
                <Textarea
                  id="revoke-note"
                  className="mt-2"
                  value={revokeNote}
                  onChange={(event) => onRevokeNoteChange(event.target.value)}
                  placeholder="Why is this confirmed CIK wrong?"
                />
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onCloseRevoke}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={!pendingRevokeManager || !revokeNote.trim() || revokePending}
              onClick={onSubmitRevoke}
            >
              Revoke CIK
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={pendingRetryManager !== null} onOpenChange={(open) => !open && onCloseRetry()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Retry CIK Search</DialogTitle>
            <DialogDescription>
              Search EDGAR again with an edited manager name. A match is saved as a candidate for review.
            </DialogDescription>
          </DialogHeader>
          {pendingRetryManager ? (
            <div className="space-y-4">
              <div className="rounded-md border border-border/70 p-3 text-sm">
                <SectionLabel>Manager</SectionLabel>
                <div className="mt-1 font-medium">
                  {String(pendingRetryManager.legal_name ?? pendingRetryManager.display_name ?? 'this manager')}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Current status: {String(pendingRetryManager.match_status ?? '—')}
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="retry-search-name">
                  Search name
                </label>
                <Input
                  id="retry-search-name"
                  className="mt-2"
                  value={retrySearchName}
                  onChange={(event) => onRetrySearchNameChange(event.target.value)}
                  placeholder="Manager legal name"
                />
              </div>
              <div>
                <label className="text-xs font-semibold uppercase text-muted-foreground" htmlFor="retry-note">
                  Optional note
                </label>
                <Textarea
                  id="retry-note"
                  className="mt-2"
                  value={retryNote}
                  onChange={(event) => onRetryNoteChange(event.target.value)}
                  placeholder="Why use this edited search name?"
                />
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onCloseRetry}>
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!pendingRetryManager || !retrySearchName.trim() || retryPending}
              onClick={onSubmitRetry}
            >
              Retry Search
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
