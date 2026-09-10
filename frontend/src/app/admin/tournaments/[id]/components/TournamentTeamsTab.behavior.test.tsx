// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChallongeTeamSyncPreview } from "@/types/admin.types";
import type { Team } from "@/types/team.types";
import { TournamentTeamsTab } from "./TournamentTeamsTab";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getChallongeTeamSyncPreview = vi.fn();
const syncTeamsFromChallonge = vi.fn();
const replace = vi.fn();
let currentSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: (...args: unknown[]) => replace(...args), push: vi.fn() }),
  usePathname: () => "/admin/tournaments/64/teams",
  useSearchParams: () => currentSearchParams
}));

vi.mock("@/services/admin.service", () => ({
  default: {
    getChallongeTeamSyncPreview: (...args: unknown[]) => getChallongeTeamSyncPreview(...args),
    syncTeamsFromChallonge: (...args: unknown[]) => syncTeamsFromChallonge(...args)
  }
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), info: vi.fn(), apiError: vi.fn() }
}));
// `ui/dialog` localizes its close button, so the tree needs a translator even
// though nothing under test reads a message.
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useLocale: () => "en"
}));

// A mix roster: the Challonge participant name never equals the internal one,
// which is exactly why auto-mapping left these unmapped and why the picker has
// to be searchable rather than an ordered list.
const PREVIEW: ChallongeTeamSyncPreview = {
  teams: [
    { id: 11, name: "PŮPŘƐMŚKIYⅡ2", balancer_name: "pupremskiy" },
    { id: 12, name: "ColdVoice", balancer_name: "coldvoice" },
    { id: 13, name: "litnik", balancer_name: "litnik_main" }
  ],
  participants: [
    {
      participant_id: 289541235,
      challonge_id: 289541235,
      group_id: null,
      group_name: null,
      challonge_tournament_id: 4242,
      name: "litnik team",
      active: true,
      suggested_team_id: null,
      mapped_team_id: null
    }
  ]
};

async function settle() {
  // A macrotask per turn, not a bare microtask: the preview query only starts
  // once the dialog opens, and react-query's own scheduling needs the timer
  // queue drained before the participants row exists.
  for (let turn = 0; turn < 4; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

const mountedRoots: { root: ReturnType<typeof createRoot>; container: HTMLDivElement }[] = [];

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mountedRoots.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <TournamentTeamsTab
          tournamentId={64}
          teams={[] as Team[]}
          stagesCount={1}
          hasChallongeSource
          canCreateTeam
          canUpdateTeam
          canDeleteTeam
          canImportTeams
          canCreatePlayer
          canUpdatePlayer
          canDeletePlayer
        />
      </QueryClientProvider>
    );
  });
  await settle();
  return container;
}

function click(node: Element | null | undefined) {
  if (!node) throw new Error("nothing to click");
  node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}

function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    globalThis.HTMLInputElement.prototype,
    "value"
  )?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function byText(selector: string, text: string) {
  return [...document.querySelectorAll(selector)].find((node) => node.textContent?.includes(text));
}

/** Opens the Teams tab's "Sync teams" dialog, which portals to `document.body`. */
async function openSyncDialog(scope: Element) {
  await act(async () => {
    click(byText("button", "Sync teams"));
  });
  await settle();
  const dialog = document.querySelector("[role='dialog']");
  if (!dialog || scope.contains(dialog)) throw new Error("sync dialog not rendered");
  return dialog;
}

/** The row's internal-team trigger, named by the participant rather than its value. */
function picker() {
  const trigger = document.querySelector<HTMLButtonElement>(
    "[aria-label='Internal team for litnik team']"
  );
  if (!trigger) throw new Error("team picker not rendered");
  return trigger;
}

beforeEach(() => {
  getChallongeTeamSyncPreview.mockReset().mockResolvedValue(PREVIEW);
  syncTeamsFromChallonge
    .mockReset()
    .mockResolvedValue({ success: true, count: 1, created: 1, updated: 0, unchanged: 0, skipped: 0 });
  replace.mockReset();
  currentSearchParams = new URLSearchParams();
});

afterEach(() => {
  for (const mounted of mountedRoots.splice(0)) {
    act(() => mounted.root.unmount());
    mounted.container.remove();
  }
});

