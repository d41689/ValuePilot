import axios, { AxiosError, AxiosHeaders, InternalAxiosRequestConfig } from 'axios';

import * as authSession from '@/lib/authSession';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api/v1';

// `_retry` marks a request we have already retried once after a refresh, so a
// second 401 on the same request ends the session instead of looping.
type RetryableRequest = InternalAxiosRequestConfig & { _retry?: boolean };

const apiClient = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = window.localStorage.getItem('vp_access_token');
    if (token) {
      const headers =
        config.headers instanceof AxiosHeaders
          ? config.headers
          : new AxiosHeaders(config.headers);
      headers.set('Authorization', `Bearer ${token}`);
      config.headers = headers;
    }
  }
  return config;
});

// Single-flight refresh: a wave of concurrent 401s shares one /auth/refresh
// call. Resolves to the new access token, or null when refresh is impossible
// (no refresh token stored, or the refresh token itself has expired).
let refreshPromise: Promise<string | null> | null = null;

function runRefresh(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = requestRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

async function requestRefresh(): Promise<string | null> {
  if (typeof window === 'undefined') {
    return null;
  }
  const refreshToken = window.localStorage.getItem('vp_refresh_token');
  if (!refreshToken) {
    return null;
  }
  try {
    // Bare axios (no interceptors) so a failed refresh cannot recurse into
    // this same refresh logic.
    const { data } = await axios.post(`${API_BASE}/auth/refresh`, {
      refresh_token: refreshToken,
    });
    // Guard against a malformed/partial response before persisting: a missing
    // token would otherwise write inconsistent auth state.
    if (!data?.access_token || !data?.refresh_token) {
      return null;
    }
    authSession.persistAuthSession(
      { accessToken: data.access_token, refreshToken: data.refresh_token },
      window.localStorage,
      document,
      window.location.protocol === 'https:',
    );
    return data.access_token as string;
  } catch {
    return null;
  }
}

function handleAuthFailure(): void {
  if (typeof window === 'undefined') {
    return;
  }
  authSession.clearAuthSession(window.localStorage, document);
  if (!window.location.pathname.startsWith('/login')) {
    window.location.href = '/login';
  }
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as RetryableRequest | undefined;

    if (!originalRequest || !authSession.shouldAttemptRefresh(error)) {
      if (error.response?.status === 401) {
        handleAuthFailure();
      }
      return Promise.reject(error);
    }

    originalRequest._retry = true;
    const refreshedToken = await runRefresh();
    if (!refreshedToken) {
      handleAuthFailure();
      return Promise.reject(error);
    }

    // The request interceptor re-reads the freshly persisted access token
    // from localStorage when the retried request goes back out.
    return apiClient(originalRequest);
  },
);

export default apiClient;
