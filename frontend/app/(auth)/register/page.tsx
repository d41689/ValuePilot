'use client';

import Link from 'next/link';
import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';

import apiClient from '@/lib/api/client';

type RegisterResponse = {
  id: number;
  email: string;
  role: string;
  tier: string;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
};

type ApiError = {
  response?: {
    data?: {
      detail?: string;
    };
  };
};

export default function RegisterPage() {
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
      await apiClient.post<RegisterResponse>('/auth/register', {
        email: email.trim(),
        password,
      });
      router.replace('/login?registered=1');
    } catch (err: unknown) {
      const apiError = (typeof err === 'object' && err !== null ? err : {}) as ApiError;
      const message = apiError.response?.data?.detail ?? 'Registration failed';
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="rounded-2xl border border-border/60 bg-card/95 p-6 shadow-sm">
      <div className="space-y-2">
        <h1 className="font-display text-2xl font-semibold">Create account</h1>
        <p className="text-sm text-muted-foreground">
          Register a new ValuePilot account with your email and password.
        </p>
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
            minLength={8}
            required
            className="w-full rounded-xl border border-border/70 bg-background px-3 py-2 text-sm outline-none focus:border-primary/70"
          />
          <p className="text-xs text-muted-foreground">Must be at least 8 characters.</p>
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
          {isSubmitting ? 'Creating account...' : 'Create account'}
        </button>
      </form>

      <p className="mt-4 text-center text-sm text-muted-foreground">
        Already have an account?{' '}
        <Link href="/login" className="font-medium text-primary hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
