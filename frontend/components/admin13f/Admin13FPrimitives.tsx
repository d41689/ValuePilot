'use client';

import { X } from 'lucide-react';
import { type ReactNode, useEffect, useRef } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export function SectionLabel({ children }: { children: ReactNode }) {
  return <div className="text-xs font-semibold uppercase text-muted-foreground">{children}</div>;
}

export function MetricTile({
  label,
  value,
  detail,
}: {
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <div className="rounded-md border border-border/70 p-3">
      <div className="text-xs uppercase text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
      {detail ? <div className="text-xs text-muted-foreground">{detail}</div> : null}
    </div>
  );
}

export function DrawerShell({
  title,
  description,
  closeLabel,
  labelledBy,
  maxWidthClassName,
  onClose,
  children,
}: {
  title: string;
  description?: ReactNode;
  closeLabel: string;
  labelledBy: string;
  maxWidthClassName: string;
  onClose: () => void;
  children: ReactNode;
}) {
  // Stable-callback ref: callers typically pass `onClose` as an inline arrow
  // (`onClose={() => setX(null)}`) which has a new identity per parent render.
  // Capturing it in a ref + a no-deps effect means the document keydown
  // listener registers exactly once per mount, not on every parent re-render.
  // (F3 reviewer note, D3 of post-MVP8-A2 sweep.)
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  // Focus management: move focus into the dialog on mount (close button),
  // restore focus to the previously-focused element on unmount. `autoFocus`
  // has known reliability issues under React StrictMode (double-mount can
  // skip the second focus) and provides no symmetric focus-restoration —
  // explicit useRef + useEffect is more robust and satisfies WCAG 2.4.3
  // (Focus Order). (F4 reviewer note, D3 of post-MVP8-A2 sweep.)
  const closeBtnRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    closeBtnRef.current?.focus();
    return () => {
      previouslyFocused?.focus();
    };
  }, []);

  return (
    <div className="fixed inset-0 z-50 bg-background/60 backdrop-blur-sm">
      <div aria-hidden="true" className="absolute inset-0 cursor-default" onClick={onClose} />
      <Card
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        className={`fixed inset-y-0 right-0 flex h-dvh max-h-dvh w-full flex-col overflow-hidden rounded-none border-y-0 border-r-0 shadow-xl ${maxWidthClassName}`}
      >
        <CardHeader className="shrink-0 border-b border-border/70 pb-3">
          <CardTitle className="flex items-center justify-between gap-2 text-base">
            <span id={labelledBy}>{title}</span>
            <Button
              ref={closeBtnRef}
              type="button"
              variant="ghost"
              size="icon"
              aria-label={closeLabel}
              onClick={onClose}
            >
              <X className="h-4 w-4" />
            </Button>
          </CardTitle>
          {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
        </CardHeader>
        <CardContent className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">{children}</CardContent>
      </Card>
    </div>
  );
}
