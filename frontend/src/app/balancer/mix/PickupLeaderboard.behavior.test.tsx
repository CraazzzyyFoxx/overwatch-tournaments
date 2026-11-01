// @vitest-environment happy-dom

import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";

import { PickupLeaderboard, PickupRatingTable } from "./PickupLeaderboard";
import type { RatedPlayer, StatsPeriodKey } from "./pickup-stats";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function player(index: number, overrides: Partial<RatedPlayer> = {}): RatedPlayer {
  return {
    key: `p:${index}`,
    playerId: index,
    display: { name: `Player${index}`, tag: `#${1000 + index}`, canonical: `Player${index}#${1000 + index}`, snapshot: null },
    games: 20,
    wins: 40 - index,
    losses: index - 20,
    draws: 0,
    winRate: (40 - index) / 20,
    streak: 0,
    streakOpen: false,
    form: [],
    lastPlayedAt: null,
    byRole: null,
    ...overrides
  };
}

const board = (count: number) =>
  Array.from({ length: count }, (_, index) => player(index + 1, { wins: 30 - index, games: 40, winRate: 0.5 }));

const mounts: { root: Root; container: HTMLDivElement }[] = [];

afterEach(() => {
  for (const { root, container } of mounts.splice(0)) {
    act(() => root.unmount());
    container.remove();
  }
});

async function mount(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mounts.push({ root, container });
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        {node}
      </NextIntlClientProvider>
    );
  });
  return container;
}

async function click(node: Element | null | undefined) {
  if (!node) throw new Error("Expected a clickable node");
  await act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function props(ranked: RatedPlayer[], overrides: { viewer?: RatedPlayer | null; period?: StatsPeriodKey; error?: boolean } = {}) {
  return {
    ranked,
    viewer: overrides.viewer ?? null,
    loading: false,
    error: overrides.error ?? false,
    onRetry: vi.fn(),
    period: overrides.period ?? ("all" as StatsPeriodKey),
    onPeriodChange: vi.fn(),
    allCommunities: false,
    ontology: null
  };
}

const rows = (scope: ParentNode) => [...scope.querySelectorAll("tbody tr")].map((row) => row.textContent ?? "");
const button = (scope: ParentNode, label: string) =>
  [...scope.querySelectorAll("button")].find((node) => node.textContent?.trim() === label);

describe("PickupLeaderboard", () => {
  it("shows the top ten in order, each with rank, name, wins of games and win rate", async () => {
    const container = await mount(<PickupLeaderboard {...props(board(12))} fullHref="/balancer/mix?view=rating" />);

    const shown = rows(container);
    expect(shown).toHaveLength(10);
    expect(shown[0]).toContain("01");
    expect(shown[0]).toContain("Player1#1001");
    expect(shown[0]).toContain("30/40");
    expect(shown[0]).toContain("50%");
    expect(shown[9]).toContain("Player10");
    expect(container.querySelector('a[href="/balancer/mix?view=rating"]')?.textContent).toContain("Full leaderboard");
  });

  it("pins the reader's own row under the top ten, with their rank", async () => {
    const ranked = board(14);
    const container = await mount(<PickupLeaderboard {...props(ranked, { viewer: ranked[12] })} fullHref="#" />);

    const shown = rows(container);
    expect(shown).toHaveLength(11);
    expect(shown[10]).toContain("13");
    expect(shown[10]).toContain("Player13");
    expect(shown[10]).toContain("You");
  });

  it("marks the reader in place inside the top ten instead of repeating them", async () => {
    const ranked = board(12);
    const container = await mount(<PickupLeaderboard {...props(ranked, { viewer: ranked[2] })} fullHref="#" />);

    const shown = rows(container);
    expect(shown).toHaveLength(10);
    expect(shown[2]).toContain("You");
  });

  it("tells an unranked reader how many matches they still need", async () => {
    const viewer = player(99, { games: 2, wins: 1 });
    const container = await mount(<PickupLeaderboard {...props(board(3), { viewer })} fullHref="#" />);

    expect(rows(container)).toHaveLength(4);
    expect(container.textContent).toContain("You have 2 of the 3 matches needed to be ranked.");
  });

  it("reports a period change from the segmented control", async () => {
    const shared = props(board(3));
    const container = await mount(<PickupLeaderboard {...shared} fullHref="#" />);

    expect(container.querySelector('[role="radiogroup"]')?.getAttribute("aria-label")).toBe("Results period");
    await click(container.querySelector('[role="radio"]:last-child'));
    expect(shared.onPeriodChange).toHaveBeenCalledWith("7d");
  });

  it("explains an empty board and resets a narrowed period to all time", async () => {
    const shared = props([], { period: "30d" });
    const container = await mount(<PickupLeaderboard {...shared} fullHref="#" />);

    expect(container.textContent).toContain("No qualifying players in this period");
    await click(button(container, "Show all time"));
    expect(shared.onPeriodChange).toHaveBeenCalledWith("all");
  });

  it("offers a retry when the record fails to load", async () => {
    const shared = props([], { error: true });
    const container = await mount(<PickupLeaderboard {...shared} fullHref="#" />);

    await click(button(container, "Retry"));
    expect(shared.onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("PickupRatingTable", () => {
  it("pages a long board and finds a player by name without renumbering them", async () => {
    const container = await mount(<PickupRatingTable {...props(board(60))} />);
    expect(rows(container)).toHaveLength(50);

    const search = container.querySelector<HTMLInputElement>('input[type="search"]');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setter?.call(search, "player57");
      search?.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const found = rows(container);
    expect(found).toHaveLength(1);
    expect(found[0]).toContain("57");
    expect(found[0]).toContain("Player57#1057");
  });

  it("names a streak for screen readers, and says when it may run past the form window", async () => {
    const container = await mount(
      <PickupRatingTable {...props([player(1, { streak: 3 }), player(2, { streak: -10, streakOpen: true })])} />
    );

    const labels = [...container.querySelectorAll('[role="img"]')].map((node) => node.getAttribute("aria-label"));
    expect(labels).toEqual(["3 consecutive wins", "10 consecutive losses"]);
    expect(rows(container)[1]).toContain("L10+");
  });
});
