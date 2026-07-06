import { NextResponse } from "next/server";
import { authService } from "@/services/auth.service";
import type { OAuthProviderName } from "@/types/auth.types";
import { resolveHost, PLATFORM_ZONE } from "@/lib/host";

// Browser-binding CSRF cookie for the OAuth start->callback round trip. The
// signed state (produced by the backend) carries origin/redirect/action and
// binds sha256(csrf) into itself; the raw value only ever lives in this
// HttpOnly cookie. An attacker who can trigger the flow (e.g. via a hidden
// <img>/<a> to /auth/discord/login) cannot read or set this cookie for the
// victim, so the callback's cookie/state-hash comparison (Task 11) fails
// closed on login/linking CSRF.
const CSRF_COOKIE = "owt_oauth_csrf";
const CSRF_COOKIE_MAX_AGE_SECONDS = 10 * 60;

function generateCsrfToken(): string {
  // Two concatenated random UUIDs: well over 128 bits of entropy, generated
  // via the platform's CSPRNG (Node/Bun webcrypto), not Math.random().
  return `${crypto.randomUUID()}${crypto.randomUUID()}`.replace(/-/g, "");
}

export async function startOAuthLogin(request: Request, provider: OAuthProviderName): Promise<NextResponse> {
  const { searchParams, origin, hostname: currentHost } = new URL(request.url);
  const nextParam = searchParams.get("next");
  const action = searchParams.get("action") === "link" ? "link" : "login";

  // Custom domains (a tenant host that is neither the apex nor a `.owt`
  // subdomain) can't complete the round trip themselves: the CSRF cookie
  // below is set with `Domain=.owt` so only the apex and its subdomains can
  // read it back on the callback. Bounce the whole start to the apex,
  // carrying the real origin and `next` along as query params, and let the
  // apex (re-invoking this same function) set the cookie and call
  // getOAuthUrl instead. No cookie is set on this redirect.
  const onCustomDomain =
    resolveHost(currentHost).mode === "tenant" && currentHost !== PLATFORM_ZONE && !currentHost.endsWith(`.${PLATFORM_ZONE}`);
  if (onCustomDomain) {
    const apexLogin = new URL(`https://${PLATFORM_ZONE}/auth/${provider}/login`);
    apexLogin.searchParams.set("action", action);
    apexLogin.searchParams.set("origin", `https://${currentHost}`);
    if (nextParam) apexLogin.searchParams.set("next", nextParam);
    return NextResponse.redirect(apexLogin);
  }

  // Only present when this is a bounced custom-domain flow arriving on the
  // apex (see above). Trust it as the state `origin` only when it resolves
  // to a tenant host, so an attacker can't point the post-login redirect at
  // an arbitrary open origin via this query param.
  const originParam = searchParams.get("origin");
  let flowOrigin = origin;
  if (originParam) {
    try {
      if (resolveHost(new URL(originParam).hostname).mode === "tenant") flowOrigin = originParam;
    } catch {
      // Malformed origin param — ignore and fall back to the apex origin.
    }
  }

  let redirect = action === "link" ? "/account" : "/";
  if (nextParam) {
    try {
      const nextUrl = new URL(nextParam, origin);
      if (nextUrl.origin === origin) redirect = nextUrl.pathname + nextUrl.search;
    } catch {
      if (nextParam.startsWith("/")) redirect = nextParam;
    }
  }

  const csrf = generateCsrfToken();
  const { url } = await authService.getOAuthUrl(provider, { origin: flowOrigin, redirect, action, csrf });

  const response = NextResponse.redirect(url);
  response.cookies.set(CSRF_COOKIE, csrf, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: CSRF_COOKIE_MAX_AGE_SECONDS,
    // Readable on the apex callback host regardless of which subdomain
    // started the flow. Omitted outside production so localhost (no
    // registrable platform-zone domain) still works.
    ...(process.env.NODE_ENV === "production" ? { domain: `.${PLATFORM_ZONE}` } : {})
  });

  return response;
}
