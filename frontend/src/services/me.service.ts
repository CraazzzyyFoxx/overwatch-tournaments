import { apiFetch } from "@/lib/api-fetch";
import type { User } from "@/types/user.types";

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

  /** Self-service unlink of an OAuth connection (Discord/Twitch/Battle.net).
   *  Removes the OAuth link and un-verifies the matching social account (the row
   *  itself is kept — re-verify by re-linking). The provider key matches the
   *  social account's `provider` (OAUTH_TO_SOCIAL is 1:1). Returns 204 (no body);
   *  the backend rejects unlinking your last provider when no password is set. */
  async unlinkOAuth(provider: string): Promise<void> {
    await apiFetch(`/api/auth/oauth/${provider}/unlink`, { method: "DELETE" });
  },

  async setAvatar(file: File): Promise<unknown> {
    // The gateway's POST /api/auth/me/avatar handler expects a multipart form
    // with a "file" field — it base64-encodes the upload into the RPC body
    // itself. Send FormData (apiFetch detects it and lets the browser set the
    // multipart Content-Type + boundary); a JSON body is rejected with 400.
    const formData = new FormData();
    formData.append("file", file);
    const res = await apiFetch("/api/auth/me/avatar", {
      method: "POST",
      body: formData,
    });
    return res.json();
  },

  async deleteAvatar(): Promise<unknown> {
    const res = await apiFetch("/api/auth/me/avatar", { method: "DELETE" });
    return res.json();
  },
};

export default meService;
