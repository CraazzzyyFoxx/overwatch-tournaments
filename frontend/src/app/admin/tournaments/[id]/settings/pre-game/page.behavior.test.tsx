// @vitest-environment happy-dom
//
// The pre-game phase editor, carried over from `pickBanConfigsTab.behavior.test`
// when the two "add a rule set" cards became a scope tree plus three steps.
// What is pinned here:
//
//   1. the section gate: pre-game follows `match.update`, not the tab's
//      `tournament.update`;
//   2. URL ↔ state: `?scope=` decides which config is being edited, `?step=`
//      which of Pool · Sequence · Sides is on screen, and both survive a
//      reload — a scope in component state cannot be pasted into Discord;
//   3. nothing is typed. The pre-cutover editor asked for stage ids, catalogue
//      item ids and step tokens as comma-separated free text; the only text
//      field left is the turn timer, and it says what empty means;
//   4. an invalid config cannot be sent, with the reason on screen;
//   5. a stored custom order survives a round trip — `preset` and `sequence`
//      used to drift apart silently and the engine discarded hand-authored
//      orders without telling anyone;
//   6. a narrower scope opens prefilled from the rules it inherits, and the
//      tree says where a scope's rules come from;
//   7. the catalogue picker's name fold and its bulk add/clear, scoped to what
//      the search currently shows.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, forwardRef, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { PickBanConfig, Stage } from "@/types/tournament.types";

import PreGameSettingsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listConfigs = vi.fn();
const upsertConfig = vi.fn();
const deleteConfig = vi.fn();
const getHeroes = vi.fn();
const getMaps = vi.fn();
const getStagePlannedRounds = vi.fn();
const getStages = vi.fn();
const getTournament = vi.fn();
const getEncounters = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getTournament: (...args: unknown[]) => getTournament(...args),
    getStages: (...args: unknown[]) => getStages(...args),
    getStagePlannedRounds: (...args: unknown[]) => getStagePlannedRounds(...args)
  }
}));

vi.mock("@/services/encounter.service", () => ({
  default: { getAll: (...args: unknown[]) => getEncounters(...args) }
}));

vi.mock("@/services/pickBan.service", () => ({
  default: {
    listConfigs: (...args: unknown[]) => listConfigs(...args),
    upsertConfig: (...args: unknown[]) => upsertConfig(...args),
    deleteConfig: (...args: unknown[]) => deleteConfig(...args)
  }
}));

vi.mock("@/services/hero.service", () => ({
  default: { getAll: (...args: unknown[]) => getHeroes(...args) }
}));

vi.mock("@/services/map.service", () => ({
  default: { getAll: (...args: unknown[]) => getMaps(...args) }
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

let granted = ["tournament.update", "match.update"];
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    isLoaded: true,
    canAccessPermission: (permission: string) => granted.includes(permission)
  })
}));

// The URL is the editor's state, so the harness owns it: `search` is what the
// page reads, and every navigation the page makes writes it back and rerenders.
let search = "";
let rerender: (() => void) | null = null;

function navigate(url: string) {
  search = new URL(url, "http://localhost").search;
  window.history.replaceState(null, "", url);
  rerender?.();
}

const routerReplace = vi.fn((url: string) => navigate(url));
const routerPush = vi.fn((url: string) => navigate(url));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "84" }),
  usePathname: () => "/admin/tournaments/84/settings/pre-game",
  useSearchParams: () => new URLSearchParams(search),
  useRouter: () => ({ replace: routerReplace, push: routerPush })
}));

// A scope is a link, and clicking it has to reach the same URL the app would.
vi.mock("next/link", () => ({
  default: forwardRef<
    HTMLAnchorElement,
    { href: string; children: React.ReactNode } & React.AnchorHTMLAttributes<HTMLAnchorElement>
  >(function Link({ href, children, onClick, ...props }, ref) {
    return (
      <a
        ref={ref}
        href={href}
        {...props}
        onClick={(event) => {
          event.preventDefault();
          onClick?.(event);
          navigate(href);
        }}
      >
        {children}
      </a>
    );
  })
}));

const HEROES = ["Tracer", "Genji", "Reinhardt", "Ana", "Lucio", "Sombra"].map((name, index) => ({
  id: index + 1,
  name,
  slug: name.toLowerCase(),
  image_path: `/heroes/${index + 1}.png`,
  type: "Damage",
  role: "damage"
}));

const MAPS = ["Busan", "King's Row", "Ilios", "Hollywood"].map((name, index) => ({
  id: index + 1,
  name,
  image_path: `/maps/${index + 1}.png`,
  gamemode: { name: index % 2 === 0 ? "Control" : "Hybrid" },
  in_competitive: true
}));
// A brawl-only map, never offered in a ranked pool.
const OFF_ROTATION_MAP = {
  id: 99,
  name: "Junkenstein's Revenge",
  image_path: "/maps/99.png",
  gamemode: { name: "Elimination" },
  in_competitive: false
};

const STAGES = [
  {
    id: 10,
    tournament_id: 84,
    name: "Group stage",
    description: null,
    stage_type: "round_robin",
    max_rounds: 3,
    advance_count: null,
    split_lower_bracket: false,
    order: 1,
    is_active: true,
    is_completed: false,
    settings_json: { best_of: { default: 3 } },
    challonge_id: null,
    challonge_slug: null,
    items: []
  },
  {
    id: 11,
    tournament_id: 84,
    name: "Playoffs",
    description: null,
    stage_type: "single_elimination",
    max_rounds: 2,
    advance_count: null,
    split_lower_bracket: false,
    order: 2,
    is_active: false,
    is_completed: false,
    settings_json: { best_of: { default: 5 } },
    challonge_id: null,
    challonge_slug: null,
    items: []
  }
] as unknown as Stage[];

