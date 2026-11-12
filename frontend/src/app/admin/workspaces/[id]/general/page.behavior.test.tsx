// @vitest-environment happy-dom
//
// The superuser shell. Each section is implemented once and mounted twice, and
// the only difference is where the workspace id comes from: this route reads it
// from the path (workspace 8), `/admin/settings/*` reads the current workspace
// out of the store. If the two ever diverge, a superuser opening someone
// else's workspace would silently edit their own.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@craazzzyyfoxx/admin-kit/ui/tooltip";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { Workspace } from "@/types/workspace.types";
import GeneralSettingsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getById = vi.fn();
const getOwner = vi.fn();
const setOwner = vi.fn();
const update = vi.fn();

vi.mock("@/services/workspace.service", () => ({
  default: {
    getById: (...args: unknown[]) => getById(...args),
    getOwner: (...args: unknown[]) => getOwner(...args),
    setOwner: (...args: unknown[]) => setOwner(...args),
    update: (...args: unknown[]) => update(...args),
    uploadIcon: vi.fn(),
    deleteIcon: vi.fn()
  }
}));

const GAMES = [
  { code: "overwatch", name: "Overwatch", enabled: true, capabilities: { native_ladder: true } },
  { code: "lol", name: "League of Legends", enabled: false, capabilities: { native_ladder: true } }
] as DisciplineDescriptor[];

const listGames = vi.fn();
vi.mock("@/services/discipline.service", () => ({
  default: { list: (...args: unknown[]) => listGames(...args) }
}));

// The drop is what the games list pins, not dnd-kit's pointer maths (which would
// also load a second React copy under pnpm): the kit reports a reorder as the new
// array and the dragged item, and that is what gets replayed here.
let drop: ((next: DisciplineDescriptor[], moved: DisciplineDescriptor) => void) | undefined;
vi.mock("@/components/kit/SortableRows", () => ({
  SortableRows: ({
    items,
    onReorder,
    children
  }: {
    items: readonly DisciplineDescriptor[];
    onReorder: (next: DisciplineDescriptor[], moved: DisciplineDescriptor) => void;
    children: (item: DisciplineDescriptor, index: number) => ReactNode;
  }) => {
    drop = onReorder;
    return <div>{items.map((item, index) => children(item, index))}</div>;
  },
  useSortableRow: () => ({ ref: () => {}, style: {}, handleProps: {}, isDragging: false }),
  SortableGrip: ({ label }: { label: string }) => <button type="button" aria-label={label} />
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "8" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })
}));

let superuser = true;
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    isLoaded: true,
    isSuperuser: superuser,
    // A superuser is the only caller of this route who is not a member of the
    // workspace it names, so the membership grant must not be what lets them in.
    isWorkspaceAdmin: () => false,
    canAccessPermission: () => true
  })
}));

vi.mock("@/components/kit/AuditTrailSheet", () => ({ AuditTrailButton: () => null }));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), apiError: vi.fn() }
}));

vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (
    selector: (state: { currentWorkspaceId: number; fetchWorkspaces: () => void }) => unknown
  ) => selector({ currentWorkspaceId: 1, fetchWorkspaces: vi.fn() })
}));

const OTHER_WORKSPACE: Workspace = {
  id: 8,
  slug: "rivals",
  name: "Rivals Cup",
  description: "Someone else's league",
  icon_url: null,
  is_active: true,
  is_hidden: false,
  timezone: "UTC",
  branding_enabled: false,
  brand_primary: null,
  brand_secondary: null,
  brand_background: null,
  brand_surface: null,
  brand_accent: null,
  brand_foreground: null,
  brand_muted: null,
  brand_border: null,
  brand_ring: null,
  brand_destructive: null,
  subdomain: null,
  seo_title: null,
  seo_description: null,
  custom_domain: null,
  custom_domain_verified_at: null,
  custom_domain_verification_token: null,
  discord_guild_id: null,
  discord_guild_verified_at: null,
  verification_status: "unverified",
  disciplines_enabled: ["overwatch"],
  default_division_grid_versions: {},
  effective_division_grid_versions: {},
  newcomer_scope: "workspace"
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
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
      >
        {/* The admin layout mounts one; the tier glyph's tooltip needs it. */}
        <TooltipProvider>
          <GeneralSettingsPage />
        </TooltipProvider>
      </QueryClientProvider>
    );
  });
  await settle();
}

beforeEach(() => {
  superuser = true;
  getById.mockReset().mockResolvedValue(OTHER_WORKSPACE);
  getOwner.mockReset().mockResolvedValue({
    auth_user_id: 3,
    username: "ada",
    email: "ada@example.com",
    first_name: null,
    last_name: null,
    avatar_url: null
  });
  setOwner.mockReset().mockResolvedValue(null);
  update.mockReset().mockResolvedValue(OTHER_WORKSPACE);
  drop = undefined;
  listGames.mockReset().mockResolvedValue(GAMES);
});

