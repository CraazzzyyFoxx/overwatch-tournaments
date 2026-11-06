// @vitest-environment happy-dom
//
// `logs_official` is the owner's policy for accepting uploaded match logs as official results. It must save
// through the scoring section's whitelist alone (a section PATCHes only its own fields) and only for someone
// who may update the tournament.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Tournament } from "@/types/tournament.types";
import ScoringSettingsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getTournament = vi.fn();
const updateTournament = vi.fn();
let mayUpdate = true;

vi.mock("@/services/admin.service", () => ({
  default: {
    getTournament: (...args: unknown[]) => getTournament(...args),
    updateTournament: (...args: unknown[]) => updateTournament(...args)
  }
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "64" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() })
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ isLoaded: true, canAccessPermission: () => mayUpdate })
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), info: vi.fn(), apiError: vi.fn() }
}));

vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const { default: en } = await import("@/i18n/messages/en.json");
  return {
    ...actual,
    useTranslations: (namespace?: string) =>
      actual.createTranslator({ locale: "en", messages: en, namespace: namespace as never })
  };
});

const TOURNAMENT = {
  id: 64,
  workspace_id: 1,
  name: "OWT 64",
  slug: "owt-64",
  is_finished: false,
  logs_official: false,
  team_formation: "balancer",
  status: "live",
  stages: []
} as unknown as Tournament;

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
        <ScoringSettingsPage />
      </QueryClientProvider>
    );
  });
  await settle();
}

const checkbox = () => container.querySelector("#settings-logs-official")!;

beforeEach(() => {
  mayUpdate = true;
  getTournament.mockReset().mockResolvedValue(TOURNAMENT);
  updateTournament.mockReset().mockResolvedValue(TOURNAMENT);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("Settings › Scoring › accept match logs as official", () => {
  it("is off by default and saves only logs_official when switched on", async () => {
    await render();
    expect(checkbox().getAttribute("aria-checked")).toBe("false");

    await act(async () => {
      checkbox().dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();
    await act(async () => {
      [...document.querySelectorAll("button")]
        .find((button) => button.textContent?.trim() === "Save changes")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(updateTournament).toHaveBeenCalledWith(64, { logs_official: true });
  });

  it("is refused outright without the tournament update permission", async () => {
    mayUpdate = false;
    await render();

    // The section frame gates the whole page, so the control never renders for an unauthorized reader.
    expect(container.querySelector("#settings-logs-official")).toBeNull();
    expect(updateTournament).not.toHaveBeenCalled();
  });
});