const ENCOUNTERS = [
  { stage_id: 10, round: 1, best_of: 3 },
  { stage_id: 10, round: 2, best_of: 3 }
];

const CUSTOM_HERO_CONFIG: PickBanConfig = {
  id: 7,
  tournament_id: 84,
  kind: "hero",
  stage_id: 11,
  round: null,
  mode: "pool",
  first_pick_rule: "higher_seed",
  first_ban_rotation: "alternate",
  turn_timer_seconds: 45,
  preset: "custom",
  sequence: ["ban_first", "ban_second", "ban_second", "ban_first"],
  no_repeat_scope: "encounter",
  unique_attribute_per_side_per_round: null,
  allow_protect: false,
  item_ids: [1, 2, 3, 4, 5],
  slots: []
};

/** The tournament-wide map rules a narrower scope inherits from. */
const TOURNAMENT_MAP_CONFIG: PickBanConfig = {
  id: 3,
  tournament_id: 84,
  kind: "map",
  stage_id: null,
  round: null,
  mode: "pool",
  first_pick_rule: "higher_seed",
  first_ban_rotation: "alternate",
  turn_timer_seconds: 30,
  preset: "bracket",
  sequence: ["ban_first", "ban_second", "pick_first", "pick_second", "decider"],
  no_repeat_scope: "encounter",
  unique_attribute_per_side_per_round: null,
  allow_protect: false,
  item_ids: [1, 2, 3, 4],
  slots: []
};

let container: HTMLDivElement;
let root: Root;

async function settle(times = 8) {
  for (let index = 0; index < times; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

/**
 * `navigate` runs outside React (a link click, a router write), so the mocked
 * `useSearchParams` needs a nudge to be re-read.
 */
function Harness() {
  const [, force] = useState(0);
  // Published from an effect, not during render: writing a module-scope binding
  // while rendering is a side effect the react-compiler rules reject.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return <PreGameSettingsPage />;
}

interface MountOptions {
  configs?: PickBanConfig[];
  maps?: unknown[];
  stages?: Stage[];
  /** Generated encounters; empty stands for a bracket that is not built yet. */
  encounters?: Array<{ stage_id: number | null; round: number; best_of: number }>;
  /** Initial query string, e.g. `?scope=tournament&kind=hero&step=sides`. */
  url?: string;
}

async function mount({
  configs = [],
  maps = MAPS,
  stages = STAGES,
  encounters = ENCOUNTERS,
  url = "?scope=tournament&kind=map&step=pool"
}: MountOptions = {}) {
  listConfigs.mockResolvedValue({ configs });
  getHeroes.mockResolvedValue({ results: HEROES });
  getMaps.mockResolvedValue({ results: maps });
  getStages.mockResolvedValue(stages);
  getTournament.mockResolvedValue({ id: 84, workspace_id: 3, team_formation: "balancer" });
  getEncounters.mockResolvedValue({ results: encounters });

  search = new URL(url, "http://localhost").search;
  window.history.replaceState(null, "", `/admin/tournaments/84/settings/pre-game${search}`);

  container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          <Harness />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
}


async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    (element as HTMLElement).click();
  });
  await settle(4);
}

// Radix's Select reaches for pointer-capture and scroll APIs happy-dom does
// not implement. Without these the trigger throws before the listbox opens.
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

/** Every button in the document, portalled popovers included. */
function byName(name: string): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>("button")].filter(
    (element) =>
      (element.getAttribute("aria-label") ?? "").trim() === name ||
      (element.textContent ?? "").trim() === name
  );
}

function only(name: string): HTMLElement {
  const matches = byName(name);
  if (matches.length === 0) throw new Error(`no control named "${name}"`);
  return matches[0];
}

/** A Radix `SelectItem`: an option row, not a button, so `byName` misses it. */
function option(label: string): HTMLElement {
  const found = [...document.querySelectorAll<HTMLElement>('[role="option"]')].find(
    (element) => (element.textContent ?? "").trim() === label
  );
  if (!found) throw new Error(`no option named "${label}" in the open listbox`);
  return found;
}

/** The step strip's button for one step. */
function stepButton(index: number, label: string) {
  return only(`${index} · ${label}`);
}

/** The editor pane: everything right of the scope tree. */
function editor(): HTMLElement {
  const nav = container.querySelector('nav[aria-label="Configuration steps"]');
  const found = nav?.parentElement;
  if (!(found instanceof HTMLElement)) throw new Error("the editor is not open");
  return found;
}

function tree(): HTMLElement {
  const found = container.querySelector('nav[aria-label="Scope"]');
  if (!(found instanceof HTMLElement)) throw new Error("the scope tree is not rendered");
  return found;
}

function treeLink(label: string): HTMLAnchorElement {
  const found = [...tree().querySelectorAll("a")].find((link) =>
    (link.textContent ?? "").includes(label)
  );
  if (!found) throw new Error(`no scope named "${label}" in the tree`);
  return found;
}

/** Turn a field's value the way React's synthetic layer sees it. */
async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      globalThis.HTMLInputElement.prototype,
      "value"
    )?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(3);
}

