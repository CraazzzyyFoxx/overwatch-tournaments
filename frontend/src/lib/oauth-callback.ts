import { NextResponse } from "next/server";
import { authService } from "@/services/auth.service";
import { getForwardedClientHeaders } from "@/lib/forward-client-headers";
import { getTokenMaxAgeSeconds } from "@/lib/jwt";
import { resolveHost, PLATFORM_ZONE } from "@/lib/host";
import { getAccessToken } from "@/lib/auth-cookies";
import type { OAuthProviderName } from "@/types/auth.types";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";
const IS_PROD = process.env.NODE_ENV === "production";

// Cookie lifetime used when the access token's `exp` can't be decoded.
const FALLBACK_ACCESS_COOKIE_MAX_AGE_SECONDS = 13 * 60;
const REFRESH_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

// Session cookies are readable across every subdomain (SSO) in production;
// omitted in dev since `localhost` has no registrable platform-zone domain.
const COOKIE_DOMAIN = `.${PLATFORM_ZONE}`;

// Browser-binding CSRF cookie set by startOAuthLogin (oauth-login.ts). Single
// use: read once here, forwarded raw to the backend, then always cleared.
const CSRF_COOKIE = "owt_oauth_csrf";

const KNOWN_PROVIDERS: ReadonlySet<OAuthProviderName> = new Set<OAuthProviderName>([
  "discord",
  "twitch",
  "battlenet",
]);

// Only redirect back to the platform apex or a valid tenant subdomain. The
// `origin` field on the exchange/link response is echoed back from the
// signed state, but the state's `origin` claim is only as trustworthy as
// whatever Host header started the flow — never redirect to it unchecked.
function isAllowedOrigin(origin: string): boolean {
  try {
    const u = new URL(origin);
    if (u.protocol !== "http:" && u.protocol !== "https:") return false;
    if (u.hostname === PLATFORM_ZONE) return true;
    return resolveHost(u.hostname).mode === "tenant";
  } catch {
    return false;
  }
}

// `redirect` (from the exchange response, itself echoed from the HMAC-signed
// state) is only constrained to a same-origin path by the *sender's* own
// discipline (oauth-login.ts's `nextUrl.origin === origin` clamp) — the RPC
// boundary (`rpc_oauth_url`) never validates its shape, so nothing here can
// assume it's safe. Constructing `new URL(redirect, origin)` directly would
// let an absolute URL, a protocol-relative `//evil.com`, or a backslash trick
// (`/\evil.com`, which WHATWG URL parsing normalizes to `//evil.com` for
// http(s)) silently escape `origin` entirely — a classic OAuth-state open
// redirect. Let the URL parser do the normalization, then verify the
// *resulting* origin still matches before trusting it.
function safeRedirectTarget(redirect: string, origin: string): URL {
  try {
    const target = new URL(redirect || "/", origin);
    if (target.origin === new URL(origin).origin) return target;
  } catch {
    // fall through to the safe default below
  }
  return new URL("/", origin);
}

function base64UrlDecodeToString(value: string): string {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
  return atob(padded);
}

interface StateRouting {
  action: "login" | "link";
  provider: OAuthProviderName | null;
}

// Best-effort, UNTRUSTED decode of the signed OAuth state — used only to pick
// which provider/endpoint this apex callback should call next (there is a
// single fixed OAuth redirect_uri for every provider, so nothing else on this
// request tells us which one just completed). The backend independently
// HMAC-verifies the state and cross-checks provider/action server-side
// (`oauth_flows._verify_state_for`), so a tampered/forged read here can only
// misroute the request to the wrong endpoint (which then fails verification),
// never bypass verification itself. State shape is
// `base64url(payloadJson).base64url(signature)` with short JSON keys:
// {"o": origin, "r": redirect, "a": action, "p": provider, "n": nonce, "e": exp}
// (confirmed against backend/identity-service's StatePayload, Task 9 report).
// A decode failure defaults to the login action per the brief; provider has
// no safe default (we'd have no endpoint to call), so it's null and the
// caller must fail closed on that.
function decodeStateForRouting(state: string): StateRouting {
  try {
    const payloadPart = state.split(".")[0];
    const json = JSON.parse(base64UrlDecodeToString(payloadPart)) as Record<string, unknown>;
    const action: "login" | "link" = json.a === "link" ? "link" : "login";
    const provider =
      typeof json.p === "string" && KNOWN_PROVIDERS.has(json.p as OAuthProviderName)
        ? (json.p as OAuthProviderName)
        : null;
    return { action, provider };
  } catch {
    return { action: "login", provider: null };
  }
}

