'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { RESEARCH_STEPS, hasResearchNotes, type ResearchNotes } from '@/lib/researchPath';

export function ResearchPath({ notes, onChange, onAppend, onClear, readOnly }: {
  notes: ResearchNotes; onChange: (notes: ResearchNotes) => void;
  onAppend: () => void; onClear: () => void; readOnly: boolean;
}) {
  const [confirmClear, setConfirmClear] = useState(false);
  const pending = hasResearchNotes(notes);
  return <Card id="research-path" className="min-w-0 scroll-mt-6" aria-labelledby="research-path-title">
    <CardHeader><CardTitle id="research-path-title">From observation to judgment</CardTitle>
      <CardDescription>Use one concrete change from the financials above. Write your own answers; nothing here decides for you. You can leave questions unanswered.</CardDescription></CardHeader>
    <CardContent className="space-y-5">
      {RESEARCH_STEPS.map((step, i) => <div key={step.key} className="space-y-2">
        <label htmlFor={`research-${step.key}`} className="text-sm font-semibold">{i + 1}. {step.question}</label>
        <p id={`research-${step.key}-help`} className="text-xs text-muted-foreground">{step.hint}</p>
        <Textarea id={`research-${step.key}`} aria-describedby={`research-${step.key}-help`} rows={3} value={notes[step.key] ?? ''}
          disabled={readOnly} onChange={event => { setConfirmClear(false); onChange({ ...notes, [step.key]: event.target.value }); }} />
      </div>)}
      <div className="rounded-lg border bg-muted/20 p-3 text-sm" role="status">{pending
        ? 'These five-step notes are in your browser draft only. Append them to your thesis before saving a revision, or explicitly clear these notes.'
        : 'Append adds your answers to the end of your existing thesis without replacing it. Only Save revision records them on the server.'}</div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" disabled={readOnly || !pending} onClick={onAppend}>Append notes to thesis draft</Button>
        <Button type="button" variant="outline" disabled={readOnly || !pending} onClick={() => setConfirmClear(true)}>Clear five-step notes</Button>
      </div>
      {confirmClear && pending ? <div className="space-y-2 rounded border p-3 text-sm">
        <p>Clear only these five answers? Your thesis, selected evidence and saved revisions will stay unchanged.</p>
        <div className="flex flex-wrap gap-2"><Button type="button" variant="outline" disabled={readOnly} onClick={() => { onClear(); setConfirmClear(false); }}>Confirm clear notes</Button><Button type="button" variant="ghost" onClick={() => setConfirmClear(false)}>Keep notes</Button></div>
      </div> : null}
    </CardContent>
  </Card>;
}