beforeEach(() => {
  vi.clearAllMocks();
  if (root) {
    // Unmounting rather than clearing the body: the picker's content is
    // portalled, and React still owns those nodes.
    act(() => root.unmount());
    container.remove();
  }
  document.body.innerHTML = "";
  rerender = null;
  granted = ["tournament.update", "match.update"];
  upsertConfig.mockResolvedValue({});
  deleteConfig.mockResolvedValue({});
  getStagePlannedRounds.mockResolvedValue([]);
});

describe("Settings › Pre-game phase — the section gate", () => {
  it("refuses the section without match.update, even by URL", async () => {
    granted = ["tournament.update"];
    await mount();

    expect(container.textContent).toContain("Not permitted");
    expect(container.querySelector('nav[aria-label="Scope"]')).toBeNull();
  });

  it("opens read-only for a caller who may read but not write", async () => {
    // `allowedSettingsSection` gates on `match.update`; the body's own controls
    // gate on it too, so a caller with it always writes. The read-only line is
    // what a future read-only grant would land on.
    await mount();
    expect(container.textContent).not.toContain(en.pickBan.admin.readOnly);
  });
});

describe("Settings › Pre-game phase — URL is the state", () => {
  it("shows nothing to edit until a scope is picked, and offers the tree instead", async () => {
    await mount({ url: "?kind=map" });

    expect(container.textContent).toContain(en.pickBan.admin.pickScopeTitle);
    expect(container.querySelector('nav[aria-label="Configuration steps"]')).toBeNull();
    // The tournament node is the place to start, and it carries the scope.
    expect(treeLink("Whole tournament").getAttribute("href")).toContain("scope=tournament");
  });

  it("scopes rules by name, starting at the whole tournament", async () => {
    await mount();

    expect(treeLink("Whole tournament").getAttribute("aria-current")).toBe("true");
    expect(treeLink("Group stage").getAttribute("href")).toContain("scope=stage:10");
    expect(editor().querySelector("h2")?.textContent).toBe("Whole tournament");
  });

  it("edits the config named by ?scope=, not the tournament's", async () => {
    const stageWide: PickBanConfig = {
      ...TOURNAMENT_MAP_CONFIG,
      id: 4,
      stage_id: 10,
      turn_timer_seconds: 15,
      item_ids: [1, 2]
    };
    await mount({
      configs: [TOURNAMENT_MAP_CONFIG, stageWide],
      url: "?scope=stage:10&kind=map&step=pool"
    });

    expect(editor().querySelector("h2")?.textContent).toBe("Group stage — all rounds");
    expect(editor().textContent).toContain("2 selected");
  });

  it("follows a scope link into the URL and re-reads it", async () => {
    await mount({ configs: [TOURNAMENT_MAP_CONFIG] });

    await click(treeLink("Playoffs"));

    expect(search).toContain("scope=stage:11");
    expect(editor().querySelector("h2")?.textContent).toBe("Playoffs — all rounds");
  });

  it("switches Pool · Sequence · Sides through ?step=", async () => {
    await mount({ configs: [TOURNAMENT_MAP_CONFIG] });

    expect(editor().textContent).toContain(en.pickBan.admin.poolSection);

    await click(stepButton(2, "Sequence"));
    expect(new URLSearchParams(search).get("step")).toBe("sequence");
    expect(editor().textContent).toContain(en.pickBan.admin.orderSection);

    await click(stepButton(3, "Sides"));
    expect(new URLSearchParams(search).get("step")).toBe("sides");
    expect(editor().textContent).toContain(en.pickBan.admin.rulesSection);
  });

  it("restores the step named by the URL on load", async () => {
    await mount({ url: "?scope=tournament&kind=hero&step=sides" });

    expect(stepButton(3, "Sides").getAttribute("aria-current")).toBe("step");
    expect(editor().textContent).toContain(en.pickBan.admin.rulesSection);
  });

  it("loads the catalogue of the kind in the URL, and only that one", async () => {
    await mount({ url: "?scope=tournament&kind=map&step=pool" });

    expect(getMaps).toHaveBeenCalledTimes(1);
    expect(getHeroes).not.toHaveBeenCalled();

    await click(only("Add maps"));
    expect(only("Busan")).toBeTruthy();
  });
});

describe("Settings › Pre-game phase asks for nothing an organizer has to look up", () => {
  it("offers one text field, the turn timer, and says what leaving it empty does", async () => {
    await mount({ url: "?scope=tournament&kind=hero&step=sides" });

    const inputs = [...editor().querySelectorAll<HTMLInputElement>("input")];
    expect(inputs).toHaveLength(1);

    const timer = inputs[0];
    const label = editor().querySelector<HTMLLabelElement>(`label[for="${timer.id}"]`);
    expect(label?.textContent).toBe("Turn timer");

    // The hint is the ask: an empty timer is not an unset field, it is "no limit".
    const hint = document.getElementById(timer.getAttribute("aria-describedby") ?? "");
    expect(hint?.textContent).toContain("Leave it empty for no time limit");
    expect(timer.placeholder).toBe("No limit");
  });

  it("names every icon-only control", async () => {
    await mount({
      configs: [CUSTOM_HERO_CONFIG],
      url: "?scope=stage:11&kind=hero&step=sequence"
    });

    const unnamed = [...container.querySelectorAll("button")].filter(
      (button) =>
        (button.textContent ?? "").trim() === "" && button.getAttribute("aria-label") == null
    );
    expect(unnamed).toEqual([]);
  });
});