// Clears the single-use CSRF cookie. Must be called with the same Domain/Path
// attributes it was set with (oauth-login.ts) or the browser won't treat this
// as an overwrite of the original cookie.
function clearCsrfCookie(response: NextResponse): void {
  response.cookies.delete({
    name: CSRF_COOKIE,
    path: "/",
    ...(IS_PROD ? { domain: COOKIE_DOMAIN } : {})
  });
}

function errorRedirect(errorCode: string, description?: string | null): NextResponse {
  const errorUrl = new URL("/", SITE_URL);
  errorUrl.searchParams.set("auth_error", errorCode);
  if (description) {
    errorUrl.searchParams.set("auth_error_description", description);
  }
  const response = NextResponse.redirect(errorUrl);
  clearCsrfCookie(response);
  return response;
}

export async function handleOAuthCallback(request: Request): Promise<NextResponse> {
  const { cookies } = await import("next/headers");

  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const error = url.searchParams.get("error");
  const errorDescription = url.searchParams.get("error_description");

  if (error) {
    return errorRedirect(error, errorDescription);
  }

  const cookieStore = await cookies();
  const csrf = cookieStore.get(CSRF_COOKIE)?.value;

  // Fail closed: the backend independently rejects a missing/mismatched csrf
  // (Task 9b's `_verify_csrf_binding`), but there's no reason to spend an RPC
  // round trip on a request that's already missing something required.
  if (!code || !state || !csrf) {
    return errorRedirect("invalid_state");
  }

  const { action, provider } = decodeStateForRouting(state);
  if (!provider) {
    return errorRedirect("invalid_provider");
  }

  try {
    const forwardedHeaders = getForwardedClientHeaders(request);

    if (action === "link") {
      const accessToken = getAccessToken(cookieStore);

      if (!accessToken) {
        const loginUrl = new URL("/", SITE_URL);
        loginUrl.searchParams.set("login", "1");
        loginUrl.searchParams.set("next", "/account");
        const response = NextResponse.redirect(loginUrl);
        clearCsrfCookie(response);
        return response;
      }

      const linkResult = await authService.linkOAuth(provider, code, state, accessToken, csrf, forwardedHeaders);
      const origin = isAllowedOrigin(linkResult.origin) ? linkResult.origin : `https://${PLATFORM_ZONE}`;

      const response = NextResponse.redirect(new URL("/account", origin));
      clearCsrfCookie(response);
      return response;
    }

    const result = await authService.exchangeOAuthCode(provider, code, state, csrf, forwardedHeaders);
    const origin = isAllowedOrigin(result.origin) ? result.origin : `https://${PLATFORM_ZONE}`;
    const target = safeRedirectTarget(result.redirect, origin);

    const response = NextResponse.redirect(target);
    response.cookies.set("owt_access_token", result.access_token, {
      httpOnly: false,
      sameSite: "lax",
      secure: IS_PROD,
      path: "/",
      maxAge: getTokenMaxAgeSeconds(result.access_token, FALLBACK_ACCESS_COOKIE_MAX_AGE_SECONDS),
      ...(IS_PROD ? { domain: COOKIE_DOMAIN } : {})
    });

    response.cookies.set("owt_refresh_token", result.refresh_token, {
      httpOnly: true,
      sameSite: "lax",
      secure: IS_PROD,
      path: "/",
      maxAge: REFRESH_COOKIE_MAX_AGE_SECONDS,
      ...(IS_PROD ? { domain: COOKIE_DOMAIN } : {})
    });

    clearCsrfCookie(response);
    return response;
  } catch (err) {
    console.error("OAuth callback error:", err);
    return errorRedirect("exchange_failed");
  }
}
