'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AlertTriangle, ShieldCheck } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import apiClient from '@/lib/api/client';
import * as authSession from '@/lib/authSession';

const CONFIRMATION = 'ERASE MY ACCOUNT';

type ApiFailure = {
  response?: { data?: { detail?: string | { message?: string } } };
};

function errorMessage(error: unknown): string {
  const failure = (typeof error === 'object' && error !== null ? error : {}) as ApiFailure;
  const detail = failure.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  return detail?.message ?? 'Account erasure did not complete. No partial erasure was kept.';
}

export default function PrivacySettingsPage() {
  const router = useRouter();
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function eraseAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (confirmation !== CONFIRMATION) return;
    setSubmitting(true);
    setError(null);
    try {
      await apiClient.post('/users/me/erase', {
        password,
        confirmation: CONFIRMATION,
      });
      authSession.clearAuthSession(window.localStorage, document);
      router.replace('/login?account_erased=1');
    } catch (requestError) {
      setError(errorMessage(requestError));
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <div className="flex items-center gap-2 text-sm font-medium text-primary">
          <ShieldCheck className="h-4 w-4" /> Privacy & account
        </div>
        <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight">Account privacy</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Review the permanent consequences before removing your ValuePilot account.
        </p>
      </div>

      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="h-5 w-5" /> Erase account
          </CardTitle>
          <CardDescription>This action cannot be undone.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm">
            <p>Your sign-in credentials and notification destinations are revoked immediately.</p>
            <p>Your authored thesis, evidence notes, valuation notes, and manual portfolio details are irreversibly tombstoned.</p>
            <p>
              Minimum non-content audit markers and shared financial lineage remain so historical market and filing records are not falsified or detached from their provenance.
            </p>
          </div>

          <form className="mt-6 space-y-4" onSubmit={eraseAccount}>
            <div className="space-y-2">
              <label htmlFor="erasure-password" className="text-sm font-medium">Current password</label>
              <Input
                id="erasure-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                minLength={8}
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="erasure-confirmation" className="text-sm font-medium">
                Type <span className="font-mono">{CONFIRMATION}</span> to confirm
              </label>
              <Input
                id="erasure-confirmation"
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                autoComplete="off"
                required
              />
            </div>
            {error ? (
              <div role="alert" className="rounded-xl border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
                {error}
              </div>
            ) : null}
            <Button
              type="submit"
              variant="destructive"
              disabled={submitting || password.length < 8 || confirmation !== CONFIRMATION}
            >
              {submitting ? 'Erasing account…' : 'Permanently erase account'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
