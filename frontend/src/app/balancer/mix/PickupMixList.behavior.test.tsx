// @vitest-environment happy-dom

import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import messages from "@/i18n/messages/en.json";
import type { CustomGame } from "@/services/custom-game.service";

import { PickupMixList } from "./PickupMixList";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function game(id: number, status: CustomGame["status"]): CustomGame {
  return {
    id,
    workspace_id: 7,
    host_user_id: 9,
    co_hosts: [],
    host_display_name: "HostTag#1234",
    name: `Mix ${id}`,
    status,
    settings: {
      points_per_win: null,
      team_names: {},
      role_mask: null,
      balancer_config: null,
      discord_channel_id: null,
      workspace_discord_channel_id: null
    },
    balance_result: null,
    created_at: "2026-01-02T00:00:00Z",
    next_map_id: null,
    roster_shape: null,
    matches_count: 0,
    last_match_at: null
  };
}

const mounts: { root: Root; container: HTMLDivElement }[] = [];

afterEach(() => {
  for (const { root, container } of mounts.splice(0)) {
    act(() => root.unmount());
    container.remove();
  }
});

async function mount(games: CustomGame[], canEdit = false) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mounts.push({ root, container });
  const onCreateGame = vi.fn();
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
        <PickupMixList
          canEdit={canEdit}
          games={games}
          loading={false}
          error={false}
          onRetry={vi.fn()}
          onCreateGame={onCreateGame}
        />
      </NextIntlClientProvider>
    );
  });
  return { container, onCreateGame };
}

async function click(node: Element | null | undefined) {
  if (!node) throw new Error("Expected a clickable node");
  await act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function filters(container: ParentNode) {
  return [...container.querySelectorAll('[role="group"] button')];
}

function destinations(container: ParentNode) {
  return [...container.querySelectorAll("li a")].map((link) => link.getAttribute("href"));
}

describe("PickupMixList", () => {
  it("partitions terminal statuses, preserves source order and lets viewers navigate either view", async () => {
    const { container, onCreateGame } = await mount([
      game(8, "completed"),
      game(3, "balanced"),
      game(11, "cancelled"),
      game(5, "draft"),
      game(2, "completed")
    ]);
    const [open, history] = filters(container);

    expect(destinations(container)).toEqual(["/balancer/mix/3", "/balancer/mix/5"]);
    expect(open.getAttribute("aria-pressed")).toBe("true");
    expect(open.querySelector(".aqt-count")?.textContent).toBe("2");
    expect(history.querySelector(".aqt-count")?.textContent).toBe("3");

    await click(history);
    expect(destinations(container)).toEqual([
      "/balancer/mix/8",
      "/balancer/mix/11",
      "/balancer/mix/2"
    ]);
    expect(history.getAttribute("aria-pressed")).toBe("true");
    expect(open.getAttribute("aria-pressed")).toBe("false");

    await click(open);
    expect(destinations(container)).toEqual(["/balancer/mix/3", "/balancer/mix/5"]);
    expect(container.querySelectorAll("button")).toHaveLength(2);
    expect(onCreateGame).not.toHaveBeenCalled();
  });

  it("offers a route out of either empty partition", async () => {
    const pastOnly = await mount([game(4, "cancelled")]);
    expect(destinations(pastOnly.container)).toEqual([]);
    await click(pastOnly.container.querySelector('[role="status"] button'));
    expect(destinations(pastOnly.container)).toEqual(["/balancer/mix/4"]);
    expect(filters(pastOnly.container)[1].getAttribute("aria-pressed")).toBe("true");

    const openOnly = await mount([game(7, "draft")]);
    await click(filters(openOnly.container)[1]);
    expect(destinations(openOnly.container)).toEqual([]);
    await click(openOnly.container.querySelector('[role="status"] button'));
    expect(destinations(openOnly.container)).toEqual(["/balancer/mix/7"]);
    expect(filters(openOnly.container)[0].getAttribute("aria-pressed")).toBe("true");
  });

  it("offers creation for an empty workspace only to hosts, including after changing filters", async () => {
    const host = await mount([], true);
    await click(host.container.querySelector('[role="status"] button'));
    expect(host.onCreateGame).toHaveBeenCalledTimes(1);

    const viewer = await mount([]);
    expect(viewer.container.querySelector('[role="status"] button')).toBeNull();
    await click(filters(viewer.container)[1]);
    expect(viewer.container.querySelector('[role="status"] button')).toBeNull();
    expect(viewer.container.querySelectorAll("button")).toHaveLength(2);
    expect(viewer.onCreateGame).not.toHaveBeenCalled();
  });
});
