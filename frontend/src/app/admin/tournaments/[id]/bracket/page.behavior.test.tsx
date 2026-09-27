// @vitest-environment happy-dom
//
// The Bracket tab (T4, F7). What is pinned here:
//  1. the permission gate that survived the split — only a superuser may change
//     a stage's format after creation, and a non-superuser is told why rather
//     than left with a control that silently does nothing;
//  2. `?stage=` and `?section=` ARE the state: selecting pushes a linkable URL,
//     and a section that does not apply to the stage's format falls back to
//     General instead of rendering an empty panel. Without `?stage=` a wide
//     viewport opens the last stage; a narrow one keeps the list, because
//     `MasterDetail`'s Back there is `history.back()`;
//  3. one destructive operation end to end — the kebab opens the screen's ONE
//     `ConfirmDialog` (the old screen mounted seven), and confirming calls the
//     mutation and clears the selection;
//  4. the stage header is an `<h2>`, because the tournament hub around it owns
//     the page's `<h1>`.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Stage } from "@/types/tournament.types";

import BracketTabPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getStages = vi.fn();
const getTournament = vi.fn();
const getStagesProgress = vi.fn();
const deleteStage = vi.fn();
const getTeams = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getStages: (...args: unknown[]) => getStages(...args),
    getTournament: (...args: unknown[]) => getTournament(...args),
    getStagesProgress: (...args: unknown[]) => getStagesProgress(...args),
    deleteStage: (...args: unknown[]) => deleteStage(...args),
    updateStage: vi.fn(),
    // The Bracket preview draws the generator's own skeleton; this tab's
    // assertions are about routing and permissions, so it stays empty here.
    getStageBracketPreview: vi.fn().mockResolvedValue([])
  }
}));

vi.mock("@/services/team.service", () => ({
  default: { getAll: (...args: unknown[]) => getTeams(...args) }
}));

vi.mock("@/services/encounter.service", () => ({
  default: { getAll: vi.fn().mockResolvedValue({ results: [], total: 0 }) }
}));

let isSuperuser = true;
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ isSuperuser })
}));

let isMobile = false;
vi.mock("@/hooks/useMobile", () => ({
  useIsMobile: () => isMobile
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

let currentSearch = "";
let rerender: (() => void) | null = null;

const push = vi.fn((url: string) => {
  currentSearch = new URL(url, "http://localhost").search;
  rerender?.();
});
// Deliberately NOT aliased to `push`: `MasterDetail`'s narrow-viewport "Back to
// list" is `history.back()`, which only returns to the list if the selection
// was PUSHED. A `replace` here would strand the user, so the test has to be
// able to tell the two apart.
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace, back: vi.fn() }),
  usePathname: () => "/admin/tournaments/84/bracket",
  useParams: () => ({ id: "84" }),
  useSearchParams: () => new URLSearchParams(currentSearch)
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: unknown }) => (
    <a href={href} {...rest}>
      {children as never}
    </a>
  )
}));

// Partial: `useHubEncountersQuery`, which the Bracket preview observes, reads
// the real key factory from this module.
vi.mock("@/lib/tournament/workspace-query-keys", async (importOriginal) => ({
  ...((await importOriginal()) as object),
  invalidateTournamentWorkspace: vi.fn()
}));

function groupStage(): Stage {
  return {
    id: 10,
    tournament_id: 84,
    name: "Groups",
    description: null,
    stage_type: "round_robin",
    max_rounds: 3,
    advance_count: 2,
    split_lower_bracket: false,
    order: 0,
    is_active: true,
    is_published: true,
    is_completed: false,
    ranking_preset: null,
    tiebreak_order: null,
    scoring: { win: null, draw: null, loss: null },
    swiss_bye_points: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 3, by_round: {}, final: null },
    ffa_scoring: { placement_points: [], score_points: 1, score_label: null },
    challonge_id: null,
    challonge_slug: null,
    items: [
      {
        id: 100,
        stage_id: 10,
        name: "Group A",
        type: "group",
        order: 0,
        inputs: [
          {
            id: 200,
            stage_item_id: 100,
            slot: 1,
            input_type: "final",
            team_id: 1,
            source_stage_item_id: null,
            source_position: null
          }
        ]
      }
    ]
  } as unknown as Stage;
}

function playoffStage(): Stage {
  return {
    id: 20,
    tournament_id: 84,
    name: "Playoff",
    description: null,
    stage_type: "double_elimination",
    max_rounds: 4,
    advance_count: null,
    split_lower_bracket: false,
    order: 1,
    is_active: false,
    is_published: false,
    is_completed: false,
    ranking_preset: null,
    tiebreak_order: null,
    scoring: { win: null, draw: null, loss: null },
    swiss_bye_points: null,
    de_grand_final_type: "no_reset",
    seed_ranking: "slot",
    best_of: { default: 3, by_round: {}, final: null },
    ffa_scoring: { placement_points: [], score_points: 1, score_label: null },
    challonge_id: null,
    challonge_slug: null,
    items: []
  } as unknown as Stage;
}

let container: HTMLDivElement;
let root: Root;

async function settle(times = 12) {
  for (let index = 0; index < times; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

function Harness() {
  const [, force] = useState(0);
  // Published from an effect, not during render: writing a module-scope binding
  // while rendering is a side effect the react-compiler rules reject.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return <BracketTabPage />;
}

async function mount(search = "") {
  currentSearch = search;
  getStages.mockResolvedValue([groupStage(), playoffStage()]);
  getTournament.mockResolvedValue({ id: 84, name: "Cup", win_points: 1 });
  getStagesProgress.mockResolvedValue([]);
  getTeams.mockResolvedValue({ results: [{ id: 1, name: "Team One" }] });

  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        >
          <Harness />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
}

async function click(element: Element | null | undefined) {
  if (!element) throw new Error("nothing to click");
  await act(async () => {
    element.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    (element as HTMLElement).click();
  });
  await settle(4);
}

/** Anywhere in the document, so portalled menus and dialogs are included. */
function named(selector: string, text: string): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>(selector)].filter(
    (element) => (element.textContent ?? "").trim() === text
  );
}

