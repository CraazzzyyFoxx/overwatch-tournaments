import type { AuthProfile } from "@/stores/auth-profile.store";
import { getPlayerSlug } from "@/utils/player";

export const AUTH_CONNECTIONS_SETTINGS_HREF = "/?settings=connections";

export function getAuthProfileHref(user?: Pick<AuthProfile, "primaryLinkedPlayer">): string {
  const playerName = user?.primaryLinkedPlayer?.playerName;
  return playerName ? `/users/${getPlayerSlug(playerName)}` : AUTH_CONNECTIONS_SETTINGS_HREF;
}

export function hasLinkedAnalyticsProfile(user?: Pick<AuthProfile, "primaryLinkedPlayer">): boolean {
  return Boolean(user?.primaryLinkedPlayer);
}
