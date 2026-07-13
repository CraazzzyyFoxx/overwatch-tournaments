import { NextResponse } from "next/server";
import { authService } from "@/services/auth.service";
import type { OAuthProviderName } from "@/types/auth.types";
import { resolveHost, PLATFORM_ZONE } from "@/lib/host";
import { publicOrigin, publicHostname } from "@/lib/request-origin";

// Browser-binding CSRF cookie for the OAuth start->callback round trip. The
// signed state (produced by the backend) carries origin/redirect/action and
// binds sha256(csrf) into itself; the raw value only ever lives in this
// HttpOnly cookie. An attacker who can trigger the flow (e.g. via a hidden
// <img>/<a> to /auth/discord/login) cannot read or set this cookie for the
// victim, so the callback's cookie/state-hash comparison (Task 11) fails
// closed on login/linking CSRF.
const CSRF_COOKIE = "owt_oauth_csrf";
const CSRF_COOKIE_MAX_AGE_SECONDS = 10 * 60;

// Task 10R fix 1: the SAME browser-binding pattern as CSRF_COOKIE above,
// applied one hop further out -- across the custom-domain <-> apex boundary
// -- to close a REVERSE CSRF on the cross-domain login/link ticket handoff
// (see oauth-callback.ts's ticket branches and /auth/sso, /auth/link/complete).
// Those tickets are redeemed by a standalone GET route on the custom domain
// with nothing binding them to the browser that started the flow, so an
// attacker could run their OWN flow, capture their OWN ticket, and lure the
// victim into redeeming it (session fixation / account takeover via
// linking). This cookie is set HOST-ONLY on the custom domain itself (see
// the onCustomDomain branch below) -- UNLIKE CSRF_COOKIE, it must NEVER carry
// a `domain` attribute: a `.${PLATFORM_ZONE}` cookie would be readable
// (and, worse, settable) from every subdomain, defeating the binding, since
// the whole point is that only the browser that visited THIS custom domain
// can ever hold it. Only its SHA-256 hash (`guard_hash`, computed below)
// ever leaves this cookie -- via the apex-bounce URL, then the signed state,
// then the ticket's `lg` field -- the raw value is never put in a URL, never
// logged, and never sent anywhere except back to identity-svc at redemption
// time (by /auth/sso, /auth/link/complete) for a constant-time compare.
const GUARD_COOKIE = "owt_xdomain_guard";
const GUARD_COOKIE_MAX_AGE_SECONDS = CSRF_COOKIE_MAX_AGE_SECONDS;

function generateSecureToken(): string {
  // Two concatenated random UUIDs: well over 128 bits of entropy, generated
  // via the platform's CSPRNG (Node/Bun webcrypto), not Math.random(). Used
  // for both CSRF_COOKIE and GUARD_COOKIE -- same entropy/generation
  // requirements, different cookies/purposes.
  return `${crypto.randomUUID()}${crypto.randomUUID()}`.replace(/-/g, "");
}

// sha256_hex(value): webcrypto digest, hex-encoded. Used to compute
// `guard_hash` from the raw guard token below -- only the hash ever leaves
// this module in a URL; the raw value stays in the HttpOnly cookie.
async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export async function startOAuthLogin(request: Request, provider: OAuthProviderName): Promise<NextResponse> {
  // Public origin/host from the edge's forwarded headers — NOT request.url,
  // whose host behind the proxy is the internal bind addr (0.0.0.0:3000). See
  // request-origin.ts. Getting this wrong signs an internal origin into the
  // OAuth state, so the callback mistakes an apex login for a custom-domain
  // login and 400s on the missing guard hash (is_platform_host("0.0.0.0") is false).
  const searchParams = new URL(request.url).searchParams;
  const origin = publicOrigin(request);
  const currentHost = publicHostname(request);

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
    // Task 10R fix 1: mint the guard token/cookie HERE, on the custom domain
    // itself, before bouncing to the apex — this is the one and only point
    // in the whole flow where a cookie can be set on this exact host. `G`
    // (the raw token) goes ONLY into the HttpOnly, host-only cookie below;
    // `H = sha256_hex(G)` is the only thing that travels onward (query param
    // -> signed state -> ticket's `lg`), per the module docstring above.
    const guard = generateSecureToken();
    const guardHash = await sha256Hex(guard);

    const apexLogin = new URL(`https://${PLATFORM_ZONE}/auth/${provider}/login`);
    apexLogin.searchParams.set("action", action);
    apexLogin.searchParams.set("origin", `https://${currentHost}`);
    apexLogin.searchParams.set("guard_hash", guardHash);
    if (nextParam) apexLogin.searchParams.set("next", nextParam);

    const response = NextResponse.redirect(apexLogin);
    response.cookies.set(GUARD_COOKIE, guard, {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: GUARD_COOKIE_MAX_AGE_SECONDS
      // NO `domain` attribute -- host-only on THIS custom domain. See the
      // GUARD_COOKIE comment above: a `.${PLATFORM_ZONE}` domain here would
      // be readable/settable from every subdomain and defeat the binding.
    });
    return response;
  }

  // Only the apex legitimately receives a bounced `origin` (from a custom-domain
  // start, Task 7). Never honor it on a subdomain — a crafted ?origin= there
  // would otherwise be signed into the state. `guard_hash` (Task 10R fix 1)
  // is gated the SAME way, for the same reason: it is only ever meaningful
  // when it arrived via the custom-domain bounce above, which only ever
  // targets the apex.
  let flowOrigin = origin;
  let guardHash: string | undefined;
  if (currentHost === PLATFORM_ZONE) {
    const originParam = searchParams.get("origin");
    if (originParam) {
      try {
        const u = new URL(originParam);
        if (resolveHost(u.hostname).mode === "tenant") flowOrigin = u.origin;
      } catch {
        // malformed origin param — fail safe to the apex origin
      }
    }
    const guardHashParam = searchParams.get("guard_hash");
    if (guardHashParam) guardHash = guardHashParam;
  }

  let redirect = action === "link" ? "/?settings=profile" : "/";
  if (nextParam) {
    try {
      const nextUrl = new URL(nextParam, origin);
      if (nextUrl.origin === origin) redirect = nextUrl.pathname + nextUrl.search;
    } catch {
      if (nextParam.startsWith("/")) redirect = nextParam;
    }
  }

  const csrf = generateSecureToken();
  const { url } = await authService.getOAuthUrl(provider, { origin: flowOrigin, redirect, action, csrf, guardHash });

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
