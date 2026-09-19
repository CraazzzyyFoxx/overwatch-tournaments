// @vitest-environment happy-dom
//
// The participants section has two shapes and one gate:
//
//  1. a balancer/draft tournament opens on the player POOL — one column per
//     role slot the roster shape asks for, and a player who declared several
//     roles standing in each of those columns (§6 ②③). Team registration keeps
//     the table and never grows a view switch (§6 ①);
//  2. the organizer-only columns (balancer state, check-in, notes, smurfs,
//     subscription) are absent from the column CONFIG without the grant, so
//     they leave the table, the search and the column picker together (§6 ②).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import type { ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { RosterShape } from "@/lib/roster-shape";
import type { Registration, RegistrationForm, RegistrationRole } from "@/types/registration.types";
import type { Tournament, TournamentStatus } from "@/types/tournament.types";

import TournamentParticipantsPage from "../TournamentParticipantsPage";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TOURNAMENT_ID = 91;

const listRegistrations = vi.fn();
const getForm = vi.fn();

vi.mock("@/services/registration.service", () => ({
  default: {
    getMyRegistration: () => Promise.resolve(null),
    listRegistrations: (...args: unknown[]) => listRegistrations(...args),
    getForm: (...args: unknown[]) => getForm(...args),
    checkInMyRegistration: () => Promise.resolve(null),
    withdrawMyRegistration: () => Promise.resolve(null)
  }
}));

vi.mock("@/services/hero.service", () => ({
  default: {
    getAll: () =>
      Promise.resolve({
        results: [
          {
            id: 1,
            name: "Ana",
            slug: "ana",
            image_path: "/ana.png",
            role: "support",
            type: "support"
          },
          {
            id: 2,
            name: "Genji",
            slug: "genji",
            image_path: "/genji.png",
            role: "damage",
            type: "damage"
          },
          { id: 3, name: "Rein", slug: "rein", image_path: "/rein.png", role: "tank", type: "tank" }
        ]
      })
  }
}));

// Anonymous visitor: the pool is a public surface and the check-in card must
// not be part of what these cases assert.
vi.mock("@/hooks/useAuthProfile", () => ({
  useAuthProfile: () => ({ status: "unauthenticated", user: null, error: null, refetch: () => {} })
}));

let canReadOrganizerColumns = false;

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: (permission: string) =>
      permission === "registration.read" ? canReadOrganizerColumns : false
  })
}));

/**
 * The virtualised table stands in for itself, but reports the column CONFIG it
 * was handed — that config is the single array the table, the search and the
 * column picker all read, so it is exactly what the permission gate acts on.
 */
vi.mock("../_components/VirtualParticipantsList", () => ({
  default: ({ allColumns }: { allColumns: { id: string }[] }) => (
    <div data-testid="roster" data-columns={allColumns.map((column) => column.id).join(",")} />
  )
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));

let searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  usePathname: () => `/tournaments/${TOURNAMENT_ID}/participants`,
  useSearchParams: () => searchParams,
  useRouter: () => ({ push: () => {}, replace: () => {} })
}));

let tournament: Tournament;

vi.mock("@/hooks/useTournamentClientData", () => ({
  useTournamentQuery: () => ({ data: tournament, isError: false, refetch: () => {} })
}));

const OW5V5_SHAPE: RosterShape = {
  slots: { tank: 1, damage: 2, support: 2 },
  team_size: 5,
  flex_slots: 0,
  has_role_slots: true,
  draft_rounds: 5,
  source: "tournament"
};

/** Spelled out rather than cast: `tsconfig.json` excludes test files, so a
 *  fixture that lies about its shape type-checks green. */
function makeTournament(
  teamFormation: string,
  status: TournamentStatus,
  rosterShape: RosterShape | null
): Tournament {
  return {
    id: TOURNAMENT_ID,
    created_at: new Date(0),
    updated_at: null,
    workspace_id: 3,
    name: "Anak Cup",
    start_date: new Date(0),
    end_date: new Date(0),
    description: null,
    challonge_id: null,
    challonge_slug: null,
    is_league: false,
    is_finished: false,
    is_hidden: false,
    team_formation: teamFormation,
    status,
    auto_transitions_enabled: true,
    allow_late_registration: false,
    phase_schedule: [],
    win_points: 1,
    draw_points: 0.5,
    loss_points: 0,
    stages: [],
    participants_count: 4,
    registrations_count: 4,
    teams_count: null,
    division_grid_version_id: null,
    division_grid_version: null,
    roster_slots_json: null,
    roster_shape: rosterShape,
    roster_locked_by_draft: null
  };
}

