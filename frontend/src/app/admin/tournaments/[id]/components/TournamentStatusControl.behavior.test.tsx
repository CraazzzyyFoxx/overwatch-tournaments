// @vitest-environment happy-dom
//
// Hub header status action. What is pinned here:
//  1. the status is derived, so the only thing an admin sets is `archived`: Archive on a completed tournament,
//     Unarchive on an archived one, nothing in any other status;
//  2. it confirms before it calls `setArchived`;
//  3. without `tournament.update` nothing renders.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Tournament } from "@/types/tournament.types";
import { TournamentStatusControl } from "./TournamentStatusControl";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const setArchived = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: { setArchived: (...args: unknown[]) => setArchived(...args) }
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn() } }));
vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  // `vi.mock` factories are hoisted above static imports, so the messages load here.
  const { default: en } = await import("@/i18n/messages/en.json");
  return {
    ...actual,
    useTranslations: (namespace?: string) =>
      actual.createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
    useLocale: () => "en"
  };
});

const tournament = (status: Tournament["status"]) => ({ id: 7, status }) as Tournament;
const mounted: Root[] = [];

async function mount(subject: Tournament, canUpdate = true) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mounted.push(root);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <TournamentStatusControl tournament={subject} canUpdate={canUpdate} />
      </QueryClientProvider>
    );
  });
  return container;
}

async function press(node: Element | null | undefined) {
  if (!node) throw new Error("nothing to press");
  await act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function button(text: string) {
  return [...document.querySelectorAll("button")].find((node) => node.textContent?.trim() === text);
}

beforeEach(() => {
  setArchived.mockReset().mockResolvedValue(tournament("archived"));
});

afterEach(async () => {
  await act(async () => {
    for (const root of mounted.splice(0)) root.unmount();
  });
  document.body.innerHTML = "";
});

describe("TournamentStatusControl", () => {
  it("archives a completed tournament, behind a confirmation", async () => {
    await mount(tournament("completed"));

    await press(button("Archive"));
    expect(setArchived).not.toHaveBeenCalled();

    const dialog = document.querySelector("[role='alertdialog']");
    expect(dialog?.textContent).toContain("Archive the tournament?");
    await press([...(dialog?.querySelectorAll("button") ?? [])].find((node) => node.textContent === "Archive"));
    expect(setArchived).toHaveBeenCalledWith(7, true);
  });

  it("unarchives an archived tournament", async () => {
    await mount(tournament("archived"));

    expect(button("Archive")).toBeUndefined();
    await press(button("Unarchive"));
    const dialog = document.querySelector("[role='alertdialog']");
    await press([...(dialog?.querySelectorAll("button") ?? [])].find((node) => node.textContent === "Unarchive"));
    expect(setArchived).toHaveBeenCalledWith(7, false);
  });

  it("offers nothing while the status is derived from a running tournament", async () => {
    for (const status of ["announcement", "live"] as const) {
      const container = await mount(tournament(status));
      expect(container.querySelector("button")).toBeNull();
    }
  });

  it("renders nothing without tournament.update", async () => {
    const container = await mount(tournament("completed"), false);
    expect(container.querySelector("button")).toBeNull();
  });
});
