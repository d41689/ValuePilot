import { NextRequest, NextResponse } from 'next/server';
import { isAdminAuthPath, isProtectedAuthPath, isPublicAuthPath } from '@/lib/authRoutes';

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get('vp_access_token')?.value;
  const role = request.cookies.get('vp_role')?.value;

  if (isPublicAuthPath(pathname)) {
    if (token) {
      return NextResponse.redirect(new URL('/home', request.url));
    }
    return NextResponse.next();
  }

  if (isProtectedAuthPath(pathname) && !token) {
    return NextResponse.redirect(new URL('/login', request.url));
  }

  if (isAdminAuthPath(pathname) && role !== 'admin') {
    return NextResponse.redirect(new URL('/home', request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    '/login',
    '/register',
    '/home/:path*',
    '/documents/:path*',
    '/watchlist/:path*',
    '/upload/:path*',
    '/stocks/:path*',
    '/calibration/:path*',
    '/screener/:path*',
    '/admin/:path*',
  ],
};
