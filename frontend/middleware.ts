import { NextRequest, NextResponse } from 'next/server';
import { resolveAuthRedirect } from '@/lib/authRoutes';

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get('vp_access_token')?.value;
  const role = request.cookies.get('vp_role')?.value;

  const redirectPath = resolveAuthRedirect(pathname, { token, role });
  if (redirectPath) {
    return NextResponse.redirect(new URL(redirectPath, request.url));
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
