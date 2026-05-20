const AUTH_COOKIE_NAMES = ['vp_access_token', 'vp_role'];
const AUTH_STORAGE_KEYS = ['vp_access_token', 'vp_refresh_token'];
const EXPIRED_COOKIE_DATE = 'Thu, 01 Jan 1970 00:00:00 GMT';

// Rolling session window. Every login and every silent refresh re-stamps the
// auth cookies with this max-age, so an active user's session never lapses;
// one week of inactivity expires the refresh token and forces a re-login.
const AUTH_SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60;

// Auth endpoints whose 401 is terminal (bad credentials, or a dead refresh
// token) and therefore must NOT trigger a token-refresh attempt.
const NON_REFRESHABLE_PATHS = ['/auth/login', '/auth/register', '/auth/refresh'];

function expireCookie(cookieTarget, name) {
  cookieTarget.cookie = `${name}=; path=/; max-age=0; expires=${EXPIRED_COOKIE_DATE}; SameSite=Lax`;
}

function clearAuthSession(storage, cookieTarget) {
  if (storage?.removeItem) {
    AUTH_STORAGE_KEYS.forEach((key) => storage.removeItem(key));
  }
  if (cookieTarget && typeof cookieTarget.cookie === 'string') {
    AUTH_COOKIE_NAMES.forEach((name) => expireCookie(cookieTarget, name));
  }
}

// Decode the `role` claim from a JWT access token WITHOUT verifying the
// signature. The server is the trust boundary; this value is only used for
// client-side route gating (the Next.js middleware re-reads it from a cookie).
function decodeJwtRole(accessToken) {
  try {
    const segment = String(accessToken).split('.')[1];
    if (!segment) return 'user';
    const normalized = segment.replace(/-/g, '+').replace(/_/g, '/');
    const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4);
    const payload = JSON.parse(atob(padded));
    return typeof payload.role === 'string' ? payload.role : 'user';
  } catch {
    return 'user';
  }
}

// Persist a freshly minted token pair: localStorage feeds the API client's
// Authorization header, the cookies feed the Next.js middleware route guard.
// Shared by login and the silent refresh so the two paths cannot drift.
//
// `secure` adds the `Secure` cookie attribute. Callers pass it from the live
// page protocol (HTTPS): it is required to protect a now week-long session,
// but a `Secure` cookie is silently dropped over plain HTTP — including local
// `http://localhost` dev — so gating on the actual protocol keeps every
// environment working without hard-coding the deployment's TLS model.
function persistAuthSession(tokens, storage, cookieTarget, secure) {
  const accessToken = tokens?.accessToken;
  const refreshToken = tokens?.refreshToken;
  if (storage?.setItem) {
    if (accessToken) storage.setItem('vp_access_token', accessToken);
    if (refreshToken) storage.setItem('vp_refresh_token', refreshToken);
  }
  if (cookieTarget && typeof cookieTarget.cookie === 'string') {
    const cookieOpts =
      `path=/; max-age=${AUTH_SESSION_MAX_AGE_SECONDS}; SameSite=Lax` +
      (secure ? '; Secure' : '');
    cookieTarget.cookie = `vp_access_token=${accessToken}; ${cookieOpts}`;
    cookieTarget.cookie = `vp_role=${decodeJwtRole(accessToken)}; ${cookieOpts}`;
  }
}

// Decide whether a failed request should trigger a token refresh + retry.
// Pure: takes an axios-style error object. Refresh only for a first-time 401
// on a normal endpoint — never for auth endpoints, never for an already-retried
// request (that would loop). The endpoint check matches on the URL path
// (exact, or as a trailing segment) so a path that merely contains an auth
// route as a substring is not misclassified.
function shouldAttemptRefresh(error) {
  const status = error?.response?.status;
  if (status !== 401) return false;
  const config = error?.config || {};
  if (config._retry) return false;
  const rawUrl = typeof config.url === 'string' ? config.url : '';
  const path = rawUrl.split('?')[0];
  if (NON_REFRESHABLE_PATHS.some((p) => path === p || path.endsWith(p))) return false;
  return true;
}

module.exports = {
  AUTH_SESSION_MAX_AGE_SECONDS,
  clearAuthSession,
  decodeJwtRole,
  persistAuthSession,
  shouldAttemptRefresh,
};