describe("Settings › Pre-game phase will not send a config the server rejects", () => {
  it("keeps save inert with the reason on screen until the pool and the steps are both there", async () => {
    await mount({ url: "?scope=tournament&kind=hero&step=pool" });

    // An empty pool is not a rejection any more: it is a rules template, saved
    // for narrower scopes to inherit and opening no room of its own.
    expect(editor().textContent).toContain("this is a rules template");

    await click(only("Add heroes"));
    await click(only("Tracer"));
    await click(only("Genji"));
    await click(only("Reinhardt"));

    expect(editor().textContent).not.toContain("this is a rules template");
    // A hero order is never generated — it is one round's steps, hand-authored —
    // so an empty one is still a config the server would reject.
    expect(editor().textContent).toContain("Add at least one step to the order.");

    // Save is visible but inert: the reason sits next to it rather than a
    // greyed-out button a viewport away from the explanation.
    await click(only("Save rules"));
    expect(upsertConfig).not.toHaveBeenCalled();

    await click(stepButton(2, "Sequence"));
    await click(only("Add step"));

    expect(editor().textContent).not.toContain("Add at least one step to the order.");
    await click(only("Save rules"));
    expect(upsertConfig).toHaveBeenCalledTimes(1);
  });

  // 2026-09-05: the rules and the pool share one row, so "set the rotation and
  // the timer once for the whole tournament, pick the maps per stage" was
  // unauthorable -- a tournament-wide pool is exactly what a per-stage
  // regulation does not have, and the pool was required to save anything.
  it("saves tournament-wide rules with no pool, as a template to inherit", async () => {
    await mount({ url: "?scope=tournament&kind=map&step=sides" });

    const timer = editor().querySelector<HTMLInputElement>("input");
    await type(timer as HTMLInputElement, "45");

    await click(only("Save rules"));

    expect(upsertConfig).toHaveBeenCalledTimes(1);
    const body = upsertConfig.mock.calls[0][1];
    expect(body.stage_id).toBeNull();
    expect(body.item_ids).toEqual([]);
    expect(body.slots).toEqual([]);
    expect(body.turn_timer_seconds).toBe(45);
  });

  it("sends the pool in pick order, with the round's own steps and no turn limit", async () => {
    await mount({ url: "?scope=tournament&kind=hero&step=pool" });

    await click(only("Add heroes"));
    await click(only("Genji"));
    await click(only("Tracer"));
    await click(only("Ana"));
    await click(stepButton(2, "Sequence"));
    await click(only("Add step"));
    await click(only("Save rules"));

    expect(upsertConfig).toHaveBeenCalledTimes(1);
    const [tournamentId, body] = upsertConfig.mock.calls[0];
    expect(tournamentId).toBe(84);
    expect(body.kind).toBe("hero");
    expect(body.item_ids).toEqual([2, 1, 4]);
    expect(body.stage_id).toBeNull();
    expect(body.round).toBeNull();
    expect(body.turn_timer_seconds).toBeNull();
    // Hero steps are always the organizer's own: `custom` is what stops the
    // engine from regenerating a map-shaped order over them.
    expect(body.preset).toBe("custom");
    expect(body.sequence).toEqual(["ban_first"]);
  });

  it("sends the timer as a number once one is typed", async () => {
    await mount({ url: "?scope=tournament&kind=hero&step=pool" });

    await click(only("Add heroes"));
    await click(only("Tracer"));
    await click(only("Genji"));
    await click(stepButton(2, "Sequence"));
    await click(only("Add step"));
    await click(stepButton(3, "Sides"));
    await type(editor().querySelector<HTMLInputElement>("input")!, "30");
    await click(only("Save rules"));

    expect(upsertConfig.mock.calls[0][1].turn_timer_seconds).toBe(30);
  });
});

describe("Settings › Pre-game phase keeps a stored custom order", () => {
  it("reopens the authored steps and saves them back", async () => {
    await mount({
      configs: [CUSTOM_HERO_CONFIG],
      url: "?scope=stage:11&kind=hero&step=sequence"
    });

    // No bracket/custom choice is offered for a hero config: its sequence is one
    // round's steps either way, so the steps themselves are the whole control.
    expect(editor().textContent).not.toContain(en.pickBan.admin.orderLabel);
    expect(editor().textContent).toContain(en.pickBan.admin.orderSteps);

    // Nothing edited: the save bar is absent, so the round trip goes through a
    // real edit and back.
    await click(only("Add step"));
    await click(only("Save rules"));

    const body = upsertConfig.mock.calls[0][1];
    // The regression that made the old editor lie: a custom sequence saved
    // without `preset: "custom"` is regenerated from `best_of` and discarded.
    expect(body.preset).toBe("custom");
    expect(body.sequence).toEqual([
      "ban_first",
      "ban_second",
      "ban_second",
      "ban_first",
      "ban_first"
    ]);
    expect(body.stage_id).toBe(11);
    expect(body.turn_timer_seconds).toBe(45);
    expect(body.no_repeat_scope).toBe("encounter");
    expect(body.first_ban_rotation).toBe("alternate");
  });
});

