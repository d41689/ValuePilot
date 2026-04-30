export type AppToastType = 'success' | 'error' | 'warning' | 'info';

export type AppToastOptions = {
  type: AppToastType;
  title: string;
  description?: string;
};

export type AppToastPayload = {
  appType: AppToastType;
  title: string;
  description?: string;
  variant: 'default' | 'destructive';
};

export function normalizeAppToastType(type: unknown): AppToastType;

export function buildAppToastPayload(options: AppToastOptions): AppToastPayload;

export function showAppToast<T>(
  toast: (payload: AppToastPayload) => T,
  options: AppToastOptions
): T;
