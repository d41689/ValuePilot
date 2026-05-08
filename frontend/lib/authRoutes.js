const AUTH_PUBLIC_PATHS = ['/login', '/register'];
const AUTH_PROTECTED_PREFIXES = [
  '/home',
  '/documents',
  '/watchlist',
  '/upload',
  '/stocks',
  '/calibration',
  '/screener',
  '/admin',
];
const AUTH_ADMIN_PREFIXES = ['/upload', '/admin'];

const isPublicAuthPath = (pathname) => AUTH_PUBLIC_PATHS.includes(pathname);
const matchesPrefix = (pathname, prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`);
const isProtectedAuthPath = (pathname) =>
  AUTH_PROTECTED_PREFIXES.some((prefix) => matchesPrefix(pathname, prefix));
const isAdminAuthPath = (pathname) =>
  AUTH_ADMIN_PREFIXES.some((prefix) => matchesPrefix(pathname, prefix));

module.exports = {
  AUTH_ADMIN_PREFIXES,
  AUTH_PUBLIC_PATHS,
  AUTH_PROTECTED_PREFIXES,
  isAdminAuthPath,
  isProtectedAuthPath,
  isPublicAuthPath,
};
