import { NextRequest, NextResponse } from 'next/server';

const PROTECTED_PREFIXES = ['/home', '/documents', '/watchlist', '/upload', '/stocks', '/calibration', '/screener'];
const ADMIN_PREFIXES = ['/upload'];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get('vp_access_token')?.value;
  const role = request.cookies.get('vp_role')?.value;

  const isProtectedRoute = PROTECTED_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
  const isAdminRoute = ADMIN_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));

  if (pathname === '/login') {
    if (token) {
      return NextResponse.redirect(new URL('/home', request.url));
    }
    return NextResponse.next();
  }

  if (isProtectedRoute && !token) {
    return NextResponse.redirect(new URL('/login', request.url));
  }

  if (isAdminRoute && role !== 'admin') {
    return NextResponse.redirect(new URL('/home', request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    '/login',
    '/home/:path*',
    '/documents/:path*',
    '/watchlist/:path*',
    '/upload/:path*',
    '/stocks/:path*',
    '/calibration/:path*',
    '/screener/:path*',
  ],
};
