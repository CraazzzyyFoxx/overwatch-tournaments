import type { AuthUser, LinkedPlayer, OAuthProviderAvailability, OAuthProviderName, TokenPair } from "@/types/auth.types";
import { apiFetch } from "@/lib/api-fetch";

export type OAuthCallbackMode = "cookie" | "ticket";

type OAuthUrlResponse = {
  provider: string;
  url: string;
  state: string;
};

type ForwardedAuthHeaders = Record<string, string>;

type OAuthAction = "login" | "link";

type OAuthUrlParams = {
  origin: string;
  redirect: string;
  action: OAuthAction;
  csrf: string;
  // Task 10R fix 1: OPTIONAL -- only present on the apex, and only when this
  // start was itself bounced from a custom domain (oauth-login.ts's
  // onCustomDomain branch). Already a hash (sha256_hex of the caller's
  // owt_xdomain_guard cookie) -- never the raw value. Omitted entirely for
  // every platform-host flow.
  guardHash?: string;
};

export type OAuthLinkMode = "linked" | "link_ticket";

// Named-options object (Task 10R) rather than positional (…, csrf,
// accessToken?) — a positional signature with two adjacent, easily
// transposed string params (csrf/accessToken) is exactly the kind of call
// site a future edit silently swaps by accident. `accessToken` is OPTIONAL:
// a custom-domain link has no apex session to present one (see
// oauth-callback.ts's "link" branch) — identity-svc decides server-side
// whether one was required (SECURITY INVARIANT: never derive the linked-to
// user from anything but a live session).
type OAuthLinkParams = {
  code: string;
  state: string;
  csrf: string;
  accessToken?: string;
  headers?: ForwardedAuthHeaders;
};

// Returned by POST /api/auth/oauth/{provider}/callback. `origin`/`redirect`/
// `action` are decoded server-side from the signed OAuth state (Task 9) so the
// callback can redirect back to whichever subdomain started the flow.
//
// `mode` (Task 9, custom domains) discriminates two shapes the backend can
// return: "cookie" (platform apex / a `.owt` subdomain) carries the raw
// tokens as before; "ticket" (a workspace custom domain, which can't read a
// cookie set on the apex) carries a one-time `ticket` instead and omits the
// tokens entirely. All four fields are optional so this stays backward-safe
// against older/cached responses that predate `mode` — callers must narrow
// on `mode`/presence before using either shape.
export interface OAuthCallbackResult {
  access_token?: string;
  refresh_token?: string;
  mode?: OAuthCallbackMode;
  ticket?: string;
  origin: string;
  redirect: string;
  action?: OAuthAction;
}

// Returned by POST /api/auth/oauth/{provider}/link. `origin`/`redirect`/
// `action` echo OAuthCallbackResult "for symmetry" (Task 9), so the caller
// can honor the origin the flow started on either way.
//
// `mode` (Task 10R) discriminates two shapes: "linked" (default; platform
// apex / a `.owt` subdomain) means the provider identity was attached
// directly — `message`/`provider`/`username` describe what was linked.
// "link_ticket" (a workspace custom domain) means NOTHING was linked yet:
// there is no live session on the ONE fixed apex callback that produced this
// response (see oauth_flows.link's module docstring) to attach the provider
// identity to. `ticket` then carries a single-use handle to that provider
// identity ONLY (never a site user id) for the custom domain's own frontend
// route (`/auth/link/complete`) to redeem against ITS OWN live session
// (`completeLink` below). `message`/`provider`/`username` are omitted in
// that mode.
export interface OAuthLinkResult {
  mode?: OAuthLinkMode;
  message?: string;
  provider?: string;
  username?: string;
  ticket?: string;
  origin: string;
  redirect: string;
  action?: OAuthAction;
}

// Thrown by linkOAuth when identity-svc reports the platform-host branch has
// no resolvable user (missing or invalid apex bearer) — the SAME signal the
// caller would have gotten before Task 10R moved this decision server-side.
// Callers should treat this identically to the old client-side pre-check:
// send the user to log in, then let them retry linking from account
// settings. Never treated as a generic failure (see oauth-callback.ts).
export class OAuthLinkAuthRequiredError extends Error {
  constructor() {
    super("OAuth account linking requires an authenticated session");
    this.name = "OAuthLinkAuthRequiredError";
  }
}

