const AUTH_COOKIE_NAMES = ['vp_access_token', 'vp_role'];
const AUTH_STORAGE_KEYS = ['vp_access_token', 'vp_refresh_token'];
const EXPIRED_COOKIE_DATE = 'Thu, 01 Jan 1970 00:00:00 GMT';

function expireCookie(cookieTarget, name) {
  cookieTarget.cookie = `${name}=; path=/; max-age=0; expires=${EXPIRED_COOKIE_DATE}`;
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

module.exports = {
  clearAuthSession,
};