async function click(node: Element | undefined) {
  await act(async () => {
    node?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle();
}

const gameSwitch = (name: string) =>
  container.querySelector<HTMLButtonElement>(`[role="switch"][aria-label="Enable ${name}"]`);

const saveButton = () =>
  [...container.querySelectorAll("button")].find((node) => node.textContent?.trim() === "Save changes");

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("Workspaces › [id] › General", () => {
  it("edits the workspace named in the route, not the one in the picker", async () => {
    await render();

    expect(getById).toHaveBeenCalledWith(8);
    expect(container.querySelector<HTMLInputElement>("#workspace-name")?.value).toBe("Rivals Cup");
  });

  // The owner is the one field on this screen the public workspace payload
  // cannot carry, so it is fetched separately — and it has to be fetched for
  // the workspace in the route, like everything else here.
  it("names the account accountable for the workspace in the route", async () => {
    await render();

    expect(getOwner).toHaveBeenCalledWith(8);
    expect(container.textContent).toContain("@ada");
    expect(container.textContent).toContain("ada@example.com");
  });

  it("says so when no owner is stamped", async () => {
    getOwner.mockResolvedValue(null);
    await render();

    expect(container.textContent).toContain("No owner recorded");
  });

  // The reassignment control is superuser-only and writes through its own
  // endpoint, so "Remove owner" is the one branch reachable without driving the
  // account picker: it must send an explicit null, not just drop the field.
  it("lets a superuser drop the accountability stamp in one click", async () => {
    await render();
    const clear = [...container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Remove owner"
    );

    expect(container.querySelector("#workspace-owner")).not.toBeNull();
    expect(clear).toBeDefined();

    await act(async () => {
      clear?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(setOwner).toHaveBeenCalledWith(8, null);
    expect(container.textContent).toContain("No owner recorded");
  });

  it("refuses a caller who neither owns the platform nor administers workspace 8", async () => {
    superuser = false;
    await render();

    expect(container.textContent).toContain("Not your workspace");
    expect(container.querySelector("#workspace-name")).toBeNull();
  });

  // A brand-new organiser has no other way to learn why their workspace is
  // nowhere on the home page, so this notice is the whole explanation — and it
  // has to disappear the moment it stops being true.
  it("explains that an unverified workspace is not listed on the home page yet", async () => {
    getById.mockResolvedValue({ ...OTHER_WORKSPACE, verification_status: "unverified" });
    await render();

    expect(container.textContent).toContain("Not listed on the home page yet");
  });

  it.each(["verified", "trusted"] as const)("drops the notice once the workspace is %s", async (status) => {
    getById.mockResolvedValue({ ...OTHER_WORKSPACE, verification_status: status });
    await render();

    expect(container.querySelector("#workspace-name")).not.toBeNull();
    expect(container.textContent).not.toContain("Not listed on the home page yet");
  });

  it("keeps the tier control to superusers", async () => {
    superuser = false;
    getById.mockResolvedValue({ ...OTHER_WORKSPACE, verification_status: "trusted" });
    await render();
    expect(container.querySelector("#workspace-verification")).toBeNull();

    superuser = true;
    await act(async () => root.unmount());
    container.remove();
    await render();
    expect(container.querySelector("#workspace-verification")).not.toBeNull();
  });

  // The games list is the one field whose ORDER is data: `[0]` is what a
  // tournament or grid gets when no game is named. So a pure reorder must be a
  // change the save bar sees, and the server must receive the list as dragged.
  describe("games", () => {
    it("switches a game on by appending it, and never lets the last one off", async () => {
      await render();

      expect(gameSwitch("Overwatch")?.getAttribute("aria-checked")).toBe("true");
      expect(gameSwitch("Overwatch")?.disabled).toBe(true);
      expect(gameSwitch("League of Legends")?.getAttribute("aria-checked")).toBe("false");
      expect(saveButton()).toBeUndefined();

      await click(gameSwitch("League of Legends"));
      expect(gameSwitch("League of Legends")?.getAttribute("aria-checked")).toBe("true");
      // Two enabled: either may go now.
      expect(gameSwitch("Overwatch")?.disabled).toBe(false);

      await click(saveButton());
      expect(update).toHaveBeenCalledWith(8, { disciplines_enabled: ["overwatch", "lol"] });
    });

    it("saves a drag that only reorders, with the dragged-first game as the default", async () => {
      getById.mockResolvedValue({ ...OTHER_WORKSPACE, disciplines_enabled: ["overwatch", "lol"] });
      await render();
      expect(saveButton()).toBeUndefined();

      const [overwatch, lol] = GAMES;
      await act(async () => drop?.([lol, overwatch], lol));
      await settle();

      const rows = [...container.querySelectorAll('[aria-label^="Reorder "]')].map((grip) =>
        grip.getAttribute("aria-label")
      );
      expect(rows).toEqual(["Reorder League of Legends", "Reorder Overwatch"]);
      expect(gameSwitch("League of Legends")?.parentElement?.textContent).toContain("Default");
      expect(gameSwitch("Overwatch")?.parentElement?.textContent).not.toContain("Default");

      await click(saveButton());
      expect(update).toHaveBeenCalledWith(8, { disciplines_enabled: ["lol", "overwatch"] });
    });

    // The scope pill and the game tabs list the community's games in this order: a save re-reads them.
    it("re-reads the community's games after a save", async () => {
      await render();
      const reads = listGames.mock.calls.filter(([axis]) => axis === 8).length;

      await click(gameSwitch("League of Legends"));
      await click(saveButton());
      expect(update).toHaveBeenCalledWith(8, { disciplines_enabled: ["overwatch", "lol"] });
      expect(listGames.mock.calls.filter(([axis]) => axis === 8).length).toBeGreaterThan(reads);
    });
  });
});
