// @vitest-environment happy-dom
//
// Registration › Sheets feed. What is pinned here:
//   1. the save affordance is the shared `SaveBar`: absent while clean, so a
//      tournament with no feed does not carry a permanently disabled button;
//   2. the first edit of the URL is what makes "Create feed" appear — the same
//      moment a save could first succeed;
//   3. Discard puts the source fields back to the saved feed and hides the bar;
//   4. the roles targets are grouped, and the value maps speak, by the TOURNAMENT'S OWN roles — League's five
//      positions, not a fixed tank/damage/support.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NextIntlClientProvider } from "next-intl";

import en from "@/i18n/messages/en.json";
import type { AdminGoogleSheetFeed, MappingCatalog } from "@/types/balancer-admin.types";
import SheetsFeedPage from "./SheetsFeedPage";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getTournamentSheet = vi.fn();
const getPublicOverview = vi.fn();
const getTournamentSheetMappingCatalog = vi.fn();
const upsertTournamentSheetWithValidation = vi.fn();

vi.mock("@/services/balancer-admin.service", () => ({
  default: {
    getTournamentSheet: (...args: unknown[]) => getTournamentSheet(...args),
    getTournamentSheetMappingCatalog: (...args: unknown[]) =>
      getTournamentSheetMappingCatalog(...args),
    upsertTournamentSheetWithValidation: (...args: unknown[]) =>
      upsertTournamentSheetWithValidation(...args),
    syncTournamentSheet: vi.fn(),
    suggestTournamentSheetMapping: vi.fn(),
    previewTournamentSheetMappingRows: vi.fn()
  }
}));

vi.mock("@/services/tournament.service", () => ({
  default: { getPublicOverview: (...args: unknown[]) => getPublicOverview(...args) }
}));

vi.mock("@/services/discipline.service", async () => (await import("@/test/discipline-metadata")).disciplineServiceMock);

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() })
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), info: vi.fn(), apiError: vi.fn() }
}));

const CATALOG: MappingCatalog = {
  targets: [
    {
      // One identity target per provider, and Battle.net's is a LIST: the main
      // tag and the smurfs land in the same answer. The parser ids below name
      // the VALUE FORMAT a column is read in, not the field.
      key: "identity_battlenet",
      label: "BattleTag",
      group: "identity",
      accepted_parsers: ["battle_tag", "battle_tag_list"],
      default_parser: "battle_tag",
      default_mode: "columns",
      default_is_list: true,
      multi_column: true,
      required: true
    }
  ],
  parsers: [
    { parser: "battle_tag", label: "BattleTag", cardinality: "single", produces: "string" },
    { parser: "battle_tag_list", label: "BattleTag list", cardinality: "multi", produces: "string" }
  ],
  value_categories: [],
  custom_fields: [],
  header_keys: ["BattleTag"]
};

const FEED: AdminGoogleSheetFeed = {
  id: 3,
  tournament_id: 95,
  source_url: "https://docs.google.com/spreadsheets/d/abc",
  sheet_id: "abc",
  gid: null,
  title: "Season 9",
  header_row_json: ["BattleTag"],
  mapping_config_json: null,
  value_mapping_json: null,
  auto_sync_enabled: false,
  auto_sync_interval_seconds: 300,
  last_synced_at: null,
  last_sync_status: null,
  last_error: null
};

let container: HTMLDivElement;
let root: Root;

async function settle(times = 4) {
  for (let turn = 0; turn < times; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function render() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
        >
          <SheetsFeedPage tournamentId={95} registrationNodeId={7} />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
}

async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      globalThis.HTMLInputElement.prototype,
      "value"
    )?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(2);
}

function saveBar() {
  return container.querySelector('[aria-label="Unsaved changes"]');
}

function button(label: string) {
  return [...container.querySelectorAll("button")].find(
    (node) => node.textContent?.trim() === label
  );
}

function urlInput() {
  return container.querySelector<HTMLInputElement>("#sheet-url")!;
}

