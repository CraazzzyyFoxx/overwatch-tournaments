import { describe, expect, it } from "bun:test";

import {
  AUTH_CONNECTIONS_SETTINGS_HREF,
  getAuthProfileHref,
  getSingleLinkedPlayer,
  hasLinkedAnalyticsProfile
} from "@/lib/auth-profile-links";

describe("auth profile links", () => {
  it("builds public profile href from the primary linked player", () => {
    const primaryLinkedPlayer = {
      playerId: 7,
      playerName: "Grace#1234",
      isPrimary: true,
      linkedAt: "2026-04-19T00:00:00Z"
    };

    expect(getAuthProfileHref({ primaryLinkedPlayer })).toBe("/users/Grace-1234");
    expect(hasLinkedAnalyticsProfile({ primaryLinkedPlayer })).toBe(true);
  });

  it("falls back to connections when no linked player exists", () => {
    expect(getAuthProfileHref(undefined)).toBe(AUTH_CONNECTIONS_SETTINGS_HREF);
    expect(hasLinkedAnalyticsProfile(undefined)).toBe(false);
  });
});

describe("getSingleLinkedPlayer", () => {
  it("returns the sole linked player when one is linked", () => {
    const player = { player_id: 7, player_name: "Grace#1234", is_primary: true, linked_at: "2026-04-19T00:00:00Z" };

    expect(getSingleLinkedPlayer([player])).toEqual(player);
  });

  it("returns undefined when no player is linked", () => {
    expect(getSingleLinkedPlayer([])).toBeUndefined();
    expect(getSingleLinkedPlayer(undefined)).toBeUndefined();
    expect(getSingleLinkedPlayer(null)).toBeUndefined();
  });
});
