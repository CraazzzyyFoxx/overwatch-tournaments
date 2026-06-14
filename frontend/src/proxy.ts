import { NextRequest, NextResponse } from "next/server";

const AUTH_SERVICE_URL =
  process.env.NEXT_PUBLIC_AUTH_SERVICE_URL?.replace(/\/$/, "") || "http://localhost:8001";

function decodeJwtPayload(token: string): any | undefined {
  const parts = token.split(".");
  if (parts.length < 2) return undefined;

  try {
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
    const json = atob(padded);
    return JSON.parse(json);
  } catch {
    return undefined;
  }
}

function shouldRefresh(accessToken: string, skewMs = 60_000): boolean {
  const payload = decodeJwtPayload(accessToken);
  const expSeconds = payload?.exp;
  if (typeof expSeconds !== "number") return false;

  const expMs = expSeconds * 1000;
  return expMs <= Date.now() + skewMs;
}

function getForwardedClientHeaders(request: NextRequest): Record<string, string> {
  const headers: Record<string, string> = {};
  const userAgent = request.headers.get("user-agent");
  const forwardedFor =
    request.headers.get("x-forwarded-for") || request.headers.get("x-vercel-forwarded-for");
  const realIp =
    request.headers.get("x-real-ip") ||
    request.headers.get("cf-connecting-ip") ||
    request.headers.get("true-client-ip") ||
    request.headers.get("x-client-ip");

  if (userAgent) {
    headers["user-agent"] = userAgent;
    headers["x-original-user-agent"] = userAgent;
  }
  if (forwardedFor) {
    headers["x-forwarded-for"] = forwardedFor;
  }
  if (realIp) {
    headers["x-real-ip"] = realIp;
  }

  return headers;
}

export async function proxy(request: NextRequest) {
  const accessToken = request.cookies.get("aqt_access_token")?.value;
  const refreshToken = request.cookies.get("aqt_refresh_token")?.value;

  if (!accessToken && !refreshToken) {
    return NextResponse.next();
  }

  if (!accessToken || shouldRefresh(accessToken)) {
    try {
      const res = await fetch(`${AUTH_SERVICE_URL}/refresh`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getForwardedClientHeaders(request),
        },
        body: JSON.stringify({ refresh_token: refreshToken })
      });

      if (!res.ok) {
        const response = NextResponse.next();
        response.cookies.delete("aqt_access_token");
        response.cookies.delete("aqt_refresh_token");
        return response;
      }

      const tokens = await res.json();

      const response = NextResponse.next();
      response.headers.set("Authorization", `Bearer ${tokens.access_token}`);

      response.cookies.set("aqt_access_token", tokens.access_token, {
        httpOnly: false,
        sameSite: "lax",
        secure: process.env.NODE_ENV === "production",
        path: "/",
        maxAge: 13 * 60
      });

      if (tokens.refresh_token) {
        response.cookies.set("aqt_refresh_token", tokens.refresh_token, {
          httpOnly: true,
          sameSite: "lax",
          secure: process.env.NODE_ENV === "production",
          path: "/",
          maxAge: 30 * 24 * 60 * 60
        });
      }

      return response;
    } catch (e) {
      console.error("Fetch Error:", e);
      return NextResponse.next();
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!api/|_next/static|_next/image|favicon.ico|auth/discord/login|auth/twitch/login|auth/battlenet/login|auth/callback|auth/logout|auth/refresh|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"
  ]
};
