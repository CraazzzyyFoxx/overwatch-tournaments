// @vitest-environment happy-dom
//
// The panel is the host's whole voice surface, and every rule it enforces is a
// Discord fact the server would otherwise refuse on:
//
//  1. no voice category in the workspace -> nothing to pick, so the panel says
//     what to fix instead of showing empty selects;
//  2. a pick is the mix's WHOLE voice state (`voicePatch`), because the
//     endpoint replaces it rather than patching one field;
//  3. a voice another open mix already took is labelled with that mix, but
//     still selectable -- two mixes sharing a voice is legal, just usually a
//     mistake;
//  4. a saved voice that is no longer in the category still renders, or the
//     host would silently lose the pick by opening the panel;
//  5. a permission the bot lacks disables the voice, the move and the return:
//     Discord would refuse the move, so the panel refuses first and names what
//     is missing;
//  6. moving is per lobby, and across all of them only when there is more than
//     one;
//  7. the report says how many moved and, per status, exactly who did not.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { createContext, useContext, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CustomGame,
  CustomGameLobby,
  MixVoiceOptions,
  MixVoiceReport,
} from "@/services/custom-game.service";

import { voicePatch } from "./pickup-voice";
import { PickupVoicePanel } from "./PickupVoicePanel";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Values matter here (which team, which lobby, which mix is holding a voice),
// so the stand-in renders them next to the key instead of the key alone.
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string, values?: Record<string, unknown>) =>
    values == null
      ? key
      : `${key}(${Object.entries(values)
          .map(([name, value]) => `${name}=${value}`)
          .join(",")})`,
}));

// Radix renders its items in a portal behind a pointer-driven trigger. The
// stand-in keeps the same contract (root owns the value, items report a pick)
// as plain DOM, so a pick is a click.
const SelectCtx = createContext<{ onValueChange?: (value: string) => void; disabled?: boolean }>({});
vi.mock("@/components/ui/select", () => ({
  Select: ({
    children,
    onValueChange,
    disabled,
  }: {
    children: ReactNode;
    value?: string;
    onValueChange?: (value: string) => void;
    disabled?: boolean;
  }) => (
    <SelectCtx.Provider value={{ onValueChange, disabled }}>
      <div data-select="">{children}</div>
    </SelectCtx.Provider>
  ),
  SelectTrigger: ({ children, ...rest }: { children: ReactNode }) => (
    <button type="button" disabled={useContext(SelectCtx).disabled} {...rest}>
      {children}
    </button>
  ),
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({
    children,
    value,
    disabled,
  }: {
    children: ReactNode;
    value: string;
    disabled?: boolean;
  }) => {
    const ctx = useContext(SelectCtx);
    return (
      <button type="button" role="option" aria-selected="false" disabled={disabled} onClick={() => ctx.onValueChange?.(value)}>
        {children}
      </button>
    );
  },
}));

const onSave = vi.fn();
const onMove = vi.fn();
const onReturn = vi.fn();

function lobby(overrides: Partial<CustomGameLobby> = {}): CustomGameLobby {
  return {
    lobby_index: 0,
    selected_variant_index: 0,
    next_map_id: null,
    balanced_at: null,
    team1_voice_channel_id: null,
    team2_voice_channel_id: null,
    ...overrides,
  };
}

function game(overrides: Partial<CustomGame> = {}): CustomGame {
  return {
    id: 3,
    workspace_id: 7,
    host_user_id: 9,
    co_hosts: [],
    host_display_name: null,
    name: "Thursday scrim",
    status: "balanced",
    settings: { points_per_win: 0, team_names: {}, workspace_discord_channel_id: null },
    created_at: null,
    lobby_count: 1,
    lobbies: [lobby()],
    roster_shape: null,
    players: [],
    matches_count: 0,
    last_match_at: null,
    self_signup: "closed",
    self_role_edit: false,
    general_voice_channel_id: null,
    ...overrides,
  };
}

