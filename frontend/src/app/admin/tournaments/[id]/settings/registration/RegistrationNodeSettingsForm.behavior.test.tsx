// @vitest-environment happy-dom
//
// The registration node's intake settings are saved with its config through the flow upsert. Pinned: the late
// sign-up override has a labelled control (it spent a release editable only through the raw admin API), a save sends
// the node's whole config with the edit on top, and the override warns when the sign-up window has no end to lift.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { TournamentFlowNode } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";
import { RegistrationNodeSettingsForm } from "./RegistrationNodeSettingsForm";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const applyChanges = vi.fn();

vi.mock("@/services/flow.service", () => ({
  default: { applyChanges: (...args: unknown[]) => applyChanges(...args) }
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() })
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ isLoaded: true, canAccessPermission: () => true })
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), info: vi.fn(), apiError: vi.fn() }
}));

const TOURNAMENT = { id: 64, workspace_id: 1 } as unknown as Tournament;

function makeNode(overrides: Partial<TournamentFlowNode> = {}): TournamentFlowNode {
  return {
    id: 21,
    kind: "registration",
    name: "Day 3",
    status: "open",
    stage_id: null,
    config: { check_in: true, intake: "team", max_participants: 60 },
    schedule: [],
    ...overrides
  } as TournamentFlowNode;
}

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

async function render(node: TournamentFlowNode) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}>
        <NextIntlClientProvider locale="en" messages={en}>
          <RegistrationNodeSettingsForm tournament={TOURNAMENT} node={node} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
}

const toggle = (id: string) => {
  const found = container.querySelector(`[id$='-${id}']`);
  if (!found) throw new Error(`${id} toggle not rendered`);
  return found;
};

beforeEach(() => {
  applyChanges.mockReset().mockResolvedValue({});
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("RegistrationNodeSettingsForm", () => {
  it("labels the late sign-up override and saves it with the node's whole config", async () => {
    await render(makeNode());

    expect(container.querySelector("label[for$='-allow-late']")?.textContent).toBe("Allow late registration");
    expect(toggle("allow-late").getAttribute("aria-checked")).toBe("false");

    await act(async () => {
      toggle("allow-late").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();
    expect(toggle("allow-late").getAttribute("aria-checked")).toBe("true");

    await act(async () => {
      [...document.querySelectorAll("button")]
        .find((button) => button.textContent?.trim() === "Save changes")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(applyChanges).toHaveBeenCalledWith(64, {
      nodes: [
        {
          id: 21,
          kind: "registration",
          name: "Day 3",
          config: { check_in: true, intake: "team", max_participants: 60, allow_late_registration: true }
        }
      ]
    });
  });

  it("warns that the override changes nothing while the sign-up window is open-ended", async () => {
    await render(makeNode());
    expect(container.textContent).toContain("this changes nothing");
  });

  it("drops the warning once the window has an end to lift", async () => {
    await render(
      makeNode({ schedule: [{ phase: "open", starts_at: "2026-04-01T00:00:00Z", ends_at: "2026-04-10T00:00:00Z" }] })
    );
    expect(container.textContent).not.toContain("this changes nothing");
  });
});
