import { NextResponse } from "next/server";
import { authService } from "@/services/auth.service";
import type { OAuthProviderName } from "@/types/auth.types";
import { resolveHost, PLATFORM_ZONE } from "@/lib/host";
import { getAccessToken } from "@/lib/auth-cookies";

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

    // Account linking (Task 10): the apex can't read this domain's
    // host-only session cookie, so it has no way to attribute the eventual
    // OAuth callback to a user on its own. If THIS domain can read an
    // access token, mint a single-use link-intent nonce and carry it along
    // -- the apex signs it into the OAuth state (see the apex branch below)
    // and its callback redeems it to resolve the linking user. No readable
    // token here means no safe way to mint one; fall through without a
    // link-intent so the apex treats this as an unauthenticated link
    // attempt (redirect to login) rather than linking anything.
    if (action === "link") {
      const { cookies } = await import("next/headers");
      const cookieStore = await cookies();
      const accessToken = getAccessToken(cookieStore);
      if (accessToken) {
        try {
          const { link_intent } = await authService.mintLinkIntent(accessToken);
          apexLogin.searchParams.set("link_intent", link_intent);
        } catch (err) {
          console.error("Failed to mint custom-domain link intent:", err);
          // No link-intent carried through -- the apex callback will have
          // neither a readable token nor a redeemable nonce and falls back
          // to redirecting to login (never an unauthenticated link).
        }
      }
    }

    return NextResponse.redirect(apexLogin);
  }

  // Only the apex legitimately receives a bounced `origin` (from a custom-domain
  // start, Task 7). Never honor it on a subdomain — a crafted ?origin= there
  // would otherwise be signed into the state.
  let flowOrigin = origin;
  let linkIntent: string | undefined;
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
    // Only honor a bounced link-intent nonce (Task 10) on the apex, mirroring
    // the origin gate above — a subdomain crafting its own ?link_intent=
    // would otherwise get an arbitrary value signed straight into a state it
    // has no business minting.
    if (action === "link") {
      const linkIntentParam = searchParams.get("link_intent");
      if (linkIntentParam) linkIntent = linkIntentParam;
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
  const { url } = await authService.getOAuthUrl(provider, { origin: flowOrigin, redirect, action, csrf, linkIntent });

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
