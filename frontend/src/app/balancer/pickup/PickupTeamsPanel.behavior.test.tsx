// @vitest-environment happy-dom
//
// The teams column replaced a `<pre>{JSON.stringify(balance_result)}</pre>`, so
// what is pinned here is that it actually reads the payload, and that the two
// writes it owns cannot fire by accident:
//
//  1. seats render per team with the rating the solver assigned, not raw JSON;
//  2. the solver returns many equally-scored options and the pager walks them
//     without re-running the balance — the index is owned by the page, so the
//     panel reports the move instead of keeping its own copy;
//  3. the index is clamped, so a shorter result cannot point past the end;
//  4. Balance is refused while nobody is checked in the lineup, which is the
//     `empty_lineup` 422 the server would raise;
//  5. recording a result is a deliberate click, repeatable, and carries the
//     page's variant index; closing the mix is a separate, explicit action;
//  6. a read-only viewer gets no writes but still sees teams;
//  7. the verdict pills sit inside the captured block with the team card, so
//     "Copy image" exports them together, while "Copy image"/"Copy battletags"
//     stay outside it -- exporting its own toolbar would be a screenshot of a
//     screenshot button;
//  8. every seat is a drag source and drop target, gated on both write access
//     and the page actually offering a swap handler -- a read-only viewer or
//     a page with nothing to call must not present drag affordance for a
//     write that cannot happen;
//  9. only the newest recorded match offers an undo, and only to a writer the
//     page actually handed a handler -- an older one would have to unwind
//     every match stacked on top of it;
// 10. Post to Discord appears only for a writer whose mix has a channel
//     configured, and posts the option the pager is on, not always the first,
//     together with the rasterised matchup card the bot attaches.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomGame, CustomGameMatch } from "@/services/custom-game.service";
import type { MapRead } from "@/types/map.types";

import { PickupTeamsPanel } from "./PickupTeamsPanel";

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
vi.mock("@/components/PlayerRoleIcon", () => ({ default: () => null }));
vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));
// Drag itself is not what this pins, and dnd-kit resolves its own React copy
// under pnpm (see PickupPlayerSheet.behavior.test.tsx), so it renders inertly
// here: children mount as plain DOM, no real drag/drop wiring.
const dndSpies = vi.hoisted(() => ({
  useDraggable: vi.fn(() => ({
    attributes: {},
    listeners: {},
    setNodeRef: () => {},
    transform: null,
    isDragging: false,
  })),
  useDroppable: vi.fn(() => ({ setNodeRef: () => {}, isOver: false })),
}));
vi.mock("@dnd-kit/core", () => ({
  DndContext: ({ children }: { children: React.ReactNode }) => children,
  DragOverlay: () => null,
  PointerSensor: class {},
  useSensor: () => null,
  useSensors: () => [],
  useDraggable: dndSpies.useDraggable,
  useDroppable: dndSpies.useDroppable,
}));
// The rasteriser is the export pipeline's, not this panel's: what the panel
// owes is handing the PNG it produced to the post handler, so the capture is
// stubbed to a known blob.
const captureSpies = vi.hoisted(() => ({ rasterize: vi.fn(), capture: vi.fn(), capturing: false }));
vi.mock("@/hooks/useNodeCapture", () => ({
  useNodeCapture: () => ({
    ref: { current: null },
    capturing: captureSpies.capturing,
    rasterize: captureSpies.rasterize,
    capture: captureSpies.capture,
  }),
}));

/** Stands in for the rasterised matchup card. */
const LINEUP_PNG = new Blob(["png"], { type: "image/png" });

const onBalance = vi.fn();
const onVariantIndexChange = vi.fn();
const onRecordOutcome = vi.fn();
const onNextMapChange = vi.fn();
const onCloseMix = vi.fn();
const onCopyBattleTags = vi.fn();
const onRenameTeam = vi.fn();
const onSwapSeats = vi.fn();
const onUndoMatch = vi.fn();
const onPostToDiscord = vi.fn();

