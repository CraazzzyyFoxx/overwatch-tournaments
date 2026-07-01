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

/**
 * An account links to at most one player (`players.user.auth_user_id`). The
 * link API still returns a 0/1-element array (`linked_players`), so this
 * picks the single entry for presentational callers instead of rendering a
 * multi-player list.
 */
export function getSingleLinkedPlayer<T>(linkedPlayers: readonly T[] | undefined | null): T | undefined {
  return linkedPlayers?.[0];
}
