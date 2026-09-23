// @vitest-environment happy-dom
//
// One settings section, and the two claims every one of the eleven makes:
//
//   1. the section gate is the PAGE's, not the rail's. Hiding a link is not
//      access control — `/settings/general` typed into the address bar has to
//      be refused too;
//   2. a section PATCHes its own changed fields and nothing else. The
//      pre-redesign form sent every field it held on every save, so renaming a
//      tournament recorded a full rewrite of its rules, schedule and scoring in
//      the audit trail (`model_dump(exclude_unset=True)` records exactly the
//      keys a PATCH sends).
//
// The branding block below is the exception to claim 2 and has its own
// describe: the cover and the logo are multipart uploads to their own
// endpoint, they apply immediately, and nothing in the save-bar flow covers
// them.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Tournament } from "@/types/tournament.types";
import { getTournamentWorkspaceQueryKeys } from "@/lib/tournament/workspace-query-keys";
import GeneralSettingsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getTournament = vi.fn();
const updateTournament = vi.fn();
const setTournamentSchedule = vi.fn();
const uploadTournamentImage = vi.fn();
const deleteTournamentImage = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getTournament: (...args: unknown[]) => getTournament(...args),
    updateTournament: (...args: unknown[]) => updateTournament(...args),
    setTournamentSchedule: (...args: unknown[]) => setTournamentSchedule(...args),
    uploadTournamentImage: (...args: unknown[]) => uploadTournamentImage(...args),
    deleteTournamentImage: (...args: unknown[]) => deleteTournamentImage(...args)
  }
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "64" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() })
}));

let canUpdateTournament = true;
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    isLoaded: true,
    canAccessPermission: (permission: string) =>
      permission === "tournament.update" ? canUpdateTournament : true
  })
}));

// The audit drawer is the admin's, not this section's: it has its own tests and
// its own permission, and mounting it here would only add a count query.
vi.mock("@/components/kit/AuditTrailSheet", () => ({ AuditTrailButton: () => null }));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), info: vi.fn(), apiError: vi.fn() }
}));

vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { workspaces: unknown[] }) => unknown) =>
    selector({ workspaces: [] })
}));

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key
}));

const TOURNAMENT: Tournament = {
  id: 64,
  created_at: new Date("2026-01-01T00:00:00Z"),
  updated_at: null,
  workspace_id: 1,
  name: "OWT 64",
  slug: "owt-64",
  start_date: new Date("2026-04-18T00:00:00Z"),
  end_date: new Date("2026-04-19T00:00:00Z"),
  description: null,
  challonge_id: null,
  challonge_slug: "owt-64",
  is_league: false,
  is_finished: false,
  is_hidden: false,
  team_formation: "balancer",
  status: "live",
  auto_transitions_enabled: true,
  allow_late_registration: false,
  phase_schedule: [],
  win_points: 3,
  draw_points: 1,
  loss_points: 0,
  stages: [],
  participants_count: 20,
  registrations_count: 20,
  teams_count: 20,
  division_grid_version_id: null,
  division_grid_version: null,
  cover_image_url: null,
  logo_url: null
};

let container: HTMLDivElement;
let root: Root;
let client: QueryClient;

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
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <GeneralSettingsPage />
      </QueryClientProvider>
    );
  });
  await settle();
}

/** Type into a controlled input the way React's synthetic layer sees it. */
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

function button(label: string) {
  return [...document.querySelectorAll("button")].find(
    (node) => node.textContent?.trim() === label
  );
}

/**
 * The two image editors are told apart by their captions, not by document
 * order: reordering the cards must not silently repoint a case at the other
 * slot, which is the very mix-up the first branding case exists to catch.
 */
function slot(caption: "Cover banner" | "Logo") {
  const label = [...container.querySelectorAll("span")].find(
    (node) => node.textContent?.trim() === caption
  );
  const column = label?.parentElement ?? null;
  return {
    file: column?.querySelector<HTMLInputElement>('input[type="file"]') ?? null,
    remove: column?.querySelector<HTMLButtonElement>('button[aria-label="Remove image"]') ?? null
  };
}

function image(name: string) {
  return new File(["binary"], name, { type: "image/png" });
}