describe("Challonge team mapping picker", () => {
  it("starts Unmapped and is named by its participant, not by its value", async () => {
    const scope = await mount();
    await openSyncDialog(scope);

    // Every row renders the same "Unmapped" text, so the visible label cannot
    // identify the control — the aria-label carries the participant.
    expect(picker().textContent).toContain("Unmapped");
  });

  it("finds a team by its balancer name, which the Challonge name never matches", async () => {
    const scope = await mount();
    await openSyncDialog(scope);

    await act(async () => {
      click(picker());
    });
    await settle();

    const search = document.querySelector<HTMLInputElement>("[cmdk-input]");
    if (!search) throw new Error("search field not rendered");

    await act(async () => {
      type(search, "coldvoice");
    });
    await settle();

    const options = [...document.querySelectorAll("[cmdk-item]")].map((node) => node.textContent);
    expect(options.some((label) => label?.includes("ColdVoice"))).toBe(true);
    // A plain list would still be showing every other team.
    expect(options.some((label) => label?.includes("litnik"))).toBe(false);
  });

  it("maps the participant, reads it back on the confirm step and submits that team id", async () => {
    const scope = await mount();
    const dialog = await openSyncDialog(scope);

    await act(async () => {
      click(picker());
    });
    await settle();
    await act(async () => {
      click(byText("[cmdk-item]", "litnik"));
    });
    await settle();

    expect(picker().textContent).toContain("litnik");
    // Step 1 cannot sync: the write is behind a confirm step that shows what
    // it will write, so the mapping table alone must not reach the server.
    expect(byText("button", "Sync mappings")).toBeUndefined();

    await act(async () => {
      click(byText("button", "Continue"));
    });
    await settle();

    const confirmStep = dialog.textContent ?? "";
    expect(confirmStep).toContain("litnik team");
    expect(confirmStep).toContain("litnik");

    await act(async () => {
      click(byText("button", "Sync mappings"));
    });
    await settle();

    expect(syncTeamsFromChallonge).toHaveBeenCalledWith(64, {
      mappings: [{ participant_id: 289541235, group_id: null, team_id: 13 }]
    });
  });

  it("keeps wheel and touch inside the list so it can scroll inside the dialog", async () => {
    // The contract that makes scrolling work at all here: Radix Dialog's
    // react-remove-scroll listens for `wheel`/`touchmove` on `document` and
    // preventDefaults whatever it cannot attribute to the dialog's own subtree.
    // This popover is portalled to `document.body`, so it is not in that subtree —
    // if its events reach `document`, the list stays frozen despite overflowing.
    const scope = await mount();
    await openSyncDialog(scope);

    await act(async () => {
      click(picker());
    });
    await settle();

    const list = document.querySelector("[cmdk-list]");
    if (!list) throw new Error("option list not rendered");

    const reachedDocument: string[] = [];
    const record = (event: Event) => reachedDocument.push(event.type);
    document.addEventListener("wheel", record);
    document.addEventListener("touchmove", record);
    try {
      list.dispatchEvent(new WheelEvent("wheel", { bubbles: true, cancelable: true }));
      list.dispatchEvent(new Event("touchmove", { bubbles: true, cancelable: true }));
    } finally {
      document.removeEventListener("wheel", record);
      document.removeEventListener("touchmove", record);
    }

    expect(reachedDocument).toEqual([]);
  });
});

describe("challongeSync deep link", () => {
  it("opens the mapping dialog and strips the param so a refresh does not reopen it", async () => {
    // The Integrations card links here to clear its "N participants not mapped"
    // failure; the dialog must already be open on arrival.
    currentSearchParams = new URLSearchParams("challongeSync=1&keep=me");
    const scope = await mount();

    const dialog = document.querySelector("[role='dialog']");
    expect(dialog).toBeTruthy();
    expect(scope.contains(dialog)).toBe(false);
    // Unrelated params survive; only the one-shot trigger is dropped.
    expect(replace).toHaveBeenCalledWith("/admin/tournaments/64/teams?keep=me", { scroll: false });
  });

  it("stays closed without the param and rewrites no url", async () => {
    await mount();

    expect(document.querySelector("[role='dialog']")).toBeNull();
    expect(replace).not.toHaveBeenCalled();
  });
});
