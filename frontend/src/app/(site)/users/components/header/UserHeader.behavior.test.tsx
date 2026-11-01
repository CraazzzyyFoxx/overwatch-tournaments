// @vitest-environment happy-dom
import { createTranslator, NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import { OW_METADATA } from "@/test/discipline-metadata";
import type { User, UserProfile } from "@/types/user.types";

import UserHeader from "./UserHeader";

const reads = vi.hoisted(() => ({
  metadata: [] as unknown[][],
  card: null as { role: string | null; roleColor: string | null } | null
}));

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace?: "common.roles") => createTranslator({ locale: "en", messages, namespace })
}));
vi.mock("@/services/discipline.service", () => ({
  default: {
    metadata: async (axis: unknown, code: string) => {
      reads.metadata.push([axis, code]);
      return WORKSPACE_METADATA;
    }
  }
}));
vi.mock("@/services/user.service", () => ({
  default: {
    getUserEncounters: async () => ({ results: [], total: 0 }),
    getUserTournament: async () => null
  }
}));
vi.mock("@/app/(site)/users/components/header/ProfileToolbar", () => ({
  default: ({ card }: { card: { role: string | null; roleColor: string | null } }) => {
    reads.card = card;
    return null;
  }
}));
vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));
vi.mock("next/image", () => ({ default: () => null }));

const WORKSPACE_ID = 7;
const damage = OW_METADATA.roles[1];
/** The viewed workspace runs a Hitscan sub-role under Damage; the global ontology has no children. */
const WORKSPACE_METADATA = {
  ...OW_METADATA,
  workspace_id: WORKSPACE_ID,
  roles: [
    ...OW_METADATA.roles,
    { ...damage, id: 21, code: "damage_hitscan", name: "Hitscan", parent_id: damage.id, workspace_id: WORKSPACE_ID, attrs: {} }
  ]
};

it("names and tints a workspace sub-role from the viewed workspace's ontology", async () => {
  const profile = {
    roles: [
      {
        role: { dimension: "player_role", role: "damage_hitscan", parent: "damage" },
        tournaments: 3,
        division: 5,
        division_grid_version: null,
        maps: 10,
        maps_won: 6
      }
    ],
    tournaments: [],
    maps_total: 0,
    maps_won: 0,
    tournaments_count: 3,
    tournaments_won: 0,
    avg_placement: null,
    avg_playoff_placement: null,
    most_played_character: null
  } as unknown as UserProfile;
  const user = { id: 1, name: "Player#1234", avatar_url: null, social_accounts: [] } as unknown as User;

  renderToStaticMarkup(
    <NextIntlClientProvider locale="en" messages={messages}>
      {await UserHeader({ profile, user, scope: "workspace", discipline: "overwatch", axis: WORKSPACE_ID })}
    </NextIntlClientProvider>
  );

  expect(reads.metadata).toEqual([[WORKSPACE_ID, "overwatch"]]);
  expect(reads.card?.role).toBe("Hitscan");
  // A sub-role without its own colour wears its parent's.
  expect(reads.card?.roleColor).toBe(damage.attrs.color);
});

it("shows the game's handle under the canonical name on a single-game profile only", async () => {
  const profile = {
    roles: [],
    tournaments: [],
    maps_total: 0,
    maps_won: 0,
    tournaments_count: 0,
    tournaments_won: 0,
    avg_placement: null,
    avg_playoff_placement: null,
    most_played_character: null
  } as unknown as UserProfile;
  const account = (id: number, provider: string, username: string) => ({
    id,
    user_id: 1,
    provider,
    username,
    display_name: null,
    url: null,
    is_verified: false,
    is_primary: true
  });
  const user = {
    id: 1,
    name: "Canon#1234",
    avatar_url: null,
    social_accounts: [account(1, "riot", "RiotHandle#EUW"), account(2, "battlenet", "InGame#9999")]
  } as unknown as User;
  const render = async (discipline: string | null) =>
    renderToStaticMarkup(
      <NextIntlClientProvider locale="en" messages={messages}>
        {await UserHeader({ profile, user, scope: "workspace", discipline, axis: WORKSPACE_ID })}
      </NextIntlClientProvider>
    );

  const single = await render("overwatch");
  expect(single).toContain("<p");
  expect(single).toMatch(/<p[^>]*>InGame#9999<\/p>/);
  // "All games" adds no handle line: the accounts stay in the chip list alone.
  expect(await render(null)).not.toMatch(/<p[^>]*>InGame#9999<\/p>/);
});
