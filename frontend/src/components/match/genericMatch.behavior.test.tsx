// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MatchRowBadge from "@/components/match/MatchRowBadge";
import MatchStatistics from "@/components/match/MatchStatistics";
import { useSegmentLabel } from "@/components/match/segment-label";
import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import { disciplineQueryKeys } from "@/lib/site/discipline-query-keys";
import { catalogEntity } from "@/test/catalog";
import type { DisciplineMetadata } from "@/types/discipline.types";
import type { MatchWithStats } from "@/types/encounter.types";
import type { MatchEvents } from "@/types/killfeed.types";
import type { MatchWithUserStats } from "@/types/user.types";

const { getMatchKillFeed, getMetadata } = vi.hoisted(() => ({
  getMatchKillFeed: vi.fn(),
  getMetadata: vi.fn()
}));
vi.mock("@/services/encounter.service", () => ({ default: { getMatchKillFeed } }));
vi.mock("@/services/discipline.service", () => ({
  default: { list: async () => [], metadata: (...args: unknown[]) => getMetadata(...args) }
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ number: (value: number) => String(value) })
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: () => undefined }) }));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Radix's Select reaches for pointer-capture and scroll APIs happy-dom does not implement.
for (const [name, value] of Object.entries({
  hasPointerCapture: () => false,
  setPointerCapture: () => undefined,
  releasePointerCapture: () => undefined,
  scrollIntoView: () => undefined
})) {
  if (!(name in Element.prototype)) {
    Object.defineProperty(Element.prototype, name, { value, writable: true });
  }
}

let root: Root | null = null;
let client: QueryClient | null = null;

/** A discipline with no module (an unknown game must never borrow Overwatch's): the generic views render. */
const metadata = {
  discipline: { code: "lol", capabilities: {} },
  stat_defs: [
    {
      id: 1,
      code: "kills",
      name: "Kills",
      value_format: "integer",
      aggregation: "sum",
      group: null,
      active: true,
      sort_order: 1
    },
    {
      id: 2,
      code: "winrate",
      name: "Win rate",
      value_format: "percent",
      aggregation: "avg",
      group: null,
      active: true,
      sort_order: 2
    },
    {
      id: 3,
      code: "time",
      name: "Duration",
      value_format: "duration",
      aggregation: "sum",
      group: null,
      active: true,
      sort_order: 3
    }
  ],
  event_types: [{ id: 1, code: "kill", name: "Kill", active: true }]
} as unknown as DisciplineMetadata;

const ASHE = catalogEntity({ id: 500, name: "Ashe" });
const fact = (
  team: number,
  member: number | null,
  stat_code: string,
  value: number,
  entity_id: number | null = null,
  segment = 0
) => ({
  encounter_team_id: team,
  workspace_member_id: member,
  entity_id,
  segment,
  stat_code,
  value
});
const member = (team: number, id: number, player: number, handle: string, canonical: string | null) => {
  const at = handle.lastIndexOf("#");
  return {
    encounter_team_id: team,
    workspace_member_id: id,
    player_id: player,
    display: { name: at > 0 ? handle.slice(0, at) : handle, tag: at > 0 ? handle.slice(at) : null, canonical, snapshot: null },
    handle_snapshot: handle,
    observed_role: null
  };
};

/** Three participants; the only member facts are Ashe's (entity grain); team 1 has a percent and a duration team fact. */
function lobby(): MatchWithStats {
  const participant = (id: number, slot: number, facts: Record<string, number>) => ({
    encounter_team_id: id,
    slot,
    source_position: slot - 1,
    tournament_team_id: null,
    name: `Team ${id}`,
    result: null,
    team_facts: facts
  });
  return {
    id: 7,
    workspace_id: 1,
    discipline: "lol",
    created_at: "2026-01-01T00:00:00Z",
    played_at: null,
    encounter: null,
    participants: [
      participant(1, 1, { winrate: 0.5, time: 125 }),
      participant(2, 2, {}),
      participant(3, 3, {})
    ],
    statistics: {
      members: [
        member(1, 10, 1, "Ann#1", "Canonical Ann"),
        // Another player's canonical name equals this handle: the link must still follow the member's own player.
        member(2, 20, 2, "Canonical Ann", "Real Bob"),
        member(3, 30, 3, "Cy#3", null)
      ],
      segments: [{ segment: 1, kind: "round", attrs: {} }],
      facts: [
        fact(1, 10, "kills", 9, ASHE.id),
        fact(2, 20, "kills", 4, ASHE.id),
        fact(1, null, "winrate", 0.5),
        fact(1, null, "time", 125)
      ],
      entities: [ASHE]
    }
  } as unknown as MatchWithStats;
}