function label(selector: string, accessibleName: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`${selector}[aria-label="${accessibleName}"]`);
}

function bodyText() {
  return document.body.textContent ?? "";
}

/** Only the section tabs; the trigger of a tab is a link. */
function sectionTab(text: string): HTMLAnchorElement | null {
  return (
    [...container.querySelectorAll<HTMLAnchorElement>("nav a")].find(
      (element) => (element.textContent ?? "").trim().startsWith(text)
    ) ?? null
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  isSuperuser = true;
  isMobile = false;
  if (root) {
    act(() => root.unmount());
    container.remove();
  }
  deleteStage.mockResolvedValue(undefined);
});

describe("Bracket tab · permission gate", () => {
  it("lets a superuser change the stage format", async () => {
    await mount("?stage=10");

    expect(label("button", "Format")).toBeNull();
    const format = [...container.querySelectorAll("label")].find(
      (element) => (element.textContent ?? "").trim() === "Format"
    );
    const trigger = format?.parentElement?.querySelector("button");
    expect(trigger?.hasAttribute("disabled")).toBe(false);
    expect(bodyText()).not.toContain("Only superusers can modify stage type");
  });

  it("locks the format for a non-superuser and says why", async () => {
    isSuperuser = false;
    await mount("?stage=10");

    const format = [...container.querySelectorAll("label")].find(
      (element) => (element.textContent ?? "").trim() === "Format"
    );
    const trigger = format?.parentElement?.querySelector("button");
    expect(trigger?.hasAttribute("disabled")).toBe(true);
    expect(bodyText()).toContain("Only superusers can modify stage type after creation.");
  });
});

describe("Bracket tab · URL is the state", () => {
  it("opens the last stage by default on a wide viewport", async () => {
    await mount();

    // Seeding flows top to bottom, so the last stage is the one still in work.
    expect(container.querySelector('nav[aria-label="Playoff sections"]')).not.toBeNull();
    expect(bodyText()).toContain("Double Elimination");
    // Not written to the URL: a default is not a navigation.
    expect(push).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });

  it("keeps the list as the landing surface on a narrow viewport", async () => {
    isMobile = true;
    await mount();

    expect(bodyText()).toContain("No stage selected");
    expect(named("button", "Groups")).toHaveLength(1);
    expect(named("button", "Playoff")).toHaveLength(1);
    expect(container.querySelector('nav[aria-label="Playoff sections"]')).toBeNull();
  });

  it("selecting a stage pushes `?stage=` and opens that stage's editor", async () => {
    await mount();

    await click(named("button", "Groups")[0]);

    expect(push).toHaveBeenCalledWith("/admin/tournaments/84/bracket?stage=10");
    // A history entry, so `MasterDetail`'s mobile "Back to list" works.
    expect(replace).not.toHaveBeenCalled();
    expect(container.querySelector('nav[aria-label="Groups sections"]')).not.toBeNull();
    // The editor header names the selected stage's format.
    expect(bodyText()).toContain("Round Robin");
  });

  it("`?section=` chooses the section, and marks its tab current", async () => {
    await mount("?stage=10&section=items");

    expect(sectionTab("Items")?.getAttribute("aria-current")).toBe("page");
    expect(bodyText()).toContain("Groups, bracket lanes and the teams in their slots.");
    // Items links out instead of editing matches in place.
    expect(
      [...document.querySelectorAll("a")].some(
        (anchor) => anchor.getAttribute("href") === "/admin/tournaments/84/matches/encounters?stage=10"
      )
    ).toBe(true);
  });

  it("falls back to General for a section the stage's format does not have", async () => {
    // Tiebreakers rank a group stage; a double elimination has no standings.
    await mount("?stage=20&section=tiebreakers");

    expect(sectionTab("Tiebreakers")).toBeNull();
    expect(sectionTab("General")?.getAttribute("aria-current")).toBe("page");
    expect(bodyText()).toContain("Bracket preview");
  });
});

describe("Bracket tab · nested entity header", () => {
  it("gives the stage an h2, leaving the hub's h1 the only one on the page", async () => {
    await mount("?stage=10");

    // The stage is an entity inside the tournament hub, so its header is the
    // same kit component one rank down — not a second `<h1>` and not a
    // hand-rolled heading beside the kit.
    expect(container.querySelectorAll("h1")).toHaveLength(0);
    const heading = container.querySelector("h2");
    expect(heading?.textContent).toBe("Groups");
    // The status pill and the metrics still travel with it.
    expect(bodyText()).toContain("Round Robin");
  });
});

describe("Bracket tab · one ConfirmDialog", () => {
  it("deletes a stage through the single confirmation and clears the selection", async () => {
    await mount("?stage=10");

    await click(label("button", "Actions for Groups"));
    await click(named('[role="menuitem"]', "Delete stage")[0]);

    // Exactly one confirmation surface on the screen, carrying this intent.
    const dialogs = document.querySelectorAll('[role="alertdialog"]');
    expect(dialogs).toHaveLength(1);
    const dialog = dialogs[0];
    expect(dialog.textContent).toContain('Delete "Groups"?');
    expect(dialog.textContent).toContain("Generated stage matches");

    await click(named("button", "Delete stage")[0]);

    expect(deleteStage).toHaveBeenCalledWith(10);
    expect(push).toHaveBeenCalledWith("/admin/tournaments/84/bracket");
  });
});