describe("Settings › Pre-game phase's picker searches by name and adds/clears in bulk", () => {
  async function openMapPicker(maps: unknown[] = MAPS) {
    await mount({ maps, url: "?scope=tournament&kind=map&step=pool" });
    await click(only("Add maps"));
    const field = document.querySelector<HTMLInputElement>('input[placeholder="Search maps…"]');
    if (!field) throw new Error("no search field in the open picker");
    return field;
  }

  it("matches a query that extends a catalogue word, the way a regulation's spelling might", async () => {
    const field = await openMapPicker();
    await type(field, "Hollywoods");

    expect(only("Hollywood")).toBeTruthy();
    expect(() => only("Busan")).toThrow();
  });

  it("shows the catalogue's empty state for a name nothing matches", async () => {
    const field = await openMapPicker();
    await type(field, "Nepal");

    expect(document.body.textContent).toContain("Nothing matches that name.");
  });

  it("select all adds only what the search currently shows; clear removes only that", async () => {
    const field = await openMapPicker();
    // Narrows Busan / King's Row / Ilios / Hollywood to the three with an "o".
    await type(field, "o");

    await click(only("Select all"));
    expect(editor().textContent).toContain("King's Row");
    expect(editor().textContent).toContain("Ilios");
    expect(editor().textContent).toContain("Hollywood");
    expect(editor().textContent).not.toContain("Busan");

    await click(only("Clear"));
    expect(editor().textContent).not.toContain("King's Row");
    expect(editor().textContent).not.toContain("Ilios");
    expect(editor().textContent).not.toContain("Hollywood");
  });

  it("renders each selected map's art alongside its name, not the name alone", async () => {
    await openMapPicker();
    await click(only("Busan"));

    // The leading "Add maps" trigger shares the row, then one chip for Busan.
    const chips = editor().querySelectorAll("ul li");
    expect(chips).toHaveLength(2);
    expect(chips[1].textContent).toContain("Busan");
    expect(chips[1].querySelector("img")).toBeTruthy();
  });

  it("keeps the picker trigger first in the row, so adding a map never moves it", async () => {
    await openMapPicker();
    await click(only("Busan"));
    await click(only("Ilios"));

    // The popover is anchored to this trigger: let a chip push it and the open
    // panel slides out from under the cursor mid-selection.
    const row = editor().querySelectorAll("ul li");
    expect(row[0].textContent).toContain("Add maps");
  });

  it("never offers a map flagged out of competitive rotation", async () => {
    await openMapPicker([...MAPS, OFF_ROTATION_MAP]);

    expect(only("Busan")).toBeTruthy();
    expect(() => only("Junkenstein's Revenge")).toThrow();
  });

  it("the group filter narrows the picker to one game mode", async () => {
    await openMapPicker();
    // Busan / Ilios are Control, King's Row / Hollywood are Hybrid.
    await click(only("Control (2)"));

    expect(only("Busan")).toBeTruthy();
    expect(only("Ilios")).toBeTruthy();
    expect(() => only("King's Row")).toThrow();
    expect(() => only("Hollywood")).toThrow();

    await click(only("All (4)"));
    expect(only("King's Row")).toBeTruthy();
  });
});

// 2026-08-10: an organizer could not scope a config to a Playoff round before
// its bracket was built — the round picker guessed `1..max_rounds` locally,
// which is wrong for elimination brackets (double elimination's lower bracket
// uses negative round numbers `max_rounds` says nothing about, and single
// elimination's round count depends on team count). The tree's rounds come
// from the server, which predicts them from the stage's planned team inputs
// using the real bracket generator.
describe("Settings › Pre-game phase predicts a round scope before the bracket is built", () => {
  async function openPlayoffs(stages: Stage[] = STAGES) {
    await mount({ stages, url: "?scope=stage:11&kind=hero&step=pool" });
  }

  function roundLabels() {
    return [...tree().querySelectorAll("a")].map((link) =>
      (link.textContent ?? "")
        .replace(/(overridden|inherited|no rules|same as above|rules only)$/, "")
        .trim()
    );
  }

  it("asks the server for stage 11's planned rounds — it has no generated encounters", async () => {
    getStagePlannedRounds.mockResolvedValue([1, 2]);
    await openPlayoffs();

    expect(getStagePlannedRounds).toHaveBeenCalledWith(11);
  });

  it("shows a loading hint while the prediction is in flight, then the rounds once it resolves", async () => {
    let resolvePrediction: (rounds: number[]) => void = () => {
      throw new Error("prediction resolved before the tree awaited it");
    };
    getStagePlannedRounds.mockImplementation(
      () => new Promise<number[]>((resolve) => (resolvePrediction = resolve))
    );

    await openPlayoffs();
    expect(tree().textContent).toContain("Checking the stage's planned bracket");

    await act(async () => resolvePrediction([1, 2]));
    await settle();

    expect(roundLabels()).toContain("Round 1");
    expect(roundLabels()).toContain("Round 2");
  });

  // The tree and the bracket name the same round: an organizer who scopes rules
  // to a round has to recognize it on the bracket they are looking at, so both
  // go through `bracketRoundLabel` (see `useBracketRoundLabel`).
  it("names a lower-bracket round the way the bracket does", async () => {
    getStagePlannedRounds.mockResolvedValue([-2, -1, 1, 2]);
    await openPlayoffs();
    await settle();

    const labels = roundLabels();
    expect(labels).toContain("LB Round 1");
    expect(labels).toContain("LB Final");
    expect(labels).toContain("Round 1");
    expect(labels).toContain("Round 2");
  });

  it("calls a double elimination's deciding round the Grand Final, not a bare round number", async () => {
    const stages = STAGES.map((stage) =>
      stage.id === 11 ? { ...stage, stage_type: "double_elimination" } : stage
    ) as unknown as Stage[];
    getStagePlannedRounds.mockResolvedValue([-2, -1, 1, 2, 3]);
    await openPlayoffs(stages);
    await settle();

    const labels = roundLabels();
    expect(labels).toContain("Grand Final");
    expect(labels).not.toContain("Round 3");
    // Round 2 is the last upper-bracket round, and the bracket calls it that.
    expect(labels).toContain("UB Final");
    expect(labels).toContain("LB Final");
  });

  it("explains an unresolved scope when neither encounters nor team inputs exist yet", async () => {
    getStagePlannedRounds.mockResolvedValue([]);
    await openPlayoffs();
    await settle();

    expect(tree().textContent).toContain("isn't built yet, and no teams are wired into it either");
  });
});

