// @vitest-environment happy-dom
//
// The leaderboard is a read of the permanent match log, so what it must get
// right is the reading, not the counting:
//
//  1. rows land in the order the caller ranked them, each with its record and
//     win percentage -- re-sorting here would risk disagreeing with the server;
//  2. a streak pill only appears while there is a run to report;
//  3. the window chips report the reader's choice upward, since the query key
//     (and not this component) owns which window is fetched.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MixMemberStats } from "@/services/custom-game.service";

import { PickupLeaderboard } from "./PickupLeaderboard";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/components/PlayerRoleIcon", () => ({ default: () => null }));

const onRetry = vi.fn();
const onPeriodChange = vi.fn();

function member(overrides: Partial<MixMemberStats> = {}): MixMemberStats {
  return {
    workspace_member_id: 1,
    display_name: "Aria",
    battle_tag: "Aria#1111",
    games: 20,
    wins: 12,
    losses: 8,
    draws: 0,
    win_rate: 0.6,
    streak: 3,
    last_played_at: "2026-01-05T20:00:00Z",
    by_role: { tank: { games: 20, wins: 12, losses: 8, draws: 0 } },
    ...overrides,
  };
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

const roots: { unmount: () => void }[] = [];

async function mount(
  members: MixMemberStats[],
  props: { loading?: boolean; error?: boolean } = {},
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    const root = createRoot(container);
    roots.push(root);
    root.render(
      <PickupLeaderboard
        members={members}
        loading={props.loading ?? false}
        error={props.error ?? false}
        onRetry={onRetry}
        period="all"
        onPeriodChange={onPeriodChange}
      />,
    );
  });
  await act(async () => {
    await tick();
  });
  return container;
}

function click(node: Element | null | undefined) {
  if (!node) throw new Error("Expected a clickable node");
  return act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

function byName(scope: ParentNode, name: string) {
  return [...scope.querySelectorAll("button")].find((node) => node.textContent?.trim() === name) ?? null;
}

function rows(scope: ParentNode) {
  return [...scope.querySelectorAll("li")];
}

beforeEach(() => {
  while (roots.length > 0) {
    const root = roots.pop();
    act(() => root?.unmount());
  }
  document.body.innerHTML = "";
  onRetry.mockReset();
  onPeriodChange.mockReset();
});

describe("PickupLeaderboard", () => {
  it("ranks rows in the order given, with each record and win percentage", async () => {
    const scope = await mount([
      member({ workspace_member_id: 1, display_name: "Aria" }),
      member({
        workspace_member_id: 2,
        display_name: "Bex",
        wins: 9,
        losses: 9,
        draws: 2,
        games: 20,
        win_rate: 0.45,
      }),
    ]);

    const [first, second] = rows(scope);
    expect(first.textContent).toContain("#1");
    expect(first.textContent).toContain("Aria");
    expect(first.textContent).toContain("12–8");
    expect(first.textContent).toContain("60%");
    expect(second.textContent).toContain("#2");
    expect(second.textContent).toContain("9–9–2");
    expect(second.textContent).toContain("45%");
  });

  it("falls back to the battletag for a member who left the roster", async () => {
    const scope = await mount([member({ display_name: null })]);

    expect(scope.textContent).toContain("Aria#1111");
  });

  it("shows a running streak and nothing at all once it is broken", async () => {
    const withStreak = await mount([member({ streak: 3 })]);
    expect(withStreak.textContent).toContain("W3");

    const broken = await mount([member({ streak: 0 })]);
    expect(broken.textContent).not.toMatch(/[WL]\d/);
  });

  it("names each role's own record on its glyph", async () => {
    const scope = await mount([
      member({
        by_role: {
          tank: { games: 8, wins: 5, losses: 3, draws: 0 },
          support: { games: 12, wins: 7, losses: 5, draws: 0 },
        },
      }),
    ]);

    const titles = [...scope.querySelectorAll("[title]")].map((node) => node.getAttribute("title"));
    expect(titles).toEqual(["tank 5–3", "support 7–5"]);
  });

  it("reports the window the reader picked instead of filtering on its own", async () => {
    const scope = await mount([member()]);

    await click(byName(scope, "7 days"));

    expect(onPeriodChange).toHaveBeenCalledWith("7d");
  });

  it("explains an empty board rather than showing a blank card", async () => {
    const scope = await mount([]);

    expect(scope.textContent).toContain("No mix results yet");
    expect(scope.textContent).toContain("Players appear after 3 recorded matches.");
  });

  it("offers a retry when the record fails to load", async () => {
    const scope = await mount([], { error: true });

    await click(byName(scope, "Retry"));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
