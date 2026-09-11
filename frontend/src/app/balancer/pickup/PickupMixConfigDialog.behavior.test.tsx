// @vitest-environment happy-dom
//
// The dialog holds three independent knobs and writes them in one go, so what
// is pinned here is the third one — the Discord channel — reporting the right
// value to the page:
//
//  1. an untouched mix with no channel saves `null`, not an empty string the
//     server would have to interpret;
//  2. a channel id is reported as a string, because a Discord snowflake does
//     not survive a round trip through a JS number;
//  3. Clear takes it back to `null`, which is how an admin unsets the override;
//  4. a host who is not a workspace admin cannot touch it at all and the save
//     reports `undefined` — the channel is the workspace's, not theirs.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomGame } from "@/services/custom-game.service";

import { PickupMixConfigDialog, type PickupMixConfigInput } from "./PickupMixConfigDialog";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

// The dialog shell labels its own close button through the message catalogue.
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

// The real picker loads the workspace's guild channels over the network and
// falls back to a manual id field; what this dialog owes it is the value and
// the change handler, so it stands in as the plain field underneath.
vi.mock("@/components/discord/DiscordChannelSelect", () => ({
  DiscordChannelSelect: ({
    value,
    onChange,
    disabled,
    ariaLabel,
    placeholder,
  }: {
    value: string;
    onChange: (channelId: string) => void;
    disabled?: boolean;
    ariaLabel?: string;
    placeholder?: string;
  }) => (
    <input
      aria-label={ariaLabel}
      placeholder={placeholder}
      disabled={disabled}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
}));
// The roster shape has its own test; here it is only the knob that must not
// interfere with the other two.
vi.mock("@/components/roster-shape/RosterShapeEditor", () => ({
  RosterShapeEditor: () => null,
}));

const WORKSPACE_ID = 7;

const SETTINGS = {
  points_per_win: null,
  team_names: {},
  role_mask: null,
  balancer_config: null,
  discord_channel_id: null,
  workspace_discord_channel_id: null,
};

function game(overrides: Partial<CustomGame> = {}): CustomGame {
  return {
    id: 3,
    workspace_id: WORKSPACE_ID,
    host_user_id: 9,
    co_hosts: [],
    host_display_name: null,
    name: "Thursday scrim",
    status: "balanced",
    settings: SETTINGS,
    balance_result: null,
    created_at: null,
    next_map_id: null,
    roster_shape: null,
    players: [],
    matches_count: 0,
    last_match_at: null,
    ...overrides,
  };
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

const onSave = vi.fn();

async function mount(current: CustomGame | undefined = game(), canSetChannel = true) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <PickupMixConfigDialog
        open
        onOpenChange={vi.fn()}
        game={current}
        workspaceId={WORKSPACE_ID}
        canWrite
        canSetChannel={canSetChannel}
        saving={false}
        onSave={onSave}
      />,
    );
  });
  await act(async () => {
    await tick();
  });
  // The dialog renders in a portal, so the assertions read the document.
  return document.body;
}

function click(node: Element | null | undefined) {
  if (!node) throw new Error("Expected a clickable node");
  return act(async () => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

function byName(scope: ParentNode, name: string) {
  return [...scope.querySelectorAll("button")].find((node) => node.textContent?.trim() === name) ?? null;
}

function channelField(scope: ParentNode) {
  const field = scope.querySelector<HTMLInputElement>('input[aria-label="Discord channel"]');
  if (!field) throw new Error("Expected the Discord channel field");
  return field;
}

// React overrides the input's own `value` setter to track changes; assigning
// through it makes React think nothing changed, so write via the prototype
// setter instead (mirrors PickupTeamsPanel.behavior.test.tsx).
const nativeValueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;

async function typeInto(field: HTMLInputElement, value: string) {
  await act(async () => {
    nativeValueSetter?.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function savedInput(): PickupMixConfigInput {
  const call = onSave.mock.calls.at(-1);
  if (!call) throw new Error("Save was never reported");
  return call[0] as PickupMixConfigInput;
}

beforeEach(() => {
  document.body.innerHTML = "";
  onSave.mockReset();
});

describe("PickupMixConfigDialog", () => {
  it("reports no channel as null rather than an empty id", async () => {
    const scope = await mount();

    await click(byName(scope, "Save"));

    expect(savedInput().discordChannelId).toBeNull();
  });

  it("reports a typed channel id as a string", async () => {
    const scope = await mount();

    await typeInto(channelField(scope), "1234567890123456789");
    await click(byName(scope, "Save"));

    expect(savedInput().discordChannelId).toBe("1234567890123456789");
  });

  it("clears a configured channel back to null", async () => {
    const scope = await mount(game({ settings: { ...SETTINGS, discord_channel_id: "123" } }));

    expect(channelField(scope).value).toBe("123");
    await click(byName(scope, "Clear"));
    expect(channelField(scope).value).toBe("");

    await click(byName(scope, "Save"));
    expect(savedInput().discordChannelId).toBeNull();
  });

  it("leaves the channel alone for a host who is not a workspace admin", async () => {
    // The channel belongs to the workspace's Discord: a host reads it but
    // cannot repoint it, and the save must carry no channel write at all --
    // `custom.set_discord_channel` would 403 the whole dialog.
    const scope = await mount(game({ settings: { ...SETTINGS, discord_channel_id: "123" } }), false);

    expect(channelField(scope).disabled).toBe(true);
    expect(byName(scope, "Clear")).toBeNull();

    await click(byName(scope, "Save"));
    expect(savedInput().discordChannelId).toBeUndefined();
  });
});