/** Pick a file the way React's synthetic change layer sees the picker. */
async function pick(input: HTMLInputElement, file: File) {
  await act(async () => {
    input.files = [file] as unknown as FileList;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await settle();
}

async function click(node: HTMLElement) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle();
}

beforeEach(() => {
  canUpdateTournament = true;
  getTournament.mockReset().mockResolvedValue(TOURNAMENT);
  updateTournament.mockReset().mockResolvedValue(TOURNAMENT);
  setTournamentSchedule.mockReset().mockResolvedValue(undefined);
  uploadTournamentImage.mockReset().mockResolvedValue(TOURNAMENT);
  deleteTournamentImage.mockReset().mockResolvedValue(TOURNAMENT);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("Settings › General", () => {
  it("refuses the section to a caller without tournament.update", async () => {
    canUpdateTournament = false;
    await render();

    expect(container.textContent).toContain("Not permitted");
    expect(container.querySelector("#settings-name")).toBeNull();
    // The branding editors are behind the same grant: a refused section must
    // not leave an upload surface behind, and no request may go out from it.
    expect(container.querySelectorAll('input[type="file"]').length).toBe(0);
    expect(container.querySelectorAll('button[aria-label="Remove image"]').length).toBe(0);
    expect(uploadTournamentImage).not.toHaveBeenCalled();
    expect(deleteTournamentImage).not.toHaveBeenCalled();
  });

  it("keeps the save bar away until something actually changed", async () => {
    await render();

    expect(container.querySelector<HTMLInputElement>("#settings-name")?.value).toBe("OWT 64");
    expect(container.querySelector('[aria-label="unsavedChanges"]')).toBeNull();
  });

  it("PATCHes the edited field alone, and never the schedule", async () => {
    await render();

    await type(container.querySelector<HTMLInputElement>("#settings-name")!, "OWT 65");
    // `next-intl` is mocked to the identity here (house convention for admin
    // behavior tests), so `SaveBar`'s own copy renders as its message keys.
    expect(container.querySelector('[aria-label="unsavedChanges"]')?.textContent).toContain(
      "1 changed field"
    );

    await act(async () => {
      button("save")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(updateTournament).toHaveBeenCalledTimes(1);
    // The whole point: `slug`, `description`, the scoring, the roster shape and
    // every other field of the tournament stay out of the request.
    expect(updateTournament).toHaveBeenCalledWith(64, { name: "OWT 65" });
    expect(setTournamentSchedule).not.toHaveBeenCalled();
  });

  it("discards back to the stored values", async () => {
    await render();

    await type(container.querySelector<HTMLInputElement>("#settings-name")!, "typo");
    await act(async () => {
      button("discard")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(container.querySelector<HTMLInputElement>("#settings-name")?.value).toBe("OWT 64");
    expect(updateTournament).not.toHaveBeenCalled();
  });
});

describe("Settings › General › Branding", () => {
  it("uploads to the slot whose editor was used, and not the other one", async () => {
    await render();
    const cover = image("cover.png");
    const logo = image("logo.png");

    await pick(slot("Cover banner").file!, cover);

    expect(uploadTournamentImage).toHaveBeenCalledTimes(1);
    expect(uploadTournamentImage).toHaveBeenCalledWith(64, "cover", cover);

    await pick(slot("Logo").file!, logo);

    expect(uploadTournamentImage).toHaveBeenCalledTimes(2);
    expect(uploadTournamentImage).toHaveBeenLastCalledWith(64, "logo", logo);
    // Spelled out because the failure mode is silent: a swapped slot overwrites
    // the other image in S3 and looks exactly like a successful upload.
    expect(uploadTournamentImage).not.toHaveBeenCalledWith(64, "cover", logo);
    expect(uploadTournamentImage).not.toHaveBeenCalledWith(64, "logo", cover);
  });

  it("offers the delete only for the slot that has an image", async () => {
    getTournament.mockResolvedValue({
      ...TOURNAMENT,
      cover_image_url: "https://s3.example/cover.png",
      logo_url: null
    } satisfies Tournament);
    await render();

    expect(container.querySelectorAll('button[aria-label="Remove image"]').length).toBe(1);
    expect(slot("Logo").remove).toBeNull();

    await click(slot("Cover banner").remove!);

    expect(deleteTournamentImage).toHaveBeenCalledTimes(1);
    expect(deleteTournamentImage).toHaveBeenCalledWith(64, "cover");
  });

  it("invalidates the tournament everywhere it is read once the upload lands", async () => {
    await render();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    await pick(slot("Cover banner").file!, image("cover.png"));

    const invalidated = invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
    const keys = getTournamentWorkspaceQueryKeys(64);
    // The admin hub's own copy, and the public tournament page that renders the
    // same cover — refreshing only the first leaves the old banner up there.
    expect(invalidated).toContain(JSON.stringify(keys.tournament));
    expect(invalidated).toContain(JSON.stringify(keys.publicTournament));
  });
});
