'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';

import apiClient from '@/lib/api/client';

type LoginResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
};

type ApiError = {
  response?: {
    data?: {
      detail?: string;
    };
  };
};

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const base64 = token.split('.')[1];
    if (!base64) return null;
    const normalized = base64.replace(/-/g, '+').replace(/_/g, '/');
    const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4);
    return JSON.parse(atob(padded)) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const response = await apiClient.post<LoginResponse>('/auth/login', {
        email: email.trim(),
        password,
      });
      const { access_token, refresh_token } = response.data;
      const payload = decodeJwtPayload(access_token);
      const role = typeof payload?.role === 'string' ? payload.role : 'user';

      window.localStorage.setItem('vp_access_token', access_token);
      window.localStorage.setItem('vp_refresh_token', refresh_token);
      document.cookie = `vp_access_token=${access_token}; path=/; max-age=${7 * 24 * 60 * 60}; SameSite=Lax`;
      document.cookie = `vp_role=${role}; path=/; max-age=${7 * 24 * 60 * 60}; SameSite=Lax`;

      router.replace('/home');
    } catch (err: unknown) {
      const apiError = (typeof err === 'object' && err !== null ? err : {}) as ApiError;
      const message = apiError.response?.data?.detail ?? 'Login failed';
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="rounded-2xl border border-border/60 bg-card/95 p-6 shadow-sm">
      <div className="space-y-2">
        <h1 className="font-display text-2xl font-semibold">Sign in</h1>
        <p className="text-sm text-muted-foreground">Use your ValuePilot credentials.</p>
      </div>

      <form className="mt-6 space-y-4" onSubmit={onSubmit}>
        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            className="w-full rounded-xl border border-border/70 bg-background px-3 py-2 text-sm outline-none focus:border-primary/70"
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            className="w-full rounded-xl border border-border/70 bg-background px-3 py-2 text-sm outline-none focus:border-primary/70"
          />
        </div>
        {error && (
          <div className="rounded-xl border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
        >
          {isSubmitting ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
