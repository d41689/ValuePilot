import type { ReactNode } from 'react';

export type AppToastType = 'success' | 'error' | 'warning' | 'info';

export type AppToastOptions = {
  type: AppToastType;
  title: ReactNode;
  description?: ReactNode;
};

export type AppToastPayload = {
  appType: AppToastType;
  title: ReactNode;
  description?: ReactNode;
  variant: 'default' | 'destructive';
};

export function normalizeAppToastType(type: unknown): AppToastType;

export function buildAppToastPayload(options: AppToastOptions): AppToastPayload;

export function showAppToast<T>(
  toast: (payload: AppToastPayload) => T,
  options: AppToastOptions
): T;
