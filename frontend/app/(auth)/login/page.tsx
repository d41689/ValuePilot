'use client';

import { FormEvent, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import apiClient from '@/lib/api/client';
import * as authSession from '@/lib/authSession';

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

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [registered, setRegistered] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    setRegistered(params.get('registered') === '1');
  }, []);

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
      authSession.persistAuthSession(
        { accessToken: access_token, refreshToken: refresh_token },
        window.localStorage,
        document,
        window.location.protocol === 'https:',
      );

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
      {registered && (
        <div className="mt-4 rounded-xl border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          Account created. Sign in with your new credentials.
        </div>
      )}

      <form className="mt-6 space-y-4" onSubmit={onSubmit}>
        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground" htmlFor="email">
            Email
          </label>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground" htmlFor="password">
            Password
          </label>
          <Input
            id="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </div>
        {error && (
          <div className="rounded-xl border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}
        <Button
          type="submit"
          disabled={isSubmitting}
          className="w-full"
        >
          {isSubmitting ? 'Signing in...' : 'Sign in'}
        </Button>
      </form>

      <p className="mt-4 text-center text-sm text-muted-foreground">
        Need an account?{' '}
        <Link href="/register" className="font-medium text-primary hover:underline">
          Create one
        </Link>
      </p>
    </div>
  );
}