function role(
  name: string,
  rank: number | null,
  heroes: string[] = [],
  isPrimary = true
): RegistrationRole {
  return {
    role: name,
    subrole: null,
    is_primary: isPrimary,
    priority: 0,
    rank_value: rank,
    top_heroes: heroes
  };
}

function makeRegistration(
  id: number,
  battleTag: string,
  roles: RegistrationRole[],
  status = "approved"
): Registration {
  return {
    id,
    tournament_id: TOURNAMENT_ID,
    workspace_id: 3,
    user_id: null,
    battle_tag: battleTag,
    smurf_tags_json: null,
    discord_nick: null,
    twitch_nick: null,
    stream_pov: false,
    roles,
    notes: null,
    custom_fields_json: null,
    status,
    checked_in: false,
    profiles_open: null,
    admission: {
      decision: "pending_check_in",
      requirements: [],
      blockers: [],
      overridden: [],
      checked_in: false,
      ready: true
    },
    submitted_at: null,
    reviewed_at: null
  };
}

const POOL_ROSTER: Registration[] = [
  makeRegistration(1, "Hornet#21345", [role("tank", 3900, ["rein"])]),
  makeRegistration(2, "zMize#2978", [role("damage", 4010, ["genji"])]),
  makeRegistration(3, "manqa#21668", [role("support", 3720, ["ana"])]),
  // The flex player: two declared roles, so two columns.
  makeRegistration(4, "CraazzzyyFox#1", [
    role("damage", 3540, ["genji"]),
    role("support", 3380, ["ana"], false)
  ]),
  makeRegistration(5, "Gone#404", [role("damage", 3000)], "withdrawn")
];

function makeForm(overrides: Partial<RegistrationForm> = {}): RegistrationForm {
  return {
    id: 9,
    tournament_id: TOURNAMENT_ID,
    workspace_id: 3,
    is_open: false,
    require_open_profile: false,
    require_subscription: false,
    // Explicit: `{}` means "the organizer disabled every built-in", which would
    // leave the gated `notes`/`smurf_tags` columns out for an unrelated reason.
    built_in_fields: {
      battle_tag: { enabled: true, required: true },
      primary_role: { enabled: true, required: true },
      top_heroes: { enabled: true, required: false },
      smurf_tags: { enabled: true, required: false },
      notes: { enabled: true, required: false }
    },
    custom_fields: [],
    ...overrides
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  const stored = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      get length() {
        return stored.size;
      },
      key: (index: number) => Array.from(stored.keys())[index] ?? null,
      getItem: (key: string) => stored.get(key) ?? null,
      setItem: (key: string, value: string) => void stored.set(key, String(value)),
      removeItem: (key: string) => void stored.delete(key),
      clear: () => stored.clear()
    }
  });
  canReadOrganizerColumns = false;
  searchParams = new URLSearchParams();
  tournament = makeTournament("draft", "check_in", OW5V5_SHAPE);
  // The service returns the whole list envelope; the pool reads its rows.
  listRegistrations.mockResolvedValue({
    registrations: POOL_ROSTER,
    division_grids: {},
    hidden: false,
    total: POOL_ROSTER.length,
    role_counts: {},
    max_participants: null
  });
  getForm.mockResolvedValue(makeForm());
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