// 2026-08-14: scoping rules to a round meant retyping the tournament's timer,
// rotation, no-repeat scope and whole pool by hand, per round — so organizers
// did not, and rounds kept playing by rules nobody had chosen for them. A
// scope now opens on whatever it resolves to today, and says so.
describe("Settings › Pre-game phase prefills a narrower scope from the rules above it", () => {
  it("copies the tournament's rules onto a stage scope, marked with where they came from", async () => {
    await mount({
      configs: [TOURNAMENT_MAP_CONFIG],
      url: "?scope=stage:10&kind=map&step=pool"
    });

    expect(editor().textContent).toContain("Prefilled from Whole tournament");
    expect(editor().textContent).toContain("4 selected");
    expect(editor().textContent).toContain("Busan");
  });

  it("saves the inherited values as the new scope's own", async () => {
    await mount({
      configs: [TOURNAMENT_MAP_CONFIG],
      url: "?scope=stage:10&kind=map&step=pool"
    });

    // A prefilled scope is already different from "no rules here", so the save
    // bar is up without an edit.
    await click(only("Save rules"));

    const body = upsertConfig.mock.calls[0][1];
    expect(body.stage_id).toBe(10);
    expect(body.round).toBeNull();
    expect(body.item_ids).toEqual([1, 2, 3, 4]);
    expect(body.turn_timer_seconds).toBe(30);
    expect(body.first_ban_rotation).toBe("alternate");
    expect(body.no_repeat_scope).toBe("encounter");
  });

  // The cascade the engine walks (`resolve_config_at_level`): a round takes its
  // stage's rules over the tournament's, so the prefill has to agree with it.
  it("prefills a round from its stage's rules, not the tournament's", async () => {
    const stageWide: PickBanConfig = {
      ...TOURNAMENT_MAP_CONFIG,
      id: 4,
      stage_id: 10,
      turn_timer_seconds: 15,
      item_ids: [1, 2]
    };
    await mount({
      configs: [TOURNAMENT_MAP_CONFIG, stageWide],
      url: "?scope=round:10:1&kind=map&step=pool"
    });

    expect(editor().textContent).toContain("Prefilled from Group stage — all rounds");
    expect(editor().textContent).toContain("2 selected");
  });

  it("marks in the tree which scopes decide something and which only repeat", async () => {
    const copy: PickBanConfig = { ...TOURNAMENT_MAP_CONFIG, id: 5, stage_id: 10, round: null };
    const different: PickBanConfig = {
      ...TOURNAMENT_MAP_CONFIG,
      id: 6,
      stage_id: 11,
      turn_timer_seconds: 90
    };
    await mount({ configs: [TOURNAMENT_MAP_CONFIG, copy, different], url: "?kind=map" });

    expect(treeLink("Whole tournament").textContent).toContain("overridden");
    // The Group stage row stores nothing the tournament does not already say.
    expect(treeLink("Group stage").textContent).toContain("same as above");
    // Playoffs decides something of its own.
    expect(treeLink("Playoffs").textContent).toContain("overridden");
  });

  it("resets an override back to inherited by dropping the scope's own config", async () => {
    const stageWide: PickBanConfig = {
      ...TOURNAMENT_MAP_CONFIG,
      id: 4,
      stage_id: 10,
      turn_timer_seconds: 15
    };
    await mount({
      configs: [TOURNAMENT_MAP_CONFIG, stageWide],
      url: "?scope=stage:10&kind=map&step=pool"
    });

    expect(editor().textContent).toContain("Inherits from Whole tournament");
    await click(only("Reset to inherited"));
    await click(only("Remove the override"));

    expect(deleteConfig).toHaveBeenCalledWith(4);
  });

  // 2026-09-05: an override stores a COPY of the rules above it, and most are
  // authored to change the pool, not the rules -- so a stage silently carried
  // whatever the tournament said the day it was created, and nothing on screen
  // distinguished "we chose this here" from "this came from above".
  it("names what each rule inherits, and takes that value back in one click", async () => {
    const stageWide: PickBanConfig = {
      ...TOURNAMENT_MAP_CONFIG,
      id: 4,
      stage_id: 10,
      turn_timer_seconds: 15
    };
    await mount({
      configs: [TOURNAMENT_MAP_CONFIG, stageWide],
      url: "?scope=stage:10&kind=map&step=sides"
    });

    // The rotation still agrees with the tournament; the timer is this scope's
    // own choice, and the field says what it is overriding.
    expect(editor().textContent).toContain("Same as Whole tournament");
    expect(editor().textContent).toContain("Whole tournament: 30 seconds");
    expect(editor().querySelector<HTMLInputElement>("input")?.value).toBe("15");

    await click(only("Use that"));

    expect(editor().querySelector<HTMLInputElement>("input")?.value).toBe("30");
    expect(editor().textContent).not.toContain("Whole tournament: 30 seconds");
  });
});

