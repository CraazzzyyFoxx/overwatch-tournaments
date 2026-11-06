// @vitest-environment happy-dom
//
// The overview's "How it's played" card is read off the flow: a league is ONE
// step with its rule and a link to the table, progress is a check and a
// highlight (never a raw status), and a tournament whose flow does not load
// keeps the stage-based steps.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { leagueFlow } from "@/lib/flow/fixtures";
import type { Tournament } from "@/types/tournament.types";

import { OverviewFormatCard } from "./OverviewSideCards";

vi.mock(
  "@/services/discipline.service",
  async () => (await import("@/test/discipline-metadata")).disciplineServiceMock
);

const getFlow = vi.fn();
vi.mock("@/services/flow.service", () => ({
  default: { get: (...args: unknown[]) => getFlow(...args) }
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  )
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const stage = (id: number, name: string, status: string) => ({
  id,
  name,
  status,
  order: id,
  stage_type: "round_robin",
  max_rounds: 0,
  best_of: { default: 3, final: null }
});

const tournament = {
  id: 7,
  slug: "owal",
  workspace_id: 1,
  discipline: "overwatch",
  team_formation: "balancer",
  roster_shape: null,
  status: "live",
  stages: [stage(31, "Day 1", "completed"), stage(32, "Day 2", "live"), stage(33, "Day 3", "draft")]
} as unknown as Tournament;

let root: Root | null = null;
const host = document.createElement("div");
document.body.append(host);

async function render() {
  root = createRoot(host);
  await act(async () => {
    root!.render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <NextIntlClientProvider locale="en" messages={en}>
          <OverviewFormatCard tournament={tournament} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  // Let the flow query settle, then its render.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  getFlow.mockReset();
});

describe("OverviewFormatCard", () => {
  it("shows a league as one step with its rule and a link to the table", async () => {
    getFlow.mockResolvedValue(leagueFlow());
    await render();

    expect(host.querySelectorAll("ol > li")).toHaveLength(1);
    expect([...host.querySelectorAll("ol > li")].length).toBe(1);
    expect(host.textContent).toContain("3 match days");
    expect(host.textContent).toContain("best 2 of 3 days count");
    expect(host.textContent).toContain("points = stage points");
    expect(host.querySelector("a")?.getAttribute("href")).toBe("/tournaments/owal/table");
    expect(host.textContent).not.toMatch(/final|closed/i);
  });

  it("falls back to the stages when the flow cannot be read", async () => {
    getFlow.mockRejectedValue(new Error("down"));
    await render();

    const steps = [...host.querySelectorAll("ol > li")];
    expect(steps).toHaveLength(3);
    expect(steps[1]!.getAttribute("aria-current")).toBe("step");
    expect(steps[0]!.textContent).toContain("Day 1");
  });
});
