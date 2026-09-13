// @vitest-environment happy-dom
//
// The dialog writes one config blob holding two differently-gated things: the
// pool's rank-delta knobs (`team.update`) and the workspace mix channel
// (`workspace.update`). A viewer who may only do the former must be unable to
// move the channel, so the save it sends carries the stored one untouched and
// never 403s the whole dialog.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkspaceBalancerConfig } from "@/types/balancer-admin.types";

import { WorkspaceBalancerConfigDialog } from "./WorkspaceBalancerConfigDialog";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

// Stands in as the plain field underneath: the real picker fetches the guild's
// channels, and what this dialog owes it is value/onChange/disabled.
vi.mock("@/components/discord/DiscordChannelSelect", () => ({
  DiscordChannelSelect: ({
    value,
    onChange,
    disabled,
    ariaLabel,
  }: {
    value: string;
    onChange: (channelId: string) => void;
    disabled?: boolean;
    ariaLabel?: string;
  }) => (
    <input
      aria-label={ariaLabel}
      disabled={disabled}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
}));

const granted = new Set<string>();
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: (permission: string) => granted.has(permission),
  }),
}));

const upsert = vi.fn();
vi.mock("@/services/balancer-admin.service", () => ({
  default: {
    upsertWorkspaceBalancerConfig: (...args: unknown[]) => upsert(...args),
  },
}));

const WORKSPACE_ID = 7;

const CONFIG: WorkspaceBalancerConfig = {
  id: 1,
  workspace_id: WORKSPACE_ID,
  rank_delta_threshold: 500,
  rank_delta_hide_from_pool: true,
  mix_discord_channel_id: "555555555555555555",
  updated_by: null,
};

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  await act(async () => {
    createRoot(container).render(
      <QueryClientProvider client={client}>
        <WorkspaceBalancerConfigDialog
          workspaceId={WORKSPACE_ID}
          config={CONFIG}
          open
          onOpenChange={vi.fn()}
        />
      </QueryClientProvider>,
    );
  });
  await act(async () => {
    await tick();
  });
  // The dialog renders in a portal, so assertions read the document.
  return document.body;
}

function channelField(scope: ParentNode) {
  const field = scope.querySelector<HTMLInputElement>('input[aria-label="Mix Discord channel"]');
  if (!field) throw new Error("Expected the mix channel field");
  return field;
}

function byName(scope: ParentNode, name: string) {
  return [...scope.querySelectorAll("button")].find((node) => node.textContent?.trim() === name) ?? null;
}

function click(node: Element | null | undefined) {
  if (!node) throw new Error("Expected a clickable node");
  return act(async () => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

beforeEach(() => {
  document.body.innerHTML = "";
  granted.clear();
  upsert.mockReset().mockResolvedValue(CONFIG);
});

describe("WorkspaceBalancerConfigDialog", () => {
  it("saves the pool knobs with the stored channel for a non-admin", async () => {
    const scope = await mount();

    expect(channelField(scope).disabled).toBe(true);
    expect(byName(scope, "Clear")).toBeNull();

    await click(byName(scope, "Save"));

    expect(upsert).toHaveBeenCalledWith(WORKSPACE_ID, {
      rank_delta_threshold: 500,
      rank_delta_hide_from_pool: true,
      mix_discord_channel_id: "555555555555555555",
    });
  });

  it("lets a workspace admin repoint the channel", async () => {
    granted.add("workspace.update");
    const scope = await mount();

    expect(channelField(scope).disabled).toBe(false);
    await click(byName(scope, "Clear"));
    await click(byName(scope, "Save"));

    expect(upsert).toHaveBeenCalledWith(WORKSPACE_ID, {
      rank_delta_threshold: 500,
      rank_delta_hide_from_pool: true,
      mix_discord_channel_id: null,
    });
  });
});
