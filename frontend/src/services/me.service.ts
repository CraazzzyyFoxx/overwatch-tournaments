import { apiFetch } from "@/lib/api-fetch";
import type { MinimizedUser, User } from "@/types/user.types";

/** Self-service account management for the current user (own player's social
 *  identities + own avatar). Adding social accounts is OAuth-only (start the
 *  link flow), so there is no manual "add" method here. Management is hide-only:
 *  users set-primary + toggle global display visibility, but cannot delete an
 *  account (full deletion is superuser-only). */
const meService = {
  async getSocialAccounts(): Promise<User> {
    const res = await apiFetch("/api/v1/me/social");
    return res.json();
  },

  async setSocialPrimary(accountId: number): Promise<User> {
    const res = await apiFetch(`/api/v1/me/social/${accountId}/primary`, { method: "POST" });
    return res.json();
  },

  async setSocialVisibility(accountId: number, visible: boolean): Promise<User> {
    const res = await apiFetch(`/api/v1/me/social/${accountId}/visibility`, {
      method: "POST",
      body: { visible },
    });
    return res.json();
  },

  /** Global stream-privacy veto for the current user's own player. Separate
   *  from `setSocialVisibility`: that one hides a social account from the
   *  public profile, this one keeps the live stream off tournament pages and
   *  overrides the per-tournament Stream POV opt-in. Returns the refreshed
   *  `User`, so callers can write it straight back into the cache. */
  async setStreamVisibility(visible: boolean): Promise<User> {
    const res = await apiFetch("/api/v1/me/stream-visibility", {
      method: "POST",
      body: { visible },
    });
    return res.json();
  },

  /** Self-service unlink of an OAuth connection (Discord/Twitch/Battle.net).
   *  Removes the OAuth link and un-verifies the matching social account (the row
   *  itself is kept — re-verify by re-linking). The provider key matches the
   *  social account's `provider` (OAUTH_TO_SOCIAL is 1:1). Returns 204 (no body);
   *  the backend rejects unlinking your last provider when no password is set. */
  async unlinkOAuth(provider: string): Promise<void> {
    await apiFetch(`/api/v1/auth/oauth/${provider}/unlink`, { method: "DELETE" });
  },

  /** Self-service deletion of the CURRENT ACCOUNT (not a social account).
   *  Returns 204. Historical data is deliberately untouched: identity-svc drops
   *  only account-owned rows (sessions, OAuth connections, API keys, roles) and
   *  unclaims the player identity, so tournaments, matches, statistics and
   *  registrations survive. Refused for a superuser account (400). */
  async deleteAccount(): Promise<void> {
    await apiFetch("/api/v1/auth/me", { method: "DELETE" });
  },

  async setAvatar(file: File): Promise<unknown> {
    // The gateway's POST /api/v1/auth/me/avatar handler expects a multipart form
    // with a "file" field — it base64-encodes the upload into the RPC body
    // itself. Send FormData (apiFetch detects it and lets the browser set the
    // multipart Content-Type + boundary); a JSON body is rejected with 400.
    const formData = new FormData();
    formData.append("file", file);
    const res = await apiFetch("/api/v1/auth/me/avatar", {
      method: "POST",
      body: formData,
    });
    return res.json();
  },

  async deleteAvatar(): Promise<unknown> {
    const res = await apiFetch("/api/v1/auth/me/avatar", { method: "DELETE" });
    return res.json();
  },

  /** The current account's bookmarked players (auth-account scoped, not tied
   *  to the caller's own linked player). Newest-favorited first. */
  async getFavoritePlayers(): Promise<MinimizedUser[]> {
    const res = await apiFetch("/api/v1/me/favorite-players");
    return res.json();
  },

  async addFavoritePlayer(playerId: number): Promise<void> {
    await apiFetch(`/api/v1/me/favorite-players/${playerId}`, { method: "POST" });
  },

  async removeFavoritePlayer(playerId: number): Promise<void> {
    await apiFetch(`/api/v1/me/favorite-players/${playerId}`, { method: "DELETE" });
  },
};

export default meService;
