// @vitest-environment happy-dom
//
// The scrims index. Two rules are easy to break and invisible to type-checking:
// the scope switch is staff-only AND must actually re-query, and the Close
// button follows the server's `can_close` rather than "do I captain a side" —
// the rule that used to hide Close from a creator who plays neither side.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { ScrimRoom } from "@/types/scrim.types";

import ScrimsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const WORKSPACE_ID = 3;

const listRooms = vi.fn();
const closeRoom = vi.fn();
let isStaff = false;
let statsScope: "all" | "workspace" = "workspace";
let hostLockedWorkspaceId: number | null = null;

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));
vi.mock("@/hooks/useAuthProfile", () => ({
  useAuthProfile: () => ({
    status: "authenticated",
    user: { id: 7, isSuperuser: false, workspaces: [{ workspace_id: 3 }, { workspace_id: 4 }] }
  })
}));
vi.mock("@/stores/auth-modal.store", () => ({
  useAuthModalStore: (selector: (s: unknown) => unknown) => selector({ open: vi.fn() })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (s: unknown) => unknown) =>
    selector({
      currentWorkspaceId: WORKSPACE_ID,
      statsScope,
      hostLockedWorkspaceId,
      isLoading: false,
      workspaces: [{ id: 3, name: "Community A" }, { id: 4, name: "Community B" }]
    })
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    hasWorkspacePermission: (workspaceId: number, permission: string) =>
      isStaff && workspaceId === WORKSPACE_ID && permission === "match.result"
  })
}));
vi.mock("@/services/scrim.service", () => ({
  default: {
    listRooms: (...args: unknown[]) => listRooms(...args),
    closeRoom: (...args: unknown[]) => closeRoom(...args)
  }
}));
// The create dialog drags in the tournament lookup; the page's own behaviour is
// what is under test.
vi.mock("./_components/ScrimCreateDialog", () => ({
  ScrimCreateDialog: () => null
}));

function room(overrides: Partial<ScrimRoom> = {}): ScrimRoom {
  return {
    id: 1,
    token: "tok1",
    label: "Alpha vs Bravo",
    workspace_id: WORKSPACE_ID,
    tournament_id: 9,
    stage_id: 11,
    encounter_id: 500,
    best_of: 3,
    home_team: { id: 700, name: "Alpha", captain_claimed: true },
    away_team: { id: 701, name: "Bravo", captain_claimed: true },
    viewer_side: null,
    can_claim: false,
    can_close: false,
    created_at: "2026-08-12T00:00:00Z",
    closed_at: null,
    ...overrides
  };
}

const cleanup: Array<() => void> = [];
afterEach(() => {
  for (const unmount of cleanup.splice(0)) act(unmount);
});

async function mount(): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  cleanup.push(() => { root.unmount(); client.clear(); container.remove(); });

  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
        <QueryClientProvider client={client}>
          <ScrimsPage />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
  return container;
}

async function settle(): Promise<void> {
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
}

function buttonWith(container: HTMLElement, text: string): HTMLElement | undefined {
  return [...container.querySelectorAll<HTMLElement>("button")].find((node) =>
    node.textContent?.includes(text)
  );
}

beforeEach(() => {
  isStaff = false;
  statsScope = "workspace";
  hostLockedWorkspaceId = null;
  listRooms.mockReset().mockResolvedValue({ rooms: [room()] });
  closeRoom.mockReset().mockResolvedValue(room({ closed_at: "2026-08-12T02:00:00Z" }));
  document.body.innerHTML = "";
});

describe("scrims page", () => {
  it("asks for the viewer's own rooms and offers no scope switch to a non-staff member", async () => {
    const container = await mount();

    expect(listRooms).toHaveBeenCalledWith(WORKSPACE_ID, "mine");
    expect(container.querySelector('[role="radiogroup"]')).toBeNull();
  });

  it("lets staff switch the query to the whole workspace", async () => {
    isStaff = true;
    const container = await mount();

    expect(listRooms).toHaveBeenCalledWith(WORKSPACE_ID, "mine");
    const group = container.querySelector('[role="radiogroup"]');
    expect(group).not.toBeNull();

    const workspaceSegment = buttonWith(container, en.scrims.list.scopeWorkspace);
    expect(workspaceSegment).toBeDefined();
    await act(async () => {
      workspaceSegment?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(listRooms).toHaveBeenCalledWith(WORKSPACE_ID, "workspace");
  });

  it("lists both communities without extending A's staff grant to B", async () => {
    statsScope = "all";
    isStaff = true;
    listRooms.mockImplementation(async (workspaceId: number) => ({
      rooms: [room({ id: workspaceId, workspace_id: workspaceId, label: `Room ${workspaceId}` })]
    }));
    const container = await mount();
    expect(container.textContent).toContain("Community A");
    expect(container.textContent).toContain("Community B");
    expect(container.textContent).toContain("Room 3");
    expect(container.textContent).toContain("Room 4");

    await act(async () => {
      buttonWith(container, en.scrims.list.scopeWorkspace)?.dispatchEvent(
        new MouseEvent("click", { bubbles: true })
      );
    });
    await settle();

    expect(listRooms).toHaveBeenCalledWith(3, "workspace");
    expect(listRooms).toHaveBeenCalledWith(4, "mine");
    expect(listRooms).not.toHaveBeenCalledWith(4, "workspace");
  });

  it("keeps a tenant's lists local even with a stale all preference", async () => {
    statsScope = "all";
    hostLockedWorkspaceId = 3;
    await mount();
    expect(listRooms).toHaveBeenCalledWith(3, "mine");
    expect(listRooms).not.toHaveBeenCalledWith(4, "mine");
  });

  it("renders a failed community read as an error, not an empty successful list", async () => {
    statsScope = "all";
    listRooms.mockRejectedValue(new Error("Forbidden"));
    const container = await mount();
    expect(buttonWith(container, en.scrims.list.retry)).toBeDefined();
    expect(container.textContent).not.toContain(en.scrims.list.emptyTitle);
  });

  it("shows Close from can_close, not from captaining a side", async () => {
    // The regression: a creator (or staff) who plays neither side gets the
    // button, a bystander does not.
    listRooms.mockResolvedValue({ rooms: [room({ id: 1, can_close: true })] });
    const container = await mount();

    const close = buttonWith(container, en.scrims.list.close);
    expect(close).toBeDefined();
    await act(async () => {
      close?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(closeRoom).toHaveBeenCalledWith("tok1");
  });

  it("hides Close when the server says the viewer may not close", async () => {
    listRooms.mockResolvedValue({ rooms: [room({ viewer_side: "home", can_close: false })] });
    const container = await mount();

    expect(buttonWith(container, en.scrims.list.close)).toBeUndefined();
  });
});
