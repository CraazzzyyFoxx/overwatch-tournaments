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

// Returned by POST /api/auth/oauth/{provider}/link — same origin/redirect/action
// echo as OAuthCallbackResult, "for symmetry" (Task 9), so the link redirect can
// also honor the origin the flow started on.
export interface OAuthLinkResult {
  message: string;
  provider: string;
  username: string;
  origin: string;
  redirect: string;
  action: OAuthAction;
}

export const authService = {
  async getOAuthUrl(provider: OAuthProviderName, params: OAuthUrlParams): Promise<OAuthUrlResponse> {
    const res = await apiFetch(`/api/auth/oauth/${provider}/url`, {
      query: { origin: params.origin, redirect: params.redirect, action: params.action, csrf: params.csrf },
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
  // never by the apex. No bearer token: the ticket alone (single-use, 60s
  // TTL, opaque) is the credential here.
  async ssoExchange(ticket: string): Promise<TokenPair> {
    const res = await apiFetch("/api/auth/sso/exchange", {
      method: "POST",
      body: { ticket },
      throwOnError: false
    });
    if (!res.ok) throw new Error("Failed to exchange SSO ticket");
    return res.json();
  },

  async linkOAuth(
    provider: OAuthProviderName,
    code: string,
    state: string,
    accessToken: string,
    csrf: string,
    headers?: ForwardedAuthHeaders,
  ): Promise<OAuthLinkResult> {
    const res = await apiFetch(`/api/auth/oauth/${provider}/link`, {
      method: "POST",
      token: accessToken,
      headers,
      body: { code, state, csrf },
      throwOnError: false
    });

    if (!res.ok) {
      throw new Error(`Failed to link ${provider} OAuth account`);
    }
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