async function mount(node: ReactNode, seed: DisciplineMetadata | null = metadata) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  if (seed) client.setQueryData(disciplineQueryKeys.metadata(1, "lol"), seed);
  const container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(<QueryClientProvider client={client!}>{node}</QueryClientProvider>);
  });
  return container;
}

async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    (element as HTMLElement).click();
  });
}

/** Lets a settled read reach the view: react-query notifies its observers on a zero timeout, so wait one out in act. */
async function settle() {
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
}

/** The select whose accessible label is `label`: it must be named by a visible element carrying that text. */
function combobox(container: HTMLElement, label: string): HTMLElement {
  for (const trigger of container.querySelectorAll<HTMLElement>('[role="combobox"]')) {
    const labelId = trigger.getAttribute("aria-labelledby");
    if (labelId && container.querySelector(`#${CSS.escape(labelId)}`)?.textContent === label)
      return trigger;
  }
  throw new Error(`no select is labelled "${label}"`);
}

afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  client?.clear();
  root = null;
  client = null;
  document.body.innerHTML = "";
});
beforeEach(() => {
  getMatchKillFeed.mockReset();
  getMetadata.mockReset();
});

describe("the generic statistics view", () => {
  it("never claims a match recorded nothing when its member facts are entity-grain, and offers them as a grain", async () => {
    const container = await mount(<MatchStatistics match={lobby()} />);
    expect(container.textContent).not.toContain(en.matches.native.noStats);
    expect(container.textContent).toContain(en.matches.native.noValues);

    const grain = combobox(container, en.matches.native.grainLabel);
    // The segment select is named too.
    combobox(container, en.matches.native.segmentLabel);

    await click(grain);
    const option = [...document.querySelectorAll('[role="option"]')].find(
      (node) => node.textContent === "Ashe"
    )!;
    await click(option);
    const bodies = [...container.querySelectorAll("tbody")];
    expect(bodies).toHaveLength(3);
    expect([...bodies[0].querySelectorAll("td")].map((cell) => cell.textContent)).toContain("9");
    expect([...bodies[1].querySelectorAll("td")].map((cell) => cell.textContent)).toContain("4");
    // The page-level "no values" note is gone; only the participant with no Ashe rows says so.
    expect([...container.querySelectorAll("p")].map((node) => node.textContent)).not.toContain(
      en.matches.native.noValues
    );
    expect(bodies[2].textContent).toContain(en.matches.native.noValues);
  });

  it("formats declared team facts through their definitions even though no member column carries them", async () => {
    const container = await mount(<MatchStatistics match={lobby()} />);
    const header = container.querySelector("tbody tr")!;
    expect(header.textContent).toContain("Win rate: 50.0%");
    expect(header.textContent).toContain("Duration: 2m 5s");
  });

  it("links a handle only through its player's canonical name, and leaves one without it unlinked", async () => {
    const container = await mount(<MatchStatistics match={lobby()} />);
    await click(combobox(container, en.matches.native.grainLabel));
    await click(
      [...document.querySelectorAll('[role="option"]')].find((node) => node.textContent === "Ashe")!
    );
    const links = [...container.querySelectorAll<HTMLAnchorElement>('a[href^="/users/"]')];
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      // The whole handle is the link; its `#tag` renders as faint text inside it.
      ["Ann#1", "/users/Canonical Ann"],
      ["Canonical Ann", "/users/Real Bob"]
    ]);
    // Cy has no canonical name: shown, not linked.
    expect(container.textContent).not.toContain("Cy");
  });

  it("keeps the timeline of a match no duel renderer takes, with every participant named", async () => {
    const feed: MatchEvents = {
      match_id: 7,
      discipline: "lol",
      entities: [ASHE],
      events: [
        {
          id: 2,
          segment: 1,
          t: 65,
          type: "kill",
          actor_member_id: 30,
          actor_team_id: 3,
          target_member_id: 10,
          target_team_id: 1,
          entity_id: 500,
          related_entity_id: null,
          data: null
        },
        {
          id: 1,
          segment: 0,
          t: 5,
          type: "kill",
          actor_member_id: 10,
          actor_team_id: 1,
          target_member_id: null,
          target_team_id: 2,
          entity_id: null,
          related_entity_id: null,
          data: { fight: 1 }
        }
      ]
    };
    getMatchKillFeed.mockResolvedValue(feed);
    const container = await mount(<MatchStatistics match={lobby()} />);
    expect(getMatchKillFeed).not.toHaveBeenCalled(); // read only when the timeline is opened
    const tab = [...container.querySelectorAll<HTMLElement>('[role="tab"]')].find(
      (node) => node.textContent === en.matches.tab.timeline
    )!;
    await act(async () => {
      tab.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
      tab.click();
    });
    await settle();
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
    const rows = [...container.querySelectorAll("ol li")].map((row) => row.textContent);
    expect(rows[0]).toContain("0:05");
    expect(rows[0]).toContain("Kill");
    expect(rows[0]).toContain("Ann (Team 1)");
    expect(rows[0]).toContain("Team 2");
    expect(rows[1]).toContain("1:05");
    expect(rows[1]).toContain("Cy (Team 3)");
    expect(rows[1]).toContain("Ashe");
  });

  it("says a timeline could not load and offers a retry; an empty one says so", async () => {
    getMatchKillFeed
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValue({ match_id: 7, discipline: "lol", entities: [], events: [] });
    const container = await mount(<MatchStatistics match={lobby()} />);
    const tab = [...container.querySelectorAll<HTMLElement>('[role="tab"]')].find(
      (node) => node.textContent === en.matches.tab.timeline
    )!;
    await act(async () => {
      tab.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
      tab.click();
    });
    await settle();
    expect(container.textContent).toContain(en.matches.native.timeline.error);
    await click(
      [...container.querySelectorAll("button")].find(
        (node) => node.textContent === en.common.retry
      )!
    );
    await settle();
    expect(container.textContent).toContain(en.matches.native.timeline.empty);
  });
});

