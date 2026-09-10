// Cookie names are deployment-scoped — see ./cookie-names. The legacy name is
// read as a fallback during the aqt->owt rename; it is never written.
import { ACCESS_TOKEN_COOKIE, LEGACY_ACCESS_TOKEN_COOKIE } from "./cookie-names";

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

// A 401 from /auth/refresh is TERMINAL for this document: the route answers 401
// only when the refresh cookie is absent or upstream rejected it, and it clears
// both cookies on the way out — nothing in this page context can make the next
// attempt succeed. Latch it, because every 401 used to be re-attempted on each
// focus/visibility event: prod logs showed clients that had never been logged in
// at all looping `/auth/refresh 401` + `/api/auth/me` pairs indefinitely (57
// browsers, 408 of the 627 "logout" responses in five days). A real login always
// navigates the document (the OAuth redirect), which resets this module.
let sessionKnownDead = false;

// Test seam. In a browser the latch is scoped to the document — logging back in
// always navigates, which discards this module — but a test process keeps ONE
// module instance across files, so a suite asserting a dead session would poison
// every later suite asserting a live refresh.
export function resetRefreshStateForTests(): void {
  sessionKnownDead = false;
  refreshInFlight = null;
}

// Runs in BOTH renderers, so both imports must stay dynamic: `next/headers` is
// server-only (a static import poisons every client bundle that touches this
// module) and `js-cookie` needs `document`, which does not exist on the server.
async function getTokenFromCookies(cookieName: string): Promise<string | undefined> {
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

export async function refreshAccessToken(): Promise<RefreshOutcome> {
  // Client-only. On the server there is no refresh path (no SSR middleware);
  // SSR renders from whatever cookie is present and the client takes over on
  // hydration via the proactive scheduler + reactive 401 path.
  if (typeof window === "undefined") return { status: "error" };

  if (sessionKnownDead) return { status: "unauthenticated" };

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
          sessionKnownDead = true;
          return { status: "unauthenticated" };
        }

        // Any other non-OK (5xx, network-level error mapped below) is transient.
        if (!res.ok) {
          return { status: "error" };
        }

        const tokens = (await res.json()) as { access_token?: string };
        if (tokens.access_token) {
          // The route's own `Set-Cookie` (relative `maxAge`, matching Domain) is
          // already applied by `fetch` — it is the ONLY writer. A client-side
          // re-write used to follow with an ABSOLUTE `expires` taken from the
          // token's `exp`, which the browser evaluates against the USER's clock:
          // a device running fast simply dropped the cookie it had just been
          // given, and the whole login/refresh cycle restarted forever.
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