function variant(offset: number) {
  return {
    teams: [
      {
        id: 1,
        average_mmr: 3000 + offset,
        roster: {
          Tank: [{ uuid: "7", name: "karin", assigned_rating: 2900 + offset, role_preferences: ["Tank"] }],
          Damage: [
            { uuid: "8", name: "DemonDimon", assigned_rating: 4100, role_preferences: ["Tank", "Damage"] },
          ],
        },
      },
      {
        id: 2,
        average_mmr: 2950,
        roster: { Support: [{ uuid: "9", name: "Tolgrn", assigned_rating: 3450 }] },
      },
    ],
    statistics: { composite_score: 0.87, mmr_std_dev: 12.34, off_role_count: 1 },
    benched_players: [{ uuid: "10", name: "Egor" }],
  };
}

const SETTINGS = {
  points_per_win: null,
  team_names: {},
  role_mask: null,
  balancer_config: null,
  discord_channel_id: null,
};

const CONTROL = { id: 1, name: "Control", slug: "control", image_path: "", description: "", aliases: [] };
const HYBRID = { id: 2, name: "Hybrid", slug: "hybrid", image_path: "", description: "", aliases: [] };

function mapRead(id: number, name: string, gamemode: typeof CONTROL): MapRead {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name,
    image_path: "",
    gamemode_id: gamemode.id,
    in_competitive: true,
    aliases: [],
    gamemode,
  };
}

const CATALOGUE = [mapRead(5, "King's Row", HYBRID), mapRead(6, "Ilios", CONTROL), mapRead(7, "Busan", CONTROL)];

function game(overrides: Partial<CustomGame> = {}): CustomGame {
  return {
    id: 3,
    workspace_id: 7,
    host_user_id: 9,
    co_hosts: [],
    host_display_name: null,
    name: "Thursday scrim",
    status: "balanced",
    settings: SETTINGS,
    balance_result: { variants: [variant(0), variant(100), variant(200)] },
    created_at: null,
    next_map_id: null,
    roster_shape: null,
    players: [],
    matches_count: 0,
    last_match_at: null,
    ...overrides,
  };
}

