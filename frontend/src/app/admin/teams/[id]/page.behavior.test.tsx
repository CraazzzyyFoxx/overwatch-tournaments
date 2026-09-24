// @vitest-environment happy-dom
//
// The team hub header after P3-3. What is pinned here:
//  1. the team name appears once, and it is the page's only `<h1>` — the old
//     header printed it twice, as an `sr-only` heading plus the edit field;
//  2. that `<h1>` is still the rename field, and saving it PATCHes the team;
//  3. the header owns the way back to the list, scoped to the tournament.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Player, Team } from "@/types/team.types";
import AdminTeamWorkspacePage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getTeam = vi.fn();
const updateTeam = vi.fn();

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useFormatter: () => ({ dateTime: (value: Date) => value.toISOString().slice(0, 10) })
}));
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "9" }),
  usePathname: () => "/admin/teams/9",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() })
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ canAccessPermission: () => true, isLoaded: true, isSuperuser: false })
}));
vi.mock("@/services/admin.service", () => ({
  default: {
    getTeam: (...args: unknown[]) => getTeam(...args),
    updateTeam: (...args: unknown[]) => updateTeam(...args),
    uploadTeamImage: vi.fn(),
    deleteTeamImage: vi.fn(),
    deleteTeam: vi.fn()
  }
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));
// The roster editor has its own behaviour suite and its own service surface.
vi.mock("@/components/admin/teams/TeamRosterEditor", () => ({
  TeamRosterEditor: () => <div data-testid="roster-editor" />
}));

function team(overrides: Partial<Team> = {}): Team {
  return {
    id: 9,
    created_at: new Date("2026-01-01T00:00:00Z"),
    updated_at: null,
    name: "Wombat Warriors",
    image_url: null,
    avg_sr: 3350.4,
    total_sr: 16752,
    captain_id: 91,
    tournament_id: 7,
    players: [
      {
        id: 501,
        created_at: new Date("2026-01-01T00:00:00Z"),
        updated_at: null,
        name: "Nova",
        sub_role: null,
        rank: 3400,
        division: 4,
        role: "damage",
        tournament_id: 7,
        user_id: 91,
        team_id: 9,
        is_newcomer: false,
        is_newcomer_role: false,
        is_substitution: false,
        related_player_id: null,
        user: { id: 91, name: "Nova" } as Player["user"]
      }
    ],
    tournament: {
      id: 7,
      name: "MoonRise Mix Vol.4",
      start_date: "2026-02-01",
      end_date: "2026-02-28"
    } as unknown as Team["tournament"],
    placement: 3,
    group: null,
    ...overrides
  };
}

const mounted: { root: Root; container: HTMLElement }[] = [];

async function settle(turns = 8) {
  for (let turn = 0; turn < turns; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount(node: ReactNode = <AdminTeamWorkspacePage />) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
  });
  await settle();
  return container;
}

beforeEach(() => {
  getTeam.mockReset().mockResolvedValue(team());
  updateTeam.mockReset().mockResolvedValue(team({ name: "Wombat Wizards" }));
  document.body.innerHTML = "";
});

afterEach(async () => {
  await act(async () => {
    for (const { root, container } of mounted.splice(0)) {
      root.unmount();
      container.remove();
    }
  });
  document.body.innerHTML = "";
});

describe("/admin/teams/[id]", () => {
  it("names the team once, in the page's only h1", async () => {
    const container = await mount();

    const headings = container.querySelectorAll("h1");
    expect(headings.length).toBe(1);
    expect(headings[0].textContent).toContain("Wombat Warriors");
    // One occurrence in the whole document outline: the hub header replaced
    // the sr-only title that used to duplicate the edit field.
    const occurrences = (container.textContent ?? "").split("Wombat Warriors").length - 1;
    expect(occurrences).toBe(1);
  });

  it("renames the team from that heading", async () => {
    const container = await mount();

    const pencil = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Edit team name"]'
    );
    await act(async () => {
      pencil?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const input = container.querySelector<HTMLInputElement>('input[aria-label="team name"]');
    expect(input).not.toBeNull();
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value"
    )!.set!;
    await act(async () => {
      setter.call(input, "Wombat Wizards");
      input!.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      container
        .querySelector('button[aria-label="Save team name"]')
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(updateTeam).toHaveBeenCalledWith(9, { name: "Wombat Wizards" });
  });

  it("goes back to the list scoped to the team's tournament", async () => {
    const container = await mount();

    const back = container.querySelector<HTMLAnchorElement>('a[aria-label="Back"]');
    expect(back?.getAttribute("href")).toBe("/admin/teams?tournament=7");
  });
});