describe("segment labels", () => {
  function Labels({ kinds }: Readonly<{ kinds: string[] }>) {
    const label = useSegmentLabel(kinds.map((kind, index) => ({ segment: index + 1, kind })));
    return <p>{[0, ...kinds.map((_, index) => index + 1)].map(label).join("|")}</p>;
  }
  const render = async (locale: "en" | "ru", messages: typeof en) => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root!.render(
        <NextIntlClientProvider locale={locale} messages={messages} timeZone="UTC">
          <Labels kinds={["round", "half"]} />
        </NextIntlClientProvider>
      );
    });
    return container.textContent;
  };

  it("localizes a known kind and reads an unknown one as a neutral numbered segment", async () => {
    expect(await render("en", en)).toBe("All Match|Round 1|Segment 2");
  });

  it("does the same in Russian, never printing the raw kind code", async () => {
    const text = await render("ru", ru as unknown as typeof en);
    expect(text).toBe("Весь матч|Раунд 1|Сегмент 2");
    expect(text).not.toContain("round");
  });
});

describe("MatchRowBadge", () => {
  const row = (overrides: Partial<MatchWithUserStats> = {}) =>
    ({
      workspace_id: 1,
      discipline: "lol",
      viewer: { facts: {}, characters: [] },
      participants: [],
      map: { name: "M" },
      ...overrides
    }) as unknown as MatchWithUserStats;

  it("is absent only for a match the viewer was not observed in", async () => {
    const container = await mount(<MatchRowBadge match={row({ viewer: null })} />);
    expect(container.innerHTML).toBe("");
  });

  it("holds a placeholder while the game's metadata loads, not nothing", async () => {
    const slow = Promise.withResolvers<DisciplineMetadata>();
    getMetadata.mockReturnValue(slow.promise);
    const container = await mount(<MatchRowBadge match={row()} />, null);
    expect(container.innerHTML).not.toBe("");
    expect(container.querySelector('[aria-hidden="true"]')).not.toBeNull();
    slow.resolve(metadata);
  });

  it("says the metadata read failed and retries it, instead of silently dropping the badge", async () => {
    getMetadata.mockRejectedValueOnce(new Error("down")).mockResolvedValue(metadata);
    const container = await mount(<MatchRowBadge match={row()} />, null);
    await settle();
    expect(container.querySelector("button")).not.toBeNull();
    const retry = container.querySelector("button")!;
    expect(retry.getAttribute("title")).toBe(en.matches.native.badgeError);
    await click(retry);
    await settle();
    expect(container.querySelector("button")).toBeNull();
    expect(getMetadata).toHaveBeenCalled();
  });
});
