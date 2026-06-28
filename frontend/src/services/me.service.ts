import { apiFetch } from "@/lib/api-fetch";
import type { User } from "@/types/user.types";

async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

/** Self-service account management for the current user (own player's social
 *  identities + own avatar). Adding social accounts is OAuth-only (start the
 *  link flow), so there is no manual "add" method here. */
const meService = {
  async getSocialAccounts(): Promise<User> {
    const res = await apiFetch("/api/v1/me/social");
    return res.json();
  },

  async setSocialPrimary(accountId: number): Promise<User> {
    const res = await apiFetch(`/api/v1/me/social/${accountId}/primary`, { method: "POST" });
    return res.json();
  },

  async deleteSocialAccount(accountId: number): Promise<User> {
    const res = await apiFetch(`/api/v1/me/social/${accountId}`, { method: "DELETE" });
    return res.json();
  },

  async setAvatar(file: File): Promise<unknown> {
    const content_b64 = await fileToBase64(file);
    const res = await apiFetch("/api/auth/me/avatar", {
      method: "POST",
      body: { content_b64, content_type: file.type || "application/octet-stream" },
    });
    return res.json();
  },

  async deleteAvatar(): Promise<unknown> {
    const res = await apiFetch("/api/auth/me/avatar", { method: "DELETE" });
    return res.json();
  },
};

export default meService;
