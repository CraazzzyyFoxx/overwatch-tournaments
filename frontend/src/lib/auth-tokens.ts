import { getTokenExpMs } from "./jwt";
import { PLATFORM_ZONE, isPlatformHost } from "./host";

// Canonical access-token cookie name. LEGACY_ACCESS_TOKEN_COOKIE is read as a
// fallback during the aqt->owt rename so existing sessions are not logged out;
// it is never written.
const ACCESS_TOKEN_COOKIE = "owt_access_token";
const LEGACY_ACCESS_TOKEN_COOKIE = "aqt_access_token";

// Must match the Domain the server sets on login (oauth-callback.ts) /
// refresh (auth/refresh/route.ts) in production. A client-side `Cookies.set`
// without a matching Domain wouldn't overwrite that cookie — RFC 6265 keys a
// cookie by (name, domain, path) — it would instead create a second,
// host-only cookie with the same name, and which one a later request sends
// first (stale domain-wide vs. fresh host-only) is undefined.
const IS_PROD = process.env.NODE_ENV === "production";
const COOKIE_DOMAIN = `.${PLATFORM_ZONE}`;

// Outcome of an access-token refresh attempt. The distinction matters: only a
// genuinely dead session ("unauthenticated" — the refresh endpoint returned 401)
// should log the user out. A transient failure ("error" — network/5xx) must NOT
// flip the UI to logged-out; the existing session stays valid and the next
// activity retries.
export type RefreshOutcome =
  | { status: "refreshed"; token: string }
  | { status: "unauthenticated" }
  | { status: "error" };

let refreshInFlight: Promise<RefreshOutcome> | null = null;

export async function getTokenFromCookies(cookieName: string): Promise<string | undefined> {
  if (typeof window === "undefined") {
    try {
      const { cookies } = await import("next/headers");
      const cookieStore = await cookies();
      return cookieStore.get(cookieName)?.value;
    } catch {
      return undefined;
    }
  }

  try {
    const Cookies = (await import("js-cookie")).default;
    return Cookies.get(cookieName);
  } catch {
    return undefined;
  }
}

// Reads the access-token cookie, preferring the canonical `owt_access_token`
// name and falling back to the legacy `aqt_access_token` name so existing
// sessions survive the aqt->owt rename.
export async function getAccessTokenCookie(): Promise<string | undefined> {
  const token = await getTokenFromCookies(ACCESS_TOKEN_COOKIE);
  if (token !== undefined) {
    return token;
  }
  return getTokenFromCookies(LEGACY_ACCESS_TOKEN_COOKIE);
}

// Persist the access token in a JS-readable cookie whose lifetime matches the
// token's own `exp`, so the client keeps the token exactly as long as it is
// valid (and decides when to refresh by `exp`, instead of losing it early).
// Mirrors the attributes set server-side by the /auth/refresh route handler.
export async function setAccessTokenCookie(token: string): Promise<void> {
  if (typeof window === "undefined") {
    return;
  }

  try {
    const Cookies = (await import("js-cookie")).default;
    const expMs = getTokenExpMs(token);
    // Domain-wide (`.owt`) only on the platform apex/subdomains; host-only on a
    // custom domain (the browser rejects a `.owt` cookie there, so a domain-wide
    // write silently no-ops and the refreshed token is lost). Mirrors the
    // server-side /auth/refresh route.
    const domainAttr = IS_PROD && isPlatformHost(window.location.hostname) ? { domain: COOKIE_DOMAIN } : {};
    Cookies.set(ACCESS_TOKEN_COOKIE, token, {
      path: "/",
      sameSite: "lax",
      secure: IS_PROD,
      ...domainAttr,
      ...(expMs !== undefined ? { expires: new Date(expMs) } : {}),
    });
  } catch {
    // ignore
  }
}

export async function refreshAccessToken(): Promise<RefreshOutcome> {
  // Client-only. On the server there is no refresh path (no SSR middleware);
  // SSR renders from whatever cookie is present and the client takes over on
  // hydration via the proactive scheduler + reactive 401 path.
  if (typeof window === "undefined") return { status: "error" };

  if (!refreshInFlight) {
    refreshInFlight = (async (): Promise<RefreshOutcome> => {
      try {
        const res = await fetch("/auth/refresh", {
          method: "POST",
          cache: "no-store",
          credentials: "include",
          headers: {
            Accept: "application/json"
          },
        });

        // 401 => the refresh token is missing/expired/revoked: the session is
        // genuinely dead. The route handler already cleared the cookies.
        if (res.status === 401) {
          return { status: "unauthenticated" };
        }

        // Any other non-OK (5xx, network-level error mapped below) is transient.
        if (!res.ok) {
          return { status: "error" };
        }

        const tokens = (await res.json()) as { access_token?: string };
        if (tokens.access_token) {
          await setAccessTokenCookie(tokens.access_token);
          return { status: "refreshed", token: tokens.access_token };
        }
        return { status: "error" };
      } catch {
        return { status: "error" };
      } finally {
        // Clears the slot for the NEXT wave of callers. Concurrent callers in
        // the current wave already hold this promise reference and receive its
        // settled value regardless of this assignment — so the dedup is intact.
        refreshInFlight = null;
      }
    })();
  }

  return refreshInFlight;
}
