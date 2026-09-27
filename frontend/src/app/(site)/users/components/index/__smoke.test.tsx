// @vitest-environment happy-dom
// THROWAWAY smoke check for the UsersClient split — delete after running.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { DEFAULT_DIVISION_GRID } from "@/lib/divisions/grid";
import UsersClient from "./UsersClient";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/navigation", () => ({
  usePathname: () => "/users",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() })
}));
vi.mock("@/hooks/useCurrentWorkspace", () => ({
  useCurrentWorkspaceId: () => 1,
  useDivisionGrid: () => DEFAULT_DIVISION_GRID
}));
vi.mock("@/services/user.service", () => ({
  default: {
    getUsersOverview: vi.fn(async () => ({
      results: [
        {
          id: 7,
          name: "Ana#1234",
          roles: [{ role: "Tank", division: 5 }],
          tournaments_count: 9,
          achievements_count: 3,
          averages: {
            avg_placement: 4,
            avg_playoff_placement: 3,
            avg_group_placement: 5,
            avg_closeness: 0.5
          },
          top_heroes: []
        }
      ],
      total: 1,
      page: 1,
      per_page: 20
    })),
    getUsersOverviewStats: vi.fn(async () => ({
      total_players: 100,
      tank_count: 30,
      damage_count: 40,
      support_count: 30,
      flex_count: 12,
      with_logs_count: 50,
      with_logs_pct: 50,
      avg_tournaments_per_player: 3.2,
      median_tournaments_per_player: 3,
      active_last_30d: 20,
      active_last_30d_pct: 20
    })),
    getUsersCatalog: vi.fn(async () => ({ letters: [], available_letters: [], total: 0 }))
  }
}));

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

it("renders the users index with a row and its expanded detail", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
          <UsersClient />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });

  for (let i = 0; i < 8; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }

  expect(container.textContent).toContain("Ana#1234");
  expect(container.textContent).toContain("100");

  const expand = container.querySelector<HTMLButtonElement>(
    `button[aria-label="${en.users.list.a11y.expandDetails}"]`
  );
  expect(expand).not.toBeNull();
  await act(async () => expand?.click());
  expect(container.textContent).toContain(en.users.list.expanded.avgPlayoff);
});
