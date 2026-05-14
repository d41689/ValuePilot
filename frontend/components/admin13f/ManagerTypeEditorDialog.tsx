/**
 * MVP6-02: lifted ManagerTypeEditorDialog (MVP5-05 SR1 deferral
 * now realized). The inline JSX previously living in
 * ``app/(dashboard)/admin/13f/page.tsx`` is here as a
 * self-contained component. Each caller owns its own
 * ``managerTypeEditor`` state + ``managerTypeMutation`` and passes
 * them as props.
 *
 * The canonical 8-value manager_type vocabulary
 * (``app/models/institutions.MANAGER_TYPES``) is presented in the
 * order matching ``MANAGER_SIGNAL_WEIGHTS`` — highest signal quality
 * first.
 */
'use client';

import { useState, type Dispatch, type SetStateAction } from 'react';
import { Loader2 } from 'lucide-react';

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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';

export const MANAGER_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'long_term_fundamental', label: 'Long-term fundamental (weight 1.00)' },
  { value: 'value_concentrated', label: 'Value concentrated (weight 1.00)' },
  { value: 'activist', label: 'Activist (weight 0.80)' },
  { value: 'multi_strategy', label: 'Multi-strategy (weight 0.60, V1 conservative)' },
  { value: 'unknown', label: 'Unknown (weight 0.60)' },
  { value: 'quant', label: 'Quant (weight 0.40)' },
  { value: 'high_turnover', label: 'High turnover (weight 0.30)' },
  { value: 'index_like', label: 'Index-like (weight 0.10)' },
];

export interface ManagerTypeEditorState {
  managerId: number;
  currentType: string;
  managerName: string;
}

interface ManagerTypeEditorDialogProps {
  editor: ManagerTypeEditorState | null;
  setEditor: Dispatch<SetStateAction<ManagerTypeEditorState | null>>;
  draft: string;
  setDraft: Dispatch<SetStateAction<string>>;
  note: string;
  setNote: Dispatch<SetStateAction<string>>;
  onSave: (payload: { managerId: number; newManagerType: string; note: string; evidenceUrl: string }) => void;
  isPending: boolean;
}

export function ManagerTypeEditorDialog({
  editor,
  setEditor,
  draft,
  setDraft,
  note,
  setNote,
  onSave,
  isPending,
}: ManagerTypeEditorDialogProps) {
  const [evidenceUrl, setEvidenceUrl] = useState('');

  const noteRequired = draft !== 'unknown';
  const saveDisabled = !editor || isPending || (noteRequired && !note.trim());

  function handleClose() {
    setEditor(null);
    setNote('');
    setEvidenceUrl('');
  }

  return (
    <Dialog
      open={editor !== null}
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit manager type</DialogTitle>
          <DialogDescription>
            {editor
              ? `${editor.managerName} · currently ${editor.currentType.replaceAll('_', ' ')}`
              : null}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="mvp6-mt-type">
              Manager type
            </label>
            <Select value={draft} onValueChange={setDraft}>
              <SelectTrigger id="mvp6-mt-type" aria-label="Manager type">
                <SelectValue placeholder="Select manager type" />
              </SelectTrigger>
              <SelectContent>
                {MANAGER_TYPE_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="mvp6-mt-note">
              Note{noteRequired ? <span className="ml-0.5 text-destructive">*</span> : ' (optional)'}
              {noteRequired ? ' (required when classifying)' : null}
            </label>
            <Textarea
              id="mvp6-mt-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Evidence or rationale for this classification"
              rows={3}
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="mvp6-mt-evidence-url">
              Evidence URL (optional)
            </label>
            <Input
              id="mvp6-mt-evidence-url"
              type="url"
              value={evidenceUrl}
              onChange={(event) => setEvidenceUrl(event.target.value)}
              placeholder="https://…"
            />
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={saveDisabled}
            onClick={() => {
              if (!editor) return;
              onSave({
                managerId: editor.managerId,
                newManagerType: draft,
                note,
                evidenceUrl,
              });
            }}
          >
            {isPending ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : null}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