export const authService = {
  async getOAuthUrl(provider: OAuthProviderName, params: OAuthUrlParams): Promise<OAuthUrlResponse> {
    const res = await apiFetch(`/api/auth/oauth/${provider}/url`, {
      query: {
        origin: params.origin,
        redirect: params.redirect,
        action: params.action,
        csrf: params.csrf,
        // Omitted from the query string entirely when undefined (apiFetch's
        // appendParams skips undefined/null) -- a platform-host flow never
        // sends a guard_hash param at all.
        guard_hash: params.guardHash
      },
      skipWorkspace: true,
      throwOnError: false
    });
    if (!res.ok) throw new Error(`Failed to get ${provider} OAuth URL`);
    return res.json();
  },

  async getAvailableOAuthProviders(): Promise<OAuthProviderAvailability[]> {
    const res = await apiFetch("/api/auth/providers", { throwOnError: false });
    if (!res.ok) throw new Error("Failed to load available OAuth providers");
    return res.json();
  },

  // `csrf` is the RAW value of the `owt_oauth_csrf` cookie (never the hash) —
  // the backend re-hashes it and fail-closed-compares against the value bound
  // into the signed state at `getOAuthUrl` time. Sent in the body (alongside
  // code/state) rather than as a query param so the gateway's generic
  // body-merge forwarding (`bodyWithMeta`) carries it through unmodified.
  async exchangeOAuthCode(
    provider: OAuthProviderName,
    code: string,
    state: string,
    csrf: string,
    headers?: ForwardedAuthHeaders,
  ): Promise<OAuthCallbackResult> {
    const res = await apiFetch(`/api/auth/oauth/${provider}/callback`, {
      method: "POST",
      headers,
      body: { code, state, csrf },
      throwOnError: false
    });
    if (!res.ok) throw new Error(`Failed to complete ${provider} OAuth`);
    return res.json();
  },

  // Redeems a one-time SSO ticket (Task 9) minted by the apex OAuth callback
  // for a workspace custom domain that can't read a cookie set on the apex.
  // Called by /auth/sso/route.ts, which runs ON the custom domain itself —
  // never by the apex. No bearer token: the ticket alone is no longer
  // sufficient as the credential (Task 10R fix 1) -- `guard` (the RAW value
  // of the caller's `owt_xdomain_guard` cookie) must ALSO match the hash
  // bound into the ticket at issuance, or identity-svc fails closed (no
  // tokens) even for an otherwise-valid ticket.
  async ssoExchange(ticket: string, guard: string): Promise<TokenPair> {
    const res = await apiFetch("/api/auth/sso/exchange", {
      method: "POST",
      body: { ticket, guard },
      throwOnError: false
    });
    if (!res.ok) throw new Error("Failed to exchange SSO ticket");
    return res.json();
  },

  async linkOAuth(provider: OAuthProviderName, params: OAuthLinkParams): Promise<OAuthLinkResult> {
    const res = await apiFetch(`/api/auth/oauth/${provider}/link`, {
      method: "POST",
      token: params.accessToken,
      headers: params.headers,
      body: { code: params.code, state: params.state, csrf: params.csrf },
      throwOnError: false
    });

    if (!res.ok) {
      // 403 here is identity-svc's "Not authenticated" for the platform-host
      // branch (missing/invalid apex bearer) -- the same signal a missing
      // accessToken produced client-side before Task 10R. Any other failure
      // (bad state, provider error, ...) is generic.
      if (res.status === 403) {
        throw new OAuthLinkAuthRequiredError();
      }
      throw new Error(`Failed to link ${provider} OAuth account`);
    }
    return res.json();
  },

  // Redeems a one-time pending-link ticket (Task 10R) minted by the apex
  // `link` callback for a workspace custom domain — the reverse of
  // ssoExchange: this carries only a PROVIDER identity, and requires the
  // caller's OWN bearer (the live session on whichever host this runs on).
  // Called by /auth/link/complete/route.ts, which runs ON the custom domain
  // itself. The bearer resolves the linked-to user; the ticket never does.
  //
  // `guard` (Task 10R fix 1) is the RAW value of the caller's
  // `owt_xdomain_guard` cookie. A valid bearer alone is NOT sufficient
  // (that's exactly the reverse-CSRF this fix closes -- a victim's own live
  // session redeeming an attacker's ticket): identity-svc additionally
  // requires `guard`'s hash to match the ticket's bound hash, fail closed.
  async completeLink(ticket: string, accessToken: string, guard: string): Promise<{ message: string; provider?: string; username?: string }> {
    const res = await apiFetch("/api/auth/link/complete", {
      method: "POST",
      token: accessToken,
      body: { ticket, guard },
      throwOnError: false
    });
    if (!res.ok) throw new Error("Failed to complete OAuth account link");
    return res.json();
  },

  async me(accessToken?: string): Promise<AuthUser> {
    const res = accessToken
      ? await apiFetch("/api/auth/me", { token: accessToken, throwOnError: false })
      : await apiFetch("/api/auth/me", { throwOnError: false });
    if (!res.ok) throw new Error("Failed to fetch current user");
    return res.json();
  },

  async refresh(refreshToken: string, headers?: ForwardedAuthHeaders): Promise<TokenPair> {
    const res = await apiFetch("/api/auth/refresh", {
      method: "POST",
      headers,
      body: { refresh_token: refreshToken },
      throwOnError: false
    });
    if (!res.ok) throw new Error("Failed to refresh token");
    return res.json();
  },

  async getLinkedPlayers(accessToken?: string): Promise<LinkedPlayer[]> {
    const res = accessToken
      ? await apiFetch("/api/auth/player/linked", { token: accessToken, throwOnError: false })
      : await apiFetch("/api/auth/player/linked", { throwOnError: false });
    if (!res.ok) throw new Error("Failed to fetch linked players");
    return res.json();
  },

  async logout(accessToken?: string, refreshToken?: string, headers?: ForwardedAuthHeaders): Promise<void> {
    const res = accessToken
      ? await apiFetch("/api/auth/logout", {
          method: "POST",
          token: accessToken,
          headers,
          body: refreshToken ? { refresh_token: refreshToken } : undefined,
          throwOnError: false
        })
      : await apiFetch("/api/auth/logout", { method: "POST", headers, throwOnError: false });

    // /logout returns 204
    if (!res.ok && res.status !== 204) {
      throw new Error("Failed to logout");
    }
  }
};