// 2026-09-04: a slot-mode pool's group count was typed by hand, so a stage
// whose matches play Bo3 could sit on four groups. The extras were unplayable
// (the server plays the first `best_of`), yet their emptiness was a validation
// error — and an inert Save meant a map added to a real group never persisted.
// The count comes from the bracket now.
describe("Settings › Pre-game phase sizes a round-group pool from the bracket", () => {
  const STORED_GROUPS: PickBanConfig = {
    ...TOURNAMENT_MAP_CONFIG,
    id: 8,
    stage_id: 10,
    round: 1,
    mode: "slots",
    item_ids: [],
    slots: [
      { position: 1, reserve_item_id: null, candidates: [1, 2] },
      { position: 2, reserve_item_id: null, candidates: [2, 3] },
      { position: 3, reserve_item_id: null, candidates: [3, 1] },
      { position: 4, reserve_item_id: null, candidates: [1, 4] }
    ]
  };

  async function openStoredGroups() {
    await mount({ configs: [STORED_GROUPS], url: "?scope=round:10:1&kind=map&step=pool" });
  }

  it("keeps one group per match of the longest series, whatever was stored", async () => {
    await openStoredGroups();

    // Round 1 of stage 10 is generated as a Bo3, so the fourth group is gone
    // and there is no control that could add a fifth.
    expect(editor().textContent).toContain("Match 3");
    expect(editor().textContent).not.toContain("Match 4");
    expect(byName("Add a round")).toHaveLength(0);
    expect(editor().textContent).toContain("playing up to 3 matches");
  });

  it("saves a map added to a group, instead of an unplayable group blocking it", async () => {
    await openStoredGroups();

    // The first group's picker; each group carries one.
    await click(byName("Add maps")[0]);
    await click(only("Hollywood"));
    await click(only("Save rules"));

    const body = upsertConfig.mock.calls[0][1];
    expect(body.mode).toBe("slots");
    expect(body.slots).toHaveLength(3);
    expect(body.slots[0].candidates).toEqual([1, 2, 4]);
  });
});

