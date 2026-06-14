import type { AuthUser, LinkedPlayer, OAuthProviderAvailability, OAuthProviderName, TokenPair } from "@/types/auth.types";
import { apiFetch } from "@/lib/api-fetch";

type OAuthUrlResponse = {
  provider: string;
  url: string;
  state: string;
};

type ForwardedAuthHeaders = Record<string, string>;

export const authService = {
  async getOAuthUrl(provider: OAuthProviderName): Promise<OAuthUrlResponse> {
    const res = await apiFetch("auth", `/oauth/${provider}/url`, { throwOnError: false });
    if (!res.ok) throw new Error(`Failed to get ${provider} OAuth URL`);
    return res.json();
  },

  async getAvailableOAuthProviders(): Promise<OAuthProviderAvailability[]> {
    const res = await apiFetch("auth", "/providers", { throwOnError: false });
    if (!res.ok) throw new Error("Failed to load available OAuth providers");
    return res.json();
  },

  async exchangeOAuthCode(
    provider: OAuthProviderName,
    code: string,
    state: string,
    headers?: ForwardedAuthHeaders,
  ): Promise<TokenPair> {
    const res = await apiFetch("auth", `/oauth/${provider}/callback`, {
      query: { code, state },
      headers,
      throwOnError: false
    });
    if (!res.ok) throw new Error(`Failed to complete ${provider} OAuth`);
    return res.json();
  },

  async linkOAuth(
    provider: OAuthProviderName,
    code: string,
    state: string,
    accessToken: string,
    headers?: ForwardedAuthHeaders,
  ): Promise<void> {
    const res = await apiFetch("auth", `/oauth/${provider}/link`, {
      method: "POST",
      token: accessToken,
      headers,
      body: { code, state },
      throwOnError: false
    });

    if (!res.ok) {
      throw new Error(`Failed to link ${provider} OAuth account`);
    }
  },

  async me(accessToken?: string): Promise<AuthUser> {
    const res = accessToken
      ? await apiFetch("auth", "/me", { token: accessToken, throwOnError: false })
      : await apiFetch("auth", "/me", { throwOnError: false });
    if (!res.ok) throw new Error("Failed to fetch current user");
    return res.json();
  },

  async refresh(refreshToken: string, headers?: ForwardedAuthHeaders): Promise<TokenPair> {
    const res = await apiFetch("auth", "/refresh", {
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
      ? await apiFetch("auth", "/player/linked", { token: accessToken, throwOnError: false })
      : await apiFetch("auth", "/player/linked", { throwOnError: false });
    if (!res.ok) throw new Error("Failed to fetch linked players");
    return res.json();
  },

  async logout(accessToken?: string, refreshToken?: string, headers?: ForwardedAuthHeaders): Promise<void> {
    const res = accessToken
      ? await apiFetch("auth", "/logout", {
          method: "POST",
          token: accessToken,
          headers,
          body: refreshToken ? { refresh_token: refreshToken } : undefined,
          throwOnError: false
        })
      : await apiFetch("auth", "/logout", { method: "POST", headers, throwOnError: false });

    // /logout returns 204
    if (!res.ok && res.status !== 204) {
      throw new Error("Failed to logout");
    }
  }
};