function options(overrides: Partial<MixVoiceOptions> = {}): MixVoiceOptions {
  return {
    category_id: "100",
    category_missing_permissions: null,
    general: [{ id: "1", name: "Waiting room", missing_permissions: null }],
    team: [
      { id: "2", name: "Alpha", missing_permissions: null },
      { id: "3", name: "Bravo", missing_permissions: null },
    ],
    error: null,
    ...overrides,
  };
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

async function mount(
  props: {
    game?: CustomGame;
    games?: CustomGame[];
    options?: MixVoiceOptions;
    optionsLoading?: boolean;
    moving?: boolean;
    returning?: boolean;
    report?: MixVoiceReport;
  } = {},
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <PickupVoicePanel
        game={props.game ?? game()}
        games={props.games ?? []}
        options={props.options ?? options()}
        optionsLoading={props.optionsLoading ?? false}
        saving={false}
        moving={props.moving ?? false}
        returning={props.returning ?? false}
        report={props.report}
        onSave={onSave}
        onMove={onMove}
        onReturn={onReturn}
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
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

/** By accessible name: the visible label for text buttons, `aria-label` for the rest. */
function byName(scope: ParentNode, name: string) {
  return (
    [...scope.querySelectorAll("button")].find(
      (node) => node.textContent?.trim() === name || node.getAttribute("aria-label") === name,
    ) ?? null
  );
}

/** The select whose trigger carries this accessible name. */
function selectByLabel(scope: ParentNode, label: string) {
  const trigger = [...scope.querySelectorAll("button")].find(
    (node) => node.getAttribute("aria-label") === label,
  );
  const root = trigger?.closest("[data-select]");
  if (!root) throw new Error(`No select labelled ${label}`);
  return root;
}

function optionByText(scope: ParentNode, text: string) {
  return (
    [...scope.querySelectorAll<HTMLButtonElement>("[role='option']")].find((node) =>
      node.textContent?.includes(text),
    ) ?? null
  );
}

beforeEach(() => {
  document.body.innerHTML = "";
  vi.clearAllMocks();
});

describe("PickupVoicePanel", () => {
  it("tells the host where to configure voices instead of showing empty pickers", async () => {
    const container = await mount({ options: options({ category_id: null, general: [], team: [] }) });

    expect(container.textContent).toContain("notConfigured");
    expect(container.querySelectorAll("[data-select]").length).toBe(0);
    expect(byName(container, "move")).toBeNull();
  });

  it("says Discord could not be reached while the category is still configured", async () => {
    const container = await mount({ options: options({ error: "discord timeout" }) });

    expect(container.textContent).toContain("unreachable");
  });

  it("saves the mix's whole voice state when one team voice is picked", async () => {
    const current = game({
      lobby_count: 2,
      general_voice_channel_id: "1",
      lobbies: [lobby({ team2_voice_channel_id: "3" }), lobby({ lobby_index: 1 })],
    });
    const container = await mount({ game: current });

    await click(optionByText(selectByLabel(container, "team(n=1,letter=A)"), "Alpha"));

    expect(onSave).toHaveBeenCalledWith(
      voicePatch(current, { lobbyIndex: 0, team: 1, channelId: "2" }),
    );
  });

  it("clears a pick through the none item", async () => {
    const current = game({ lobbies: [lobby({ team1_voice_channel_id: "2" })] });
    const container = await mount({ game: current });

    await click(optionByText(selectByLabel(container, "team(n=1,letter=A)"), "none"));

    expect(onSave).toHaveBeenCalledWith(
      voicePatch(current, { lobbyIndex: 0, team: 1, channelId: null }),
    );
  });

  it("marks a voice another open mix is using, and still lets this mix take it", async () => {
    const container = await mount({
      games: [
        game({ id: 3 }),
        game({
          id: 4,
          name: "Friday cup",
          lobbies: [lobby({ lobby_index: 1, team1_voice_channel_id: "3" })],
        }),
      ],
    });

    const bravo = optionByText(selectByLabel(container, "team(n=2,letter=A)"), "Bravo");
    expect(bravo?.textContent).toContain("busy(mix=Friday cup,letter=B)");
    expect(bravo?.disabled).toBe(false);
  });

  it("keeps a saved voice that left the category visible rather than losing it silently", async () => {
    const container = await mount({
      game: game({ lobbies: [lobby({ team1_voice_channel_id: "77" })] }),
    });

    expect(selectByLabel(container, "team(n=1,letter=A)").textContent).toContain("outsideCategory");
  });

  it("refuses the move Discord would refuse, and names the missing permission", async () => {
    const container = await mount({
      game: game({ general_voice_channel_id: "1", lobbies: [lobby({ team1_voice_channel_id: "2" })] }),
      options: options({
        team: [
          { id: "2", name: "Alpha", missing_permissions: ["move_members"] },
          { id: "3", name: "Bravo", missing_permissions: null },
        ],
      }),
    });

    expect(container.textContent).toContain("missing(permissions=permission.move_members)");
    expect(optionByText(selectByLabel(container, "team(n=1,letter=A)"), "Alpha")?.disabled).toBe(true);
    expect(byName(container, "move")?.disabled).toBe(true);
    expect(byName(container, "return")?.disabled).toBe(true);
  });

  it("moves one lobby, and every lobby only when the mix runs more than one", async () => {
    const single = await mount({});

    await click(byName(single, "move"));
    expect(onMove).toHaveBeenCalledWith(0);
    expect(byName(single, "moveAll")).toBeNull();

    const many = await mount({
      game: game({ lobby_count: 2, lobbies: [lobby(), lobby({ lobby_index: 1 })] }),
    });

    await click(byName(many, "moveAll"));
    expect(onMove).toHaveBeenCalledWith(null);
    await click(byName(many, "returnAll"));
    expect(onReturn).toHaveBeenCalledWith(null);
  });

  it("returns one lobby on its own row", async () => {
    const container = await mount({});

    await click(byName(container, "return"));

    expect(onReturn).toHaveBeenCalledWith(0);
  });

  it("reports how many moved and who did not, grouped by what stopped them", async () => {
    const container = await mount({
      report: {
        moved: 2,
        results: [
          { workspace_member_id: 1, name: "karin", status: "moved", channel_id: "2" },
          { workspace_member_id: 2, name: "Tolgrn", status: "moved", channel_id: "2" },
          { workspace_member_id: 3, name: "Egor", status: "not_in_voice", channel_id: null },
          { workspace_member_id: 4, name: "DemonDimon", status: "not_in_voice", channel_id: null },
          { workspace_member_id: 5, name: "Hleb", status: "no_discord_link", channel_id: null },
        ],
      },
    });

    expect(container.textContent).toContain("report.moved(count=2)");
    expect(container.textContent).toContain("status.not_in_voice");
    expect(container.textContent).toContain("Egor, DemonDimon");
    expect(container.textContent).toContain("status.no_discord_link");
    expect(container.textContent).toContain("Hleb");
    // Everyone who made it is already counted; naming them again is noise.
    expect(container.textContent).not.toContain("karin");
  });
});
