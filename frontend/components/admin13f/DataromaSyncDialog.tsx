/**
 * DataromaSyncDialog — admin diff UI for "Sync with Dataroma".
 *
 * Task doc:
 * ``docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md``
 *
 * Flow:
 *   1. Parent opens the dialog and fires the sync mutation.
 *   2. While the request is in flight we show a spinner.
 *   3. On success we render three sections (NEW / KNOWN / DROPPED).
 *      Only NEW entries are actionable — each row has a checkbox; the
 *      footer button POSTs the selected pairs to
 *      ``/admin/13f/managers/dataroma-sync/add`` and the parent's
 *      ``onAdd`` callback refreshes the manager list + closes the
 *      dialog.
 */
'use client';

import { useEffect, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

export interface DataromaSyncEntry {
  dataroma_code: string;
  name: string;
  institution_manager_id: number | null;
}

export interface DataromaSyncDiff {
  fetched_at: string;
  new_count: number;
  known_count: number;
  dropped_count: number;
  new_sample: DataromaSyncEntry[];
  known_sample: DataromaSyncEntry[];
  dropped_sample: DataromaSyncEntry[];
}

interface DataromaSyncDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  diff: DataromaSyncDiff | null;
  isFetching: boolean;
  fetchError: string | null;
  isAdding: boolean;
  onAdd: (items: { dataroma_code: string; name: string }[]) => void;
}

export function DataromaSyncDialog({
  open,
  onOpenChange,
  diff,
  isFetching,
  fetchError,
  isAdding,
  onAdd,
}: DataromaSyncDialogProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Reset selection whenever a new diff lands so a stale set from the
  // previous sync doesn't leak forward.
  useEffect(() => {
    setSelected(new Set());
  }, [diff]);

  const newEntries = useMemo<DataromaSyncEntry[]>(
    () => diff?.new_sample ?? [],
    [diff],
  );
  const knownCount = diff?.known_count ?? 0;
  const droppedEntries = diff?.dropped_sample ?? [];
  const droppedCount = diff?.dropped_count ?? 0;
  const newCount = diff?.new_count ?? 0;

  const allSelected = newEntries.length > 0 && selected.size === newEntries.length;

  const toggleAll = () => {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(newEntries.map((e) => e.dataroma_code)));
    }
  };

  const toggleOne = (code: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) {
        next.delete(code);
      } else {
        next.add(code);
      }
      return next;
    });
  };

  const selectedItems = useMemo(
    () =>
      newEntries
        .filter((e) => selected.has(e.dataroma_code))
        .map((e) => ({ dataroma_code: e.dataroma_code, name: e.name })),
    [newEntries, selected],
  );

  const addDisabled = selectedItems.length === 0 || isAdding;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Sync with Dataroma</DialogTitle>
          <DialogDescription>
            Compares Dataroma&apos;s current superinvestor list to your
            manager universe. Read-only — nothing is written until you click
            &quot;Add selected as candidates&quot;.
          </DialogDescription>
        </DialogHeader>

        {isFetching ? (
          <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Fetching Dataroma manager list…</span>
          </div>
        ) : fetchError ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
            {fetchError}
          </div>
        ) : diff ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>
                Fetched {new Date(diff.fetched_at).toLocaleString()}
              </span>
              <Badge variant="warning">{newCount} new</Badge>
              <Badge variant="secondary">{knownCount} already tracked</Badge>
              <Badge variant={droppedCount > 0 ? 'danger' : 'secondary'}>
                {droppedCount} dropped from Dataroma
              </Badge>
            </div>

            <section className="space-y-2">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">
                  New from Dataroma ({newCount})
                </h3>
                {newEntries.length > 0 ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={toggleAll}
                  >
                    {allSelected ? 'Clear all' : 'Select all'}
                  </Button>
                ) : null}
              </div>
              {newEntries.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No new Dataroma entries.
                </p>
              ) : (
                <ul className="max-h-64 space-y-1 overflow-y-auto rounded-md border p-2">
                  {newEntries.map((entry) => {
                    const checked = selected.has(entry.dataroma_code);
                    return (
                      <li
                        key={entry.dataroma_code}
                        className="flex items-center gap-2 rounded px-1 py-1 text-sm hover:bg-muted/40"
                      >
                        <Checkbox
                          id={`dataroma-add-${entry.dataroma_code}`}
                          checked={checked}
                          onCheckedChange={() => toggleOne(entry.dataroma_code)}
                          aria-label={`Add ${entry.name}`}
                        />
                        <label
                          htmlFor={`dataroma-add-${entry.dataroma_code}`}
                          className="flex flex-1 cursor-pointer items-center justify-between gap-2"
                        >
                          <span className="font-medium">{entry.name}</span>
                          <code className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                            {entry.dataroma_code}
                          </code>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              )}
              {newCount > newEntries.length ? (
                <p className="text-xs text-muted-foreground">
                  Showing first {newEntries.length} of {newCount}. Re-run sync
                  after adding to see the rest.
                </p>
              ) : null}
            </section>

            {droppedCount > 0 ? (
              <section className="space-y-2">
                <h3 className="text-sm font-semibold">
                  No longer in Dataroma ({droppedCount})
                </h3>
                <ul className="max-h-40 space-y-1 overflow-y-auto rounded-md border p-2 text-sm">
                  {droppedEntries.map((entry) => (
                    <li
                      key={entry.dataroma_code}
                      className="flex items-center justify-between gap-2 px-1 py-1"
                    >
                      <span>{entry.name}</span>
                      <code className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                        {entry.dataroma_code}
                      </code>
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-muted-foreground">
                  Dataroma rotates its tracked list; managers shown here may
                  still be active filers. No automatic action is taken.
                </p>
              </section>
            ) : null}
          </div>
        ) : null}

        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={isAdding}
          >
            Close
          </Button>
          <Button
            type="button"
            disabled={addDisabled}
            onClick={() => onAdd(selectedItems)}
          >
            {isAdding ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : null}
            Add selected as candidates
            {selectedItems.length > 0 ? ` (${selectedItems.length})` : ''}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
