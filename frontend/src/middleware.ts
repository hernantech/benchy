import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const start = Date.now();
  const response = NextResponse.next();

  console.log(
    `${request.method} ${request.nextUrl.pathname} [${request.headers.get("x-forwarded-for") ?? "unknown"}]`
  );

  return response;
}

export const config = {
  matcher: ["/api/:path*", "/"],
};