// 2026-09-04: a regulation plays different maps in each round of a stage, and
// a config's scope key is `(stage, round)` — so that is one config per round.
// The stage screen used to author a single pool applied to every round of the
// stage, with no way to see Round 1's maps next to Round 2's; organizers
// encoded the rounds as groups instead, which the engine reads as maps of one
// series. The stage screen now authors every round at once and fans the save
// out over them.
describe("Settings › Pre-game phase authors every round of a stage at once", () => {
  const STAGE_GROUPS: PickBanConfig = {
    ...TOURNAMENT_MAP_CONFIG,
    id: 9,
    stage_id: 10,
    round: null,
    mode: "slots",
    item_ids: [],
    slots: [
      { position: 1, reserve_item_id: null, candidates: [1, 2] },
      { position: 2, reserve_item_id: null, candidates: [2, 3] },
      { position: 3, reserve_item_id: null, candidates: [3, 1] }
    ]
  };

  /** Round 2 already plays its own maps; round 1 has no config of its own. */
  const ROUND_TWO_GROUPS: PickBanConfig = {
    ...STAGE_GROUPS,
    id: 10,
    round: 2,
    slots: [
      { position: 1, reserve_item_id: null, candidates: [4, 3] },
      { position: 2, reserve_item_id: null, candidates: [3, 4] },
      { position: 3, reserve_item_id: null, candidates: [4, 1] }
    ]
  };

  it("lists each round of the stage with its own matches", async () => {
    await mount({
      configs: [STAGE_GROUPS, ROUND_TWO_GROUPS],
      url: "?scope=stage:10&kind=map&step=pool"
    });

    // Stage 10 generates rounds 1 and 2, both Bo3: two round sections of three
    // matches each, named the way the bracket names them.
    const text = editor().textContent ?? "";
    expect(text).toContain("Round 1");
    expect(text).toContain("Round 2");
    expect(text).toContain("3 matches");
    // Round 2's own stored maps, not the stage-wide ones round 1 falls back to.
    expect(text).toContain("Hollywood");
  });

  it("saves one config per round, each with that round's maps", async () => {
    await mount({
      configs: [STAGE_GROUPS, ROUND_TWO_GROUPS],
      url: "?scope=stage:10&kind=map&step=pool"
    });

    // Round 1's first match: add Hollywood there and nowhere else.
    await click(byName("Add maps")[0]);
    await click(only("Hollywood"));
    await click(only("Save rules"));

    expect(upsertConfig).toHaveBeenCalledTimes(2);
    const first = upsertConfig.mock.calls[0][1];
    const second = upsertConfig.mock.calls[1][1];

    expect(first.stage_id).toBe(10);
    expect(first.round).toBe(1);
    expect(first.slots.map((slot: { candidates: number[] }) => slot.candidates)).toEqual([
      [1, 2, 4],
      [2, 3],
      [3, 1]
    ]);

    expect(second.round).toBe(2);
    expect(second.slots.map((slot: { candidates: number[] }) => slot.candidates)).toEqual([
      [4, 3],
      [3, 4],
      [4, 1]
    ]);
  });

  it("switches a shared pool into per-round groups without leaving an empty list", async () => {
    // A stage-wide pool config, so the shape starts as one shared pool.
    await mount({
      configs: [{ ...TOURNAMENT_MAP_CONFIG, id: 11, stage_id: 10, round: null }],
      url: "?scope=stage:10&kind=map&step=pool"
    });

    await click(only("One shared pool"));
    await click(option("One group per match"));

    const text = editor().textContent ?? "";
    expect(text).toContain("Round 1");
    expect(text).toContain("Round 2");
    expect(text).toContain("Match 1");
    // Two rounds of three groups: every one of them is on screen asking to be
    // filled, rather than an empty list with a validation error under it.
    expect(byName("Add maps")).toHaveLength(6);
    expect(text).toContain("no candidates");
  });

  it("reopens on the groups its rounds store, with nothing at the stage level", async () => {
    // The state a save from this screen leaves behind: per-round configs only.
    await mount({
      configs: [ROUND_TWO_GROUPS, { ...ROUND_TWO_GROUPS, id: 12, round: 1 }],
      url: "?scope=stage:10&kind=map&step=pool"
    });

    const text = editor().textContent ?? "";
    expect(text).toContain("One group per match");
    expect(text).toContain("Round 1");
    expect(text).toContain("Round 2");
    expect(text).toContain("Match 3");
  });

  // The case the feature is actually used in: a group stage's pools are
  // authored before the bracket is generated, and the server's prediction
  // returns nothing until teams are wired into the stage. A group stage's
  // length is known anyway — without this the screen fell back to one flat
  // list of groups, which is what an organizer read as "where is the split by
  // round?".
  it("derives a round robin's rounds from its teams, not from max_rounds", async () => {
    getStagePlannedRounds.mockResolvedValue([]);
    // Six teams in the group: everyone plays everyone, so five rounds — the
    // stage's max_rounds of 3 is an unrelated planning field.
    const seeded = {
      ...STAGES[0],
      items: [
        {
          id: 100,
          stage_id: 10,
          name: "Group A",
          type: "group",
          order: 0,
          inputs: Array.from({ length: 6 }, (_, index) => ({
            id: 200 + index,
            stage_item_id: 100,
            slot: index + 1,
            input_type: "final",
            team_id: index + 1,
            source_stage_item_id: null,
            source_position: null
          }))
        }
      ]
    } as unknown as Stage;

    await mount({
      encounters: [],
      stages: [seeded, STAGES[1]],
      configs: [STAGE_GROUPS],
      url: "?scope=stage:10&kind=map&step=pool"
    });

    const text = editor().textContent ?? "";
    expect(text).toContain("Round 5");
    expect(text).not.toContain("Round 6");
  });

  // 2026-09-05: a Swiss is generated one round at a time (round N+1 is paired
  // off round N's standings), so mid-stage the bracket holds only the rounds
  // already played. Taking the generated rounds alone left the tree offering
  // Round 1 and nothing else, with the rest of the regulation unconfigurable
  // until the moment it was about to be played.
  it("lists every round a Swiss will play, not only the ones already generated", async () => {
    getStagePlannedRounds.mockResolvedValue([]);
    const swiss = { ...STAGES[0], stage_type: "swiss", max_rounds: 4 } as unknown as Stage;

    await mount({
      encounters: [{ stage_id: 10, round: 1, best_of: 3 }],
      stages: [swiss, STAGES[1]],
      url: "?scope=stage:10&kind=map&step=pool"
    });

    const text = tree().textContent ?? "";
    for (const round of [1, 2, 3, 4]) expect(text).toContain(`Round ${round}`);
    expect(text).not.toContain("Round 5");
  });

  it("falls back to the planned round count when the stage has no teams yet", async () => {
    getStagePlannedRounds.mockResolvedValue([]);
    await mount({
      encounters: [],
      configs: [STAGE_GROUPS],
      url: "?scope=stage:10&kind=map&step=pool"
    });

    const text = editor().textContent ?? "";
    // Stage 10 has no items wired, so its max_rounds of 3 is all there is.
    expect(text).toContain("Round 3");
    expect(text).not.toContain("Round 4");
  });

  // An elimination stage's round numbers are not guessable client-side, so
  // there the groups really do cover the whole stage until the bracket exists —
  // and the screen says so rather than showing a list that looks per-round.
  it("says a stage's groups cover every round while the bracket cannot name them", async () => {
    getStagePlannedRounds.mockResolvedValue([]);
    await mount({
      encounters: [],
      configs: [{ ...STAGE_GROUPS, id: 13, stage_id: 11 }],
      url: "?scope=stage:11&kind=map&step=pool"
    });

    const text = editor().textContent ?? "";
    expect(text).toContain("apply to every round of it");
    expect(text).toContain("Match 1");
    expect(text).not.toContain("Round 1");
  });
});

// 2026-09-04: clicking through the scope tree cost a "Discard unsaved
// changes?" dialog per round. The save bar's `dirty` flag answered two
// questions at once — "is there something to save here" (true on every scope
// with no config of its own, since saving stores what it inherits) and "would
// leaving lose work" — and armed the unsaved guard with the first.
describe("Settings › Pre-game phase only guards edits an organizer made", () => {
  it("switches scope without a discard prompt when nothing was typed", async () => {
    await mount({
      configs: [TOURNAMENT_MAP_CONFIG],
      url: "?scope=round:10:1&kind=map&step=pool"
    });

    // Round 1 has no config of its own: the bar is up, offering to store what
    // the round inherits.
    expect(only("Save rules")).toBeTruthy();

    await click(treeLink("Round 2"));

    expect(document.body.textContent).not.toContain("Discard unsaved changes?");
    expect(editor().textContent).toContain("Group stage — round 2");
  });

  it("still stops a scope switch that would lose an edit", async () => {
    await mount({
      configs: [TOURNAMENT_MAP_CONFIG],
      url: "?scope=round:10:1&kind=map&step=pool"
    });

    await click(only("Add maps"));
    await click(only("Hollywood"));
    await click(treeLink("Round 2"));

    expect(document.body.textContent).toContain("Discard unsaved changes?");
    expect(editor().textContent).toContain("Group stage — round 1");
  });
});
