// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import { OW_METADATA } from "@/test/discipline-metadata";
import { TEST_LADDER_TIERS } from "@/test/native-ladder";
import type { CharacterWithUserStats, CareerAccount, CareerCharacter, CareerQueue} from "@/types/user.types";

import CareerOverviewCard from "./CareerOverviewCard";
import CareerTab from "./CareerTab";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const services = vi.hoisted(() => ({
  career: vi.fn(),
  characters: vi.fn(),
  ranks: vi.fn()
}));
vi.mock("@/services/user.service", () => ({
  default: { getUserCareer: services.career, getUserCharacters: services.characters }
}));
vi.mock("@/services/rank.service", () => ({ default: { getUserCurrentRanks: services.ranks } }));
vi.mock("@/hooks/useCatalogEntities", () => ({
  useCatalogEntities: () => ({
    data: ["ana", "ashe"].map((slug, id) => ({ id, slug, name: slug === "ana" ? "Ana" : "Ashe", image_path: null }))
  })
}));
vi.mock("next/image", () => ({ default: () => null }));

const METADATA = { ...OW_METADATA, native_ladder: TEST_LADDER_TIERS };
const AT = "2026-11-16T12:00:00Z";

const hero = (character: string, role: string, overrides: Partial<CareerCharacter> = {}): CareerCharacter => ({
  character,
  role,
  seconds: 3600,
  share: 0.5,
  games_played: 6,
  games_won: 3,
  winrate: 0.5,
  rates: { eliminations: 13.33, deaths: 3.37, hero_damage_done: 4595.5, healing_done: role === "support" ? 8892.37 : undefined },
  ...overrides
});

const queue = (overrides: Partial<CareerQueue> = {}): CareerQueue => ({
  platform: "pc",
  queue: "competitive",
  season: 25,
  seconds: 12600,
  games_played: 20,
  games_won: 11,
  games_lost: 9,
  winrate: 0.55,
  rates: { eliminations: 15.18, deaths: 4.49, hero_damage_done: 5773.94, healing_done: 7003.34 },
  roles: [{ role: "support", seconds: 8248, share: 0.66, pool_size: 3.42, mains: ["ana"] }],
  characters: [hero("ana", "support"), hero("ashe", "damage")],
  captured_at: AT,
  ...overrides
});

const account = (id: number, handle: string, overrides: Partial<CareerAccount> = {}): CareerAccount => ({
  social_account_id: id,
  handle,
  is_primary: false,
  status: "ok",
  last_success_at: AT,
  profile: {
    display_name: handle.split("#")[0],
    avatar_url: null,
    attrs: { title: "Kitten of Discord", endorsement_level: 4 },
    is_public: true,
    upstream_updated_at: AT,
    fetched_at: AT
  },
  queues: [queue()],
  ...overrides
});

const closed = account(3, "closed#3", {
  status: "private",
  queues: [],
  profile: { display_name: "Closed", avatar_url: null, attrs: {}, is_public: false, upstream_updated_at: AT, fetched_at: AT }
});

const ourHero = (slug: string, name: string, avg: Record<string, number>): CharacterWithUserStats =>
  ({
    character: { id: 1, slug, name, image_path: null },
    games: 4,
    win: 3,
    loss: 1,
    draw: 0,
    win_rate_all: null,
    record: null,
    stats: Object.entries(avg).map(([stat, avg_10]) => ({ name: stat, avg_10, overall: 0, avg_10_all: 0 }))
  }) as unknown as CharacterWithUserStats;

let root: Root;
let container: HTMLElement;

beforeEach(() => {
  document.body.innerHTML = "";
  container = document.body.appendChild(document.createElement("div"));
  root = createRoot(container);
  services.characters.mockResolvedValue({ results: [], total: 0 });
  services.ranks.mockResolvedValue({ user_id: 1, ranks: [], generated_at: AT });
});

afterEach(async () => {
  await act(async () => root.unmount());
  vi.clearAllMocks();
});

