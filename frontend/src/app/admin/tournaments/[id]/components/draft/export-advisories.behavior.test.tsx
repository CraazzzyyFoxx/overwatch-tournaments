// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { notify } from "@/lib/notify";
import draftService from "@/services/draft.service";
import type { DraftBoard, DraftSession } from "@/types/draft.types";
import { DraftHistoryPanel } from "./DraftHistoryPanel";
import { LifecycleControls } from "./LifecycleControls";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/lib/datetime/client", () => ({ useFormatter: () => ({ dateTime: () => "Today" }) }));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), warning: vi.fn(), apiError: vi.fn() } }));
vi.mock("@/services/draft.service", () => ({ default: { listSessions: vi.fn(), lifecycle: vi.fn(), exportDraft: vi.fn() } }));
vi.mock("@craazzzyyfoxx/admin-kit/kit/ConfirmDialog", () => ({
  ConfirmDialog: ({ open, onConfirm }: { open: boolean; onConfirm: () => void }) =>
    open ? <button onClick={onConfirm}>Confirm export</button> : null
}));

const session = { id: 7, status: "completed", format: "snake", rounds: 4, created_at: null } as DraftSession;
const advisories = [
  "Alpha: skipped Missing#1234 (not found)",
  "Alpha: team_format_violation: starters_out_of_range"
];
let container: HTMLDivElement;
let root: Root;
let client: QueryClient;

async function settle() {
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
}

async function mount(node: ReactNode) {
  await act(async () => { root.render(<QueryClientProvider client={client}>{node}</QueryClientProvider>); });
  await settle();
}

async function click(label: string) {
  const button = [...container.querySelectorAll("button")].find((item) => item.textContent === label);
  expect(button).toBeDefined();
  await act(async () => { button!.click(); });
  await settle();
}

/** The history row's actions live in a Radix menu, which opens on `pointerdown`. */
async function openRowMenu() {
  const trigger = container.querySelector('button[aria-haspopup="menu"]');
  expect(trigger).not.toBeNull();
  await act(async () => {
    trigger!.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    trigger!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle();
}

function menuItems(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')];
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  vi.mocked(draftService.listSessions).mockResolvedValue([session]);
  vi.mocked(draftService.exportDraft).mockResolvedValue({ ...session, advisories });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

afterEach(async () => {
  await act(async () => root.unmount());
  client.clear();
  container.remove();
});

describe("draft export advisories", () => {
  it.each(["history", "controls"])("shows skipped names and format warnings from %s", async (surface) => {
    await mount(surface === "history"
      ? <DraftHistoryPanel tournamentId={5} />
      : <LifecycleControls tournamentId={5} board={{ session, current_pick: null, picks: [] } as unknown as DraftBoard} />);
    await click("actions.export");
    if (surface === "controls") await click("Confirm export");
    await vi.waitFor(() => expect(notify.warning).toHaveBeenCalled());
    expect(notify.warning).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({
      description: advisories.join("\n"), duration: Infinity
    }));
    expect(notify.success).not.toHaveBeenCalled();
  });

  it("keeps a clean export as a success", async () => {
    vi.mocked(draftService.exportDraft).mockResolvedValue({ ...session, advisories: [] });
    await mount(<DraftHistoryPanel tournamentId={5} />);
    await click("actions.export");
    await vi.waitFor(() => expect(notify.success).toHaveBeenCalled());
    expect(notify.warning).not.toHaveBeenCalled();
  });
});

describe("draft history row actions", () => {
  it("offers delete for a finished session", async () => {
    await mount(<DraftHistoryPanel tournamentId={5} />);
    await openRowMenu();
    expect(menuItems().map((item) => item.textContent?.trim())).toContain("history.delete");
  });

  it("shows delete disabled with its reason while the draft is on the clock", async () => {
    vi.mocked(draftService.listSessions).mockResolvedValue([{ ...session, status: "live" }]);
    await mount(<DraftHistoryPanel tournamentId={5} />);
    await openRowMenu();
    const remove = menuItems().find((item) => item.textContent?.startsWith("history.delete"));
    expect(remove?.hasAttribute("data-disabled")).toBe(true);
    expect(remove?.textContent).toContain("history.cancelFirst");
  });
});

describe("control room pause and resume", () => {
  const paused = { ...session, status: "paused" } as DraftSession;
  const board = { session: paused, current_pick: null, picks: [] } as unknown as DraftBoard;
  const resumeButton = () =>
    [...container.querySelectorAll("button")].find((item) => item.textContent === "actions.resume");

  it("resumes a paused draft in one click", async () => {
    // The session's own lifecycle: it answers for this session alone, whichever tournament it sits in.
    vi.mocked(draftService.lifecycle).mockImplementation(async (sessionId, action) => {
      if (sessionId !== paused.id || action !== "resume") throw new Error("no such session action");
      return { ...paused, status: "live" };
    });
    await mount(<LifecycleControls tournamentId={5} board={board} />);
    await click("actions.resume");
    await vi.waitFor(() => expect(notify.success).toHaveBeenCalledWith("lifecycleSuccess"));
    expect(notify.apiError).not.toHaveBeenCalled();
  });

  it("keeps Resume visible but disabled, with the reason, while the roles are infeasible", async () => {
    await mount(<LifecycleControls tournamentId={5} board={board} resumeBlocked />);
    const button = resumeButton();
    expect(button?.disabled).toBe(true);
    const reason = document.getElementById(button!.getAttribute("aria-describedby")!);
    expect(reason?.textContent).toBe("resumeBlocked");
  });
});