/** Let queued promise callbacks and React Query's own scheduling drain. */
async function settle(ticks = 3) {
  for (let index = 0; index < ticks; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <TournamentParticipantsPage slug="anak-cup" />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
}

function column(role: string): HTMLElement | null {
  return container.querySelector<HTMLElement>(`[data-pool-column="${role}"]`);
}

/** The pool is the second view now, so its cases have to ask for it. */
async function mountPool() {
  searchParams = new URLSearchParams("view=pool");
  await mount();
}

describe("participants pool", () => {
  it("opens on the table even where a pool exists", async () => {
    await mount();

    expect(container.querySelector('[data-testid="roster"]')).not.toBeNull();
    expect(container.querySelector("[data-pool-column]")).toBeNull();
  });

  it("gives the pool one column per role slot", async () => {
    await mountPool();

    expect(
      [...container.querySelectorAll("[data-pool-column]")].map((node) =>
        node.getAttribute("data-pool-column")
      )
    ).toEqual(["tank", "damage", "support"]);
    expect(container.querySelector('[data-testid="roster"]')).toBeNull();

    expect(column("tank")?.textContent).toContain("Hornet#21345");
    expect(column("damage")?.textContent).toContain("zMize#2978");
    expect(column("support")?.textContent).toContain("manqa#21668");
  });

  it("lists a player with several roles in each of them, marked and explained", async () => {
    await mountPool();

    const damage = column("damage");
    const support = column("support");
    expect(damage?.textContent).toContain("CraazzzyyFox#1");
    expect(support?.textContent).toContain("CraazzzyyFox#1");
    // The tank column is not everybody's column: the mark means "also elsewhere",
    // not "shown everywhere".
    expect(column("tank")?.textContent).not.toContain("CraazzzyyFox#1");

    // The explanation rides on the name link; the secondary-role copy is dimmed
    // rather than carrying a glyph, which in a flex tournament every row would.
    const marked = damage?.querySelector<HTMLElement>("[data-flex-mark]");
    const link = marked?.querySelector("a");
    expect(link?.getAttribute("title")).toContain("Plays several roles");
    expect(link?.getAttribute("title")).toContain("DPS");
    expect(link?.getAttribute("title")).toContain("Support");
    const supportLink = support?.querySelector<HTMLElement>("[data-flex-mark] a");
    const [primaryLink, secondaryLink] = link?.className.includes("font-medium")
      ? [link, supportLink]
      : [supportLink, link];
    expect(primaryLink?.className).toContain("font-medium");
    expect(secondaryLink?.className).not.toContain("font-medium");
    // Rank is per role, not per player: the same person sits at a different
    // height in each column. The division reads as an icon, so the SR rides on
    // the title of the cell that carries it.
    expect(damage?.querySelector('[title$="3540"]')).not.toBeNull();
    expect(support?.querySelector('[title$="3380"]')).not.toBeNull();
    expect(damage?.textContent).not.toMatch(/3540/);
  });

  it("sorts each column by rank and folds withdrawn registrations away", async () => {
    await mountPool();

    const damageNames = [...(column("damage")?.querySelectorAll("li") ?? [])].map(
      (node) => node.textContent ?? ""
    );
    expect(damageNames[0]).toContain("zMize#2978");
    expect(damageNames[1]).toContain("CraazzzyyFox#1");
    // A withdrawn registration is never a column row.
    expect(container.querySelector("[data-pool-column]")?.textContent).not.toContain("Gone#404");

    const withdrawn = [...container.querySelectorAll("details")].find((node) =>
      node.textContent?.includes("withdrew")
    );
    expect(withdrawn).toBeDefined();
    expect(withdrawn?.textContent).toContain("Gone#404");
  });

  it("gives team registration the table and no view switch", async () => {
    tournament = makeTournament("registration", "check_in", null);
    await mount();

    expect(container.querySelector('[role="radiogroup"]')).toBeNull();
    expect(container.querySelector("[data-pool-column]")).toBeNull();
    expect(container.querySelector('[data-testid="roster"]')).not.toBeNull();
  });

  it("offers the pool/table switch only where a pool exists", async () => {
    await mountPool();

    const segment = container.querySelector<HTMLElement>('[role="radiogroup"]');
    expect(segment?.getAttribute("aria-label")).toBe("Participant view");
    expect(
      [...(segment?.querySelectorAll('[role="radio"]') ?? [])].map((n) => n.textContent)
    ).toEqual(["Table", "By role"]);

    // The switch opens the toolbar and the search closes it: `.filter-search`
    // owns the one `auto` margin, so a control after it would be pushed into
    // the right-hand cluster and jump when the view changes.
    const toolbar = segment?.closest(".filters");
    const search = toolbar?.querySelector("input");
    expect(segment && search && segment.compareDocumentPosition(search)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
  });

  it("renders the table when the URL asks for it", async () => {
    searchParams = new URLSearchParams("view=table");
    await mount();

    expect(container.querySelector("[data-pool-column]")).toBeNull();
    expect(container.querySelector('[data-testid="roster"]')).not.toBeNull();
  });

  it("keeps organizer-only columns out of the config without the grant", async () => {
    tournament = makeTournament("registration", "check_in", null);
    getForm.mockResolvedValue(makeForm({ require_subscription: true }));
    await mount();

    const columns = (
      container.querySelector('[data-testid="roster"]')?.getAttribute("data-columns") ?? ""
    ).split(",");
    for (const id of ["notes", "smurf_tags"]) {
      expect(columns).not.toContain(id);
    }
    // The registration's own state is public: check-in, the subscription
    // verdict and the balancer status answer "am I in and what is still
    // missing", which is why the roster is opened at all.
    for (const id of ["battle_tag", "_check_in", "_subscription", "_balancer_status"]) {
      expect(columns).toContain(id);
    }
  });

  it("restores organizer-only columns for a reader who may see them", async () => {
    canReadOrganizerColumns = true;
    tournament = makeTournament("registration", "check_in", null);
    getForm.mockResolvedValue(makeForm({ require_subscription: true }));
    await mount();

    const columns = (
      container.querySelector('[data-testid="roster"]')?.getAttribute("data-columns") ?? ""
    ).split(",");
    for (const id of ["notes", "smurf_tags"]) {
      expect(columns).toContain(id);
    }
  });
});