async function mount(accounts: CareerAccount[], node: (props: { userId: number }) => ReactNode) {
  services.career.mockResolvedValue({ user_id: 1, accounts, generated_at: AT });
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          {node({ userId: 1 })}
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  // Let the queries settle and the dependent ones start.
  for (let i = 0; i < 3; i++) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

const tab = ({ userId }: { userId: number }) => <CareerTab userId={userId} scope="all" metadata={METADATA} />;
const overview = ({ userId }: { userId: number }) => (
  <CareerOverviewCard userId={userId} userSlug="Someone" metadata={METADATA} />
);

describe("ladder tab", () => {
  it("shows a closed profile as its name and a calm note, with no career figures", async () => {
    await mount([closed], tab);
    expect(container.textContent).toContain("Closed");
    expect(container.textContent).toContain("Profile is closed");
    expect(container.textContent).not.toContain("Hours played");
    expect(container.textContent).not.toContain("Winrate");
  });

  it("says so when the player has no Overwatch account", async () => {
    await mount([], tab);
    expect(container.textContent).toContain("No Overwatch account");
  });

  it("switches the whole portrait with the account chip", async () => {
    await mount(
      [
        account(1, "main#1", { is_primary: true }),
        account(2, "smurf#2", { queues: [queue({ seconds: 7200, games_played: 9 })] })
      ],
      tab
    );
    expect(container.textContent).toContain("3.5 h");
    const chips = [...container.querySelectorAll('[role="radio"]')].filter((chip) => chip.textContent?.includes("#2"));
    await act(async () => (chips[0] as HTMLElement).click());
    expect(container.textContent).toContain("smurfKitten of Discord");
    expect(container.textContent).toContain("2 h");
    expect(container.textContent).not.toContain("3.5 h");
  });

  it("puts the primary account first", async () => {
    await mount([account(2, "smurf#2"), account(1, "main#1", { is_primary: true })], tab);
    const chips = [...container.querySelectorAll('[role="radio"]')].map((chip) => chip.textContent);
    expect(chips[0]).toContain("main");
    expect(chips[0]).toContain("Main");
  });

  it("marks our tournament figure up or down, coloured by whether it beats the ladder (deaths: lower is better)", async () => {
    services.characters.mockResolvedValue({
      results: [
        // Ladder Ana: 13.33 elims, 3.37 deaths, 8892 healing per 10.
        ourHero("ana", "Ana", { eliminations: 15, deaths: 2.5, healing_dealt: 6000 }),
        // Ashe is not played in our tournaments: left out.
        ourHero("sigma", "Sigma", { eliminations: 20 })
      ]
    });
    await mount([account(1, "main#1", { is_primary: true })], tab);

    const row = (label: string) =>
      [...container.querySelectorAll("section[aria-label='Ana'] tbody tr")].find((tr) => tr.textContent?.startsWith(label));
    const mark = (label: string) => row(label)?.querySelector("[data-direction]");

    expect(mark("Eliminations")?.getAttribute("data-direction")).toBe("up");
    expect(mark("Eliminations")?.getAttribute("style")).toContain("--aqt-emerald");
    // Fewer deaths than on the ladder: the value is down, and that is good.
    expect(mark("Deaths")?.getAttribute("data-direction")).toBe("down");
    expect(mark("Deaths")?.getAttribute("style")).toContain("--aqt-emerald");
    expect(mark("Deaths")?.textContent).toContain("Better than on the ladder");
    // Less healing: down, and bad.
    expect(mark("Healing")?.getAttribute("data-direction")).toBe("down");
    expect(mark("Healing")?.getAttribute("style")).toContain("--aqt-rose");
    expect(container.querySelector("section[aria-label='Ashe']")).toBeNull();
    expect(container.textContent).toContain("4 maps in our tournaments · 6 games this season");
  });

  it("draws the ladder meta only when the server sent it", async () => {
    const withMeta = (characters: CareerCharacter[], metaFit?: number) => [
      account(1, "main#1", { is_primary: true, queues: [queue({ characters, meta_fit: metaFit })] })
    ];
    await mount(withMeta([hero("ana", "support", { games_played: 20, winrate: 0.6 })]), tab);
    expect(container.textContent).not.toContain("Meta fit");
    // The role's effective number of heroes, a fraction: plural "heroes", never the old "pool".
    expect(container.textContent).toContain("≈ 3.4 heroes");
    expect(container.textContent).not.toContain("vs ladder");

    await act(async () => root.unmount());
    root = createRoot(container);
    await mount(
      withMeta([
        hero("ana", "support", {
          games_played: 20,
          winrate: 0.6,
          meta: { division: "diamond", pickrate: 0.1, winrate: 0.5, banrate: null }
        })
      ], 0.31),
      tab
    );
    expect(container.textContent).toContain("Meta fit");
    expect(container.textContent).toContain("31%");
    expect(container.textContent).toContain("vs ladder");
    expect(container.textContent).toContain("10 pp");
  });
});

describe("overview ladder card", () => {
  it("is absent when no account has career data", async () => {
    await mount([closed], overview);
    expect(container.textContent).toBe("");
  });

  it("links to the ladder tab and sums up the main account", async () => {
    await mount([account(1, "main#1", { is_primary: true })], overview);
    expect(container.textContent).toContain("20 games · 55% · 3.5 h");
    expect(container.querySelector("a")?.getAttribute("href")).toBe("/users/Someone?tab=ladder");
  });
});