beforeEach(() => {
  getTournamentSheet.mockReset();
  getTournamentSheetMappingCatalog.mockReset().mockResolvedValue(CATALOG);
  upsertTournamentSheetWithValidation.mockReset();
  getPublicOverview.mockReset().mockResolvedValue({ id: 95, workspace_id: 3, discipline: "overwatch" });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("Sheets feed › save bar", () => {
  it("has no save affordance until the first edit, then offers Create feed", async () => {
    getTournamentSheet.mockResolvedValue(null);
    await render();

    expect(saveBar()).toBeNull();
    expect(button("Create feed")).toBeUndefined();

    await type(urlInput(), "https://docs.google.com/spreadsheets/d/new");

    expect(saveBar()).not.toBeNull();
    expect(button("Create feed")).toBeDefined();
    expect(button("Save changes")).toBeUndefined();
  });

  it("labels the bar Save changes for an existing feed and Discard restores the source", async () => {
    getTournamentSheet.mockResolvedValue(FEED);
    await render();

    expect(saveBar()).toBeNull();
    const title = container.querySelector<HTMLInputElement>("#sheet-title")!;
    expect(title.value).toBe("Season 9");

    await type(title, "Renamed");
    expect(button("Save changes")).toBeDefined();

    await act(async () => {
      button("Discard")!.click();
    });
    await settle(2);

    expect(saveBar()).toBeNull();
    expect(container.querySelector<HTMLInputElement>("#sheet-title")!.value).toBe("Season 9");
  });

  it("saves through the bar with the edited source", async () => {
    getTournamentSheet.mockResolvedValue(FEED);
    upsertTournamentSheetWithValidation.mockResolvedValue({ ok: true, feed: FEED });
    await render();

    await type(urlInput(), "https://docs.google.com/spreadsheets/d/moved");
    await act(async () => {
      button("Save changes")!.click();
    });
    await settle(2);

    expect(upsertTournamentSheetWithValidation).toHaveBeenCalledWith(
      95,
      expect.objectContaining({ source_url: "https://docs.google.com/spreadsheets/d/moved" })
    );
  });
});

describe("Sheets feed › the tournament's own roles", () => {
  const LEAGUE_CATALOG: MappingCatalog = {
    ...CATALOG,
    targets: [
      ...CATALOG.targets,
      { key: "source_roles.primary", label: "Primary role", group: "roles", accepted_parsers: ["role_token"], default_parser: "role_token", default_mode: "columns", default_is_list: false, multi_column: false, required: false },
      ...["top", "jungle", "mid"].flatMap((code) =>
        ["rank_value", "subrole"].map((field) => ({
          key: `roles.${code}.${field}`,
          label: `${code} ${field}`,
          group: "roles" as const,
          accepted_parsers: ["integer"],
          default_parser: "integer",
          default_mode: "columns",
          default_is_list: false,
          multi_column: false,
          required: false
        }))
      ),
      { key: "is_flex", label: "Full flex", group: "roles", accepted_parsers: ["boolean"], default_parser: "boolean", default_mode: "columns", default_is_list: false, multi_column: false, required: false }
    ],
    subrole_catalog: { top: [], jungle: [], mid: [] }
  };

  it("groups the roles targets by the owner's roles, in the game's order, named by the game", async () => {
    getPublicOverview.mockResolvedValue({ id: 95, workspace_id: 3, discipline: "lol" });
    getTournamentSheetMappingCatalog.mockResolvedValue(LEAGUE_CATALOG);
    getTournamentSheet.mockResolvedValue(FEED);
    await render();

    await act(async () => {
      button("Roles")!.click();
    });
    await settle(2);

    const headings = [...container.querySelectorAll("div")]
      .filter((node) => node.className.includes("bg-muted/40"))
      .map((node) => node.textContent);
    expect(headings).toEqual(["Declared roles", "Top", "Jungle", "Mid", "Other"]);
    expect(container.textContent).not.toMatch(/Tank|Damage/);
  });

  it("offers the owner's roles when a sheet's role text is mapped", async () => {
    getPublicOverview.mockResolvedValue({ id: 95, workspace_id: 3, discipline: "lol" });
    getTournamentSheetMappingCatalog.mockResolvedValue(CATALOG);
    getTournamentSheet.mockResolvedValue({
      ...FEED,
      value_mapping_json: { roles: { "лес": "jungle" } }
    });
    await render();

    // The saved row resolves its role against League's dictionary, by name.
    expect(container.textContent).toContain("Jungle");
    expect(container.textContent).not.toMatch(/Tank|Damage/);
  });
});