function match(overrides: Partial<CustomGameMatch> = {}): CustomGameMatch {
  return {
    id: 2,
    home_team_name: "Wolves",
    away_team_name: "Bears",
    home_score: 1,
    away_score: 0,
    winner: 1,
    map_id: 5,
    map_name: "King's Row",
    map_image_path: null,
    recorded_by: 9,
    recorded_at: new Date().toISOString(),
    points_per_win_applied: null,
    ...overrides,
  };
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

async function mount(
  current: CustomGame | undefined,
  props: {
    canWrite?: boolean;
    activeCount?: number;
    variantIndex?: number;
    hasMix?: boolean;
    omitSwapSeats?: boolean;
    maps?: MapRead[];
    matches?: CustomGameMatch[];
    undoingMatchId?: number | null;
    omitUndoMatch?: boolean;
    omitPostToDiscord?: boolean;
  } = {},
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <PickupTeamsPanel
        canWrite={props.canWrite ?? true}
        gamesLoading={false}
        gamesError={false}
        onRetryGames={vi.fn()}
        game={current}
        gameLoading={false}
        hasMix={props.hasMix ?? current != null}
        balancing={false}
        activeCount={props.activeCount ?? 10}
        onBalance={onBalance}
        variantIndex={props.variantIndex ?? 0}
        onVariantIndexChange={onVariantIndexChange}
        recordingOutcome={false}
        onRecordOutcome={onRecordOutcome}
        matches={props.matches ?? []}
        undoingMatchId={props.undoingMatchId ?? null}
        onUndoMatch={props.omitUndoMatch ? undefined : onUndoMatch}
        maps={props.maps ?? []}
        settingNextMap={false}
        onNextMapChange={onNextMapChange}
        closingMix={false}
        onCloseMix={onCloseMix}
        onRenameTeam={onRenameTeam}
        onSwapSeats={props.omitSwapSeats ? undefined : onSwapSeats}
        onCopyBattleTags={onCopyBattleTags}
        postingToDiscord={false}
        onPostToDiscord={props.omitPostToDiscord ? undefined : onPostToDiscord}
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

/** By accessible name: the visible label for text buttons, `aria-label` for the icon-only tools. */
function byName(scope: ParentNode, name: string) {
  return (
    [...scope.querySelectorAll("button")].find(
      (node) => node.textContent?.trim() === name || node.getAttribute("aria-label") === name,
    ) ?? null
  );
}

function inputByLabel(scope: ParentNode, label: string) {
  return scope.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`);
}

// React overrides the input's own `value` setter to track changes; assigning
// through it makes React think nothing changed, so write via the prototype
// setter instead (mirrors InlineEditText.behavior.test.tsx).
const nativeValueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;

async function typeInto(field: HTMLInputElement, value: string) {
  await act(async () => {
    nativeValueSetter?.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function pagerLabel(scope: ParentNode) {
  return scope.querySelector('[role="status"]')?.textContent?.trim();
}

beforeEach(() => {
  document.body.innerHTML = "";
  onBalance.mockReset();
  onVariantIndexChange.mockReset();
  onRecordOutcome.mockReset();
  onNextMapChange.mockReset();
  onCloseMix.mockReset();
  onCopyBattleTags.mockReset();
  onRenameTeam.mockReset();
  onSwapSeats.mockReset();
  onUndoMatch.mockReset();
  onPostToDiscord.mockReset();
  captureSpies.rasterize.mockReset();
  captureSpies.rasterize.mockResolvedValue(LINEUP_PNG);
  captureSpies.capture.mockReset();
  captureSpies.capturing = false;
  dndSpies.useDraggable.mockClear();
  dndSpies.useDroppable.mockClear();
});

describe("PickupTeamsPanel", () => {
  it("renders seats and ratings from the payload instead of raw JSON", async () => {
    const scope = await mount(game());

    expect(scope.textContent).toContain("karin");
    expect(scope.textContent).toContain("2900");
    expect(scope.textContent).toContain("Tolgrn");
    expect(scope.textContent).toContain("3450");
    expect(scope.textContent).not.toContain("balance_result");
    expect(scope.textContent).not.toContain('"uuid"');
  });

  it("shows the option's own verdict but not who it left out -- the lineup already marks them benched", async () => {
    const scope = await mount(game());

    expect(scope.textContent).toContain("0.87");
    expect(scope.textContent).toContain("12.3");
    expect(scope.textContent).not.toContain("Egor");
  });

  it("captures the verdict pills with the teams block, not the action buttons beside it", async () => {
    const scope = await mount(game());

    const captured = scope.querySelector('[data-testid="teams-capture"]');
    expect(captured).not.toBeNull();
    expect(captured?.textContent).toContain("0.87");
    expect(captured?.textContent).toContain("karin");
    expect(captured?.textContent).not.toContain("Copy image");
    expect(captured?.textContent).not.toContain("Copy battletags");
    expect(captured?.textContent).not.toContain("Close mix");
  });

  it("reports a pager move to the page instead of keeping its own index", async () => {
    const scope = await mount(game());

    expect(pagerLabel(scope)).toBe("1 / 3");
    expect(byName(scope, "Previous balance option")?.hasAttribute("disabled")).toBe(true);

    await click(byName(scope, "Next balance option"));

    expect(onVariantIndexChange).toHaveBeenCalledWith(1);
    expect(onBalance).not.toHaveBeenCalled();
  });

  it("renders the option the page selected", async () => {
    const scope = await mount(game(), { variantIndex: 2 });

    expect(pagerLabel(scope)).toBe("3 / 3");
    expect(scope.textContent).toContain("3100");
  });

  it("clamps an index left pointing past a shorter result", async () => {
    const scope = await mount(game({ balance_result: { variants: [variant(0)] } }), { variantIndex: 7 });

    // One option left: the pager is gone and the first option is on screen.
    expect(pagerLabel(scope)).toBeUndefined();
    expect(scope.textContent).toContain("karin");
  });

  it("offers the empty state for a mix that has not been balanced", async () => {
    const scope = await mount(game({ status: "draft", balance_result: null }));

    expect(scope.textContent).toContain("No teams yet");
    expect(byName(scope, "Balance teams")).not.toBeNull();
  });

  it("refuses to balance an empty lineup and says why", async () => {
    const scope = await mount(game({ status: "draft", balance_result: null }), { activeCount: 0 });

    expect(byName(scope, "Balance teams")?.hasAttribute("disabled")).toBe(true);
    expect(scope.textContent).toContain("Check at least one player in the lobby");
  });

  it("balances on request when the lineup is not empty", async () => {
    const scope = await mount(game({ status: "draft", balance_result: null }));

    await click(byName(scope, "Balance teams"));

    expect(onBalance).toHaveBeenCalledTimes(1);
  });

  it("records a result only on a deliberate click, without closing the mix", async () => {
    const scope = await mount(game());

    expect(onRecordOutcome).not.toHaveBeenCalled();

    await click(byName(scope, "Draw"));
    expect(onRecordOutcome).toHaveBeenCalledWith({ outcome: { winner: null }, variantIndex: 0 });

    await click(byName(scope, "Team 2 win"));
    expect(onRecordOutcome).toHaveBeenLastCalledWith({ outcome: { winner: 2 }, variantIndex: 0 });
  });

  it("reports the page's variant index alongside a recorded result", async () => {
    const scope = await mount(game(), { variantIndex: 1 });

    await click(byName(scope, "Team 1 win"));
    expect(onRecordOutcome).toHaveBeenCalledWith({ outcome: { winner: 1 }, variantIndex: 1 });
  });

  it("shows the mix's next map, with its mode, inside the captured block", async () => {
    const scope = await mount(game({ next_map_id: 5 }), { maps: CATALOGUE });

    const captured = scope.querySelector('[data-testid="teams-capture"]');
    expect(captured?.textContent).toContain("King's Row");
    expect(captured?.textContent).toContain("Hybrid");
    expect(captured?.textContent).not.toContain("Not rolled yet");
  });

  it("rolls inside the chosen mode and hands the verdict to the page", async () => {
    const scope = await mount(game(), { maps: CATALOGUE });

    expect(scope.textContent).toContain("Not rolled yet");
    expect(byName(scope, "Hybrid")?.getAttribute("aria-pressed")).toBe("false");

    await click(byName(scope, "Hybrid"));
    expect(byName(scope, "Hybrid")?.getAttribute("aria-pressed")).toBe("true");

    await click(byName(scope, "Roll"));
    // Hybrid has exactly one competitive map, so the roll is deterministic.
    expect(onNextMapChange).toHaveBeenCalledWith(5);
  });

  it("hides the roll controls from a read-only viewer, and the whole strip until something is rolled", async () => {
    const nothingRolled = await mount(game(), { maps: CATALOGUE, canWrite: false });
    expect(nothingRolled.textContent).not.toContain("Next map");

    document.body.innerHTML = "";
    const rolled = await mount(game({ next_map_id: 6 }), { maps: CATALOGUE, canWrite: false });
    expect(rolled.textContent).toContain("Ilios");
    expect(byName(rolled, "Roll")).toBeNull();
    expect(byName(rolled, "Hybrid")).toBeNull();
  });

  it("lets the host pick the next map by hand through the combobox", async () => {
    const scope = await mount(game(), { maps: CATALOGUE });

    await click(byName(scope, "No map"));
    const option = [...document.body.querySelectorAll<HTMLElement>("[cmdk-item]")].find(
      (node) => node.textContent?.trim() === "Ilios",
    );
    await click(option);

    expect(onNextMapChange).toHaveBeenCalledWith(6);
  });

  it("lets the host close the mix independently of recording a result, after confirming", async () => {
    const scope = await mount(game());

    await click(byName(scope, "Close mix"));
    expect(onCloseMix).not.toHaveBeenCalled();

    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "Close this mix?",
    );

    await click(byName(document, "Yes, close mix"));
    expect(onCloseMix).toHaveBeenCalledTimes(1);
  });

  it("offers no result controls to a viewer or on a closed mix -- the history is the record", async () => {
    const scope = await mount(game({ status: "completed" }), { canWrite: false });

    expect(byName(scope, "Team 1 win")).toBeNull();
    expect(byName(scope, "Draw")).toBeNull();
    expect(byName(scope, "Close mix")).toBeNull();
  });

  it("shows the configured points-per-win on the win buttons, never on Draw", async () => {
    const scope = await mount(game({ settings: { ...SETTINGS, points_per_win: 25 } }));

    expect(byName(scope, "Team 1 win +25")).not.toBeNull();
    expect(byName(scope, "Team 2 win +25")).not.toBeNull();
    expect(byName(scope, "Draw")).not.toBeNull();
  });

  it("omits the points hint once no rank-adjustment is configured", async () => {
    const scope = await mount(game());

    expect(byName(scope, "Team 1 win")).not.toBeNull();
  });

  it("renders the recorded match history the page hands it", async () => {
    const scope = await mount(game(), { matches: [match()] });

    expect(scope.textContent).toContain("Match history");
    expect(scope.textContent).toContain("Wolves");
    expect(scope.textContent).toContain("Bears");
    expect(scope.textContent).toContain("King's Row");
  });

  it("offers the undo only on the newest recorded match", async () => {
    const scope = await mount(game(), {
      matches: [match({ id: 9 }), match({ id: 8 })],
    });

    expect(scope.querySelectorAll('button[aria-label="Undo this match"]')).toHaveLength(1);
  });

  it("withholds the undo from a read-only viewer and from a page offering no handler", async () => {
    const readOnly = await mount(game(), { matches: [match()], canWrite: false });
    expect(readOnly.querySelector('button[aria-label="Undo this match"]')).toBeNull();

    const noHandler = await mount(game(), { matches: [match()], omitUndoMatch: true });
    expect(noHandler.querySelector('button[aria-label="Undo this match"]')).toBeNull();
  });

  it("names the rank points it will give back, and only undoes after confirming", async () => {
    const scope = await mount(game(), {
      matches: [match({ id: 9, points_per_win_applied: 25 })],
    });

    await click(scope.querySelector('button[aria-label="Undo this match"]'));
    expect(onUndoMatch).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "moves every player's rank back by 25 points",
    );

    await click(byName(document, "Undo match"));
    expect(onUndoMatch).toHaveBeenCalledWith(9);
  });

  it("says so plainly when the match moved no rank points", async () => {
    const scope = await mount(game(), { matches: [match()] });

    await click(scope.querySelector('button[aria-label="Undo this match"]'));

    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "No rank points were applied.",
    );
  });

  it("hides the match history section until something has been recorded", async () => {
    const scope = await mount(game());

    expect(scope.textContent).not.toContain("Match history");
  });

  it("hands the tag copy to the page", async () => {
    const scope = await mount(game());

    await click(byName(scope, "Copy battletags"));
    expect(onCopyBattleTags).toHaveBeenCalledTimes(1);
  });

  it("hides write controls for a read-only viewer but still shows the teams", async () => {
    const scope = await mount(game(), { canWrite: false });

    expect(byName(scope, "Balance teams")).toBeNull();
    expect(scope.textContent).toContain("karin");
    expect(pagerLabel(scope)).toBe("1 / 3");
  });

  it("separates no mix at all from a mix with no teams", async () => {
    const scope = await mount(undefined, { hasMix: false });

    expect(scope.textContent).toContain("No mixes yet");
    expect(scope.textContent).not.toContain("No teams yet");
  });

  it("lets the host rename a team through the pencil affordance", async () => {
    const scope = await mount(game());

    const pencils = [...scope.querySelectorAll('button[aria-label="Edit team name"]')];
    expect(pencils).toHaveLength(2);

    await click(pencils[0]);
    const field = inputByLabel(scope, "team name");
    expect(field?.value).toBe("Team 1");
    await typeInto(field as HTMLInputElement, "Wolves");
    await click(scope.querySelector('button[aria-label="Save team name"]'));

    expect(onRenameTeam).toHaveBeenCalledWith(0, "Wolves");
  });

  it("hides the rename pencil for a read-only viewer", async () => {
    const scope = await mount(game(), { canWrite: false });

    expect(scope.querySelectorAll('button[aria-label="Edit team name"]')).toHaveLength(0);
  });

  it("withholds the rename pencils while the card is being captured", async () => {
    captureSpies.capturing = true;
    const scope = await mount(game());

    expect(scope.querySelectorAll('button[aria-label="Edit team name"]')).toHaveLength(0);
    // The names themselves stay in the picture.
    expect(scope.querySelector('[data-testid="teams-capture"]')?.textContent).toContain("Team 1");
  });

  it("shows a host's saved team name instead of the computed default", async () => {
    const scope = await mount(game({ settings: { ...SETTINGS, team_names: { "0": "Wolves" } } }));

    expect(scope.textContent).toContain("Wolves");
    // The second team keeps its computed default; the win buttons pick up
    // the same override so the scoreline reads the same name as the column.
    expect(byName(scope, "Wolves win")).not.toBeNull();
    expect(byName(scope, "Team 2 win")).not.toBeNull();
  });

  it("wires every seat as a drag source and drop target for a host who can rebalance manually", async () => {
    await mount(game());

    // Every seat across both teams (3 in the fixture) is both draggable and
    // droppable, and none of them are disabled for a host with a swap handler.
    expect(dndSpies.useDraggable).toHaveBeenCalledTimes(3);
    expect(dndSpies.useDroppable).toHaveBeenCalledTimes(3);
    for (const call of dndSpies.useDraggable.mock.calls) {
      expect(call[0]).toMatchObject({ disabled: false });
    }
    for (const call of dndSpies.useDroppable.mock.calls) {
      expect(call[0]).toMatchObject({ disabled: false });
    }
  });

  it("disables seat dragging for a read-only viewer", async () => {
    await mount(game(), { canWrite: false });

    for (const call of dndSpies.useDraggable.mock.calls) {
      expect(call[0]).toMatchObject({ disabled: true });
    }
  });

  it("disables seat dragging when the page offers no swap handler", async () => {
    await mount(game(), { omitSwapSeats: true });

    for (const call of dndSpies.useDraggable.mock.calls) {
      expect(call[0]).toMatchObject({ disabled: true });
    }
  });

  it("offers no Post to Discord until a channel is configured", async () => {
    const scope = await mount(game());

    expect(byName(scope, "Post to Discord")).toBeNull();
  });

  it("posts the option on screen, rasterised, to the mix's configured channel", async () => {
    const withChannel = game({ settings: { ...SETTINGS, discord_channel_id: "123" } });
    const scope = await mount(withChannel);

    await click(byName(scope, "Post to Discord"));
    expect(onPostToDiscord).toHaveBeenCalledWith(0, LINEUP_PNG);

    // The pager's option is what a lobby is reading, so that is what goes out.
    document.body.innerHTML = "";
    const second = await mount(withChannel, { variantIndex: 1 });
    await click(byName(second, "Post to Discord"));
    expect(onPostToDiscord).toHaveBeenLastCalledWith(1, LINEUP_PNG);
  });

  it("posts without an image when the capture fails", async () => {
    captureSpies.rasterize.mockRejectedValue(new Error("tainted canvas"));
    const scope = await mount(game({ settings: { ...SETTINGS, discord_channel_id: "123" } }));

    await click(byName(scope, "Post to Discord"));

    // The server still has a text embed to fall back on -- losing the
    // screenshot must not lose the matchup.
    expect(onPostToDiscord).toHaveBeenCalledWith(0, null);
  });

  it("hides Post to Discord from a read-only viewer", async () => {
    const scope = await mount(game({ settings: { ...SETTINGS, discord_channel_id: "123" } }), {
      canWrite: false,
    });

    expect(byName(scope, "Post to Discord")).toBeNull();
  });
});
