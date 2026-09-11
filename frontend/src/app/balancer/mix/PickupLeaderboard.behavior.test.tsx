// @vitest-environment happy-dom

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import type { MixMemberStats } from "@/services/custom-game.service";

import { PickupLeaderboard } from "./PickupLeaderboard";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

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
    ...overrides
  };
}

const mounts: { root: Root; container: HTMLDivElement }[] = [];

afterEach(() => {
  for (const { root, container } of mounts.splice(0)) {
    act(() => root.unmount());
    container.remove();
  }
});

async function mount(
  members: MixMemberStats[],
  props: {
    loading?: boolean;
    error?: boolean;
    period?: "all" | "30d" | "7d";
    onPeriodChange?: (p: "all" | "30d" | "7d") => void;
    onRetry?: () => void;
  } = {}
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mounts.push({ root, container });
  const onRetry = props.onRetry ?? vi.fn();
  const onPeriodChange = props.onPeriodChange ?? vi.fn();

  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <PickupLeaderboard
          members={members}
          loading={props.loading ?? false}
          error={props.error ?? false}
          onRetry={onRetry}
          period={props.period ?? "all"}
          onPeriodChange={onPeriodChange}
        />
      </NextIntlClientProvider>
    );
  });
  return { container, onRetry, onPeriodChange };
}

async function click(node: Element | null | undefined) {
  if (!node) throw new Error("Expected a clickable node");
  await act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function rows(scope: ParentNode) {
  return [...scope.querySelectorAll("ol li")];
}

describe("PickupLeaderboard", () => {
  it("ranks rows in the order given, showing rank, name, wins, and win rate", async () => {
    const { container } = await mount([
      member({ workspace_member_id: 1, display_name: "Aria", wins: 12, win_rate: 0.6 }),
      member({
        workspace_member_id: 2,
        display_name: "Bex",
        wins: 9,
        losses: 9,
        draws: 2,
        games: 20,
        win_rate: 0.45
      })
    ]);

    const [first, second] = rows(container);
    expect(first.textContent).toContain("#1");
    expect(first.textContent).toContain("Aria");
    expect(first.textContent).toContain("12");
    expect(first.textContent).toContain("60%");

    expect(second.textContent).toContain("#2");
    expect(second.textContent).toContain("Bex");
    expect(second.textContent).toContain("9");
    expect(second.textContent).toContain("45%");
  });

  it("falls back to the battletag or raw member id when display name is not set", async () => {
    const { container: tagContainer } = await mount([
      member({ display_name: null, battle_tag: "Aria#1111" })
    ]);
    expect(tagContainer.textContent).toContain("Aria#1111");

    const { container: idContainer } = await mount([
      member({ display_name: null, battle_tag: null, workspace_member_id: 42 })
    ]);
    expect(idContainer.textContent).toContain("#42");
  });

  it("discloses full details with losses, draws, streak, and role records", async () => {
    const { container } = await mount([
      member({
        wins: 10,
        losses: 5,
        draws: 1,
        games: 16,
        streak: 3,
        by_role: {
          tank: { games: 10, wins: 7, losses: 3, draws: 0 }
        }
      })
    ]);

    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    expect(details?.textContent).toContain("Show detailed results");
    expect(details?.textContent).toContain("3 consecutive wins");
    expect(details?.textContent).toContain("Tank");

    const zeroStreak = await mount([member({ streak: 0 })]);
    expect(zeroStreak.container.querySelector("details")?.textContent).toContain(
      "No current streak"
    );
  });

  it("reports period changes through the accessible select", async () => {
    const onPeriodChange = vi.fn();
    const { container } = await mount([member()], { period: "all", onPeriodChange });

    const select = container.querySelector("select");
    expect(select).not.toBeNull();
    await act(async () => {
      if (select) {
        select.value = "7d";
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });

    expect(onPeriodChange).toHaveBeenCalledWith("7d");
  });

  it("explains an empty board and allows resetting to all time when filtered", async () => {
    const onPeriodChange = vi.fn();
    const { container } = await mount([], { period: "30d", onPeriodChange });

    expect(container.textContent).toContain("No qualifying players in this period");
    const allTimeButton = [...container.querySelectorAll("button")].find((btn) =>
      btn.textContent?.includes("Show all time")
    );
    expect(allTimeButton).toBeDefined();
    await click(allTimeButton);
    expect(onPeriodChange).toHaveBeenCalledWith("all");
  });

  it("offers a retry when the record fails to load", async () => {
    const onRetry = vi.fn();
    const { container } = await mount([], { error: true, onRetry });

    const retryBtn = [...container.querySelectorAll("button")].find((btn) =>
      btn.textContent?.includes("Retry")
    );
    expect(retryBtn).toBeDefined();
    await click(retryBtn);

    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
