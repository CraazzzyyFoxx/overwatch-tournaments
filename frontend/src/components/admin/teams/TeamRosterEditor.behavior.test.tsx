// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { Player } from "@/types/team.types";
import { TeamRosterEditor } from "./TeamRosterEditor";

vi.mock("@/services/discipline.service", async () => (await import("@/test/discipline-metadata")).disciplineServiceMock);

/** The tournament's own grid: this editor never reaches for another game's ladder. */
const DIVISION_GRID = {
  tiers: [
    { number: 20, name: "Diamond 5", slug: "diamond-5", sort_order: 20, rank_min: 3000, rank_max: 3499, icon_url: "/divisions/diamond-5.png" }
  ]
};

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getPlayerSubRoles = vi.fn();
const updatePlayer = vi.fn();
const createPlayer = vi.fn();
const deletePlayer = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getPlayerSubRoles: (...args: unknown[]) => getPlayerSubRoles(...args),
    updatePlayer: (...args: unknown[]) => updatePlayer(...args),
    createPlayer: (...args: unknown[]) => createPlayer(...args),
    deletePlayer: (...args: unknown[]) => deletePlayer(...args)
  }
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
vi.mock("next/image", () => ({
  // eslint-disable-next-line @next/next/no-img-element -- this IS the next/image stand-in
  default: ({ src, alt }: { src: string; alt: string }) => <img src={src} alt={alt} />
}));
vi.mock("@/hooks/useCurrentWorkspace", () => ({ useDivisionGrid: () => DIVISION_GRID }));
vi.mock("@/components/kit/ServerSearchCombobox", () => ({
  UserSearchCombobox: () => <div data-testid="user-search" />
}));

function player(overrides: Partial<Player> & { id: number; name: string }): Player {
  return {
    created_at: new Date(0),
    updated_at: null,
    display: { name: overrides.name, tag: null, canonical: null, snapshot: null },
    rank: 3000,
    division: 20,
    role: { dimension: "player_role", role: "damage" },
    tournament_id: 7,
    user_id: overrides.id + 100,
    team_id: 3,
    is_newcomer: false,
    is_newcomer_role: false,
    is_substitution: false,
    related_player_id: null,
    user: null,
    ...overrides
  };
}

const SUPPORT = player({ id: 1, name: "Mercy", role: { dimension: "player_role", role: "support" }, rank: 2800 });
const TANK = player({ id: 2, name: "Rein", role: { dimension: "player_role", role: "tank_main_heal", parent: "tank" }, rank: 3300 });
const DAMAGE = player({ id: 3, name: "Tracer", role: { dimension: "player_role", role: "damage" }, rank: 3100 });
const TANK_SUB = player({
  id: 4,
  name: "Sigma",
  role: { dimension: "player_role", role: "tank" },
  rank: 3200,
  is_substitution: true,
  related_player_id: 2
});

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

async function mount(props?: { canUpdatePlayer?: boolean; discipline?: string | null; players?: Player[] }) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);

  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        {/* The admin layout mounts one; mirror it so tooltips resolve. */}
        <TooltipProvider>
          <TeamRosterEditor
            teamId={3}
            tournamentId={7}
            workspaceId={1}
            discipline={props?.discipline === undefined ? "overwatch" : props.discipline}
            players={props?.players ?? [SUPPORT, TANK, DAMAGE, TANK_SUB]}
            divisionGrid={null}
            canCreatePlayer
            canUpdatePlayer={props?.canUpdatePlayer ?? true}
            canDeletePlayer
          />
        </TooltipProvider>
      </QueryClientProvider>
    );
  });

  for (let turn = 0; turn < 5; turn += 1) {
    await act(async () => {
      await tick();
    });
  }

  return container;
}

function rankFields(scope: HTMLElement) {
  return Array.from(
    scope.querySelectorAll<HTMLInputElement>('input[aria-label^="Rank of "]')
  );
}

const nativeValueSetter = Object.getOwnPropertyDescriptor(
  HTMLInputElement.prototype,
  "value"
)?.set;

async function typeAndBlur(field: HTMLInputElement, value: string) {
  await act(async () => {
    nativeValueSetter?.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  // React implements `onBlur` on the bubbling `focusout` event.
  await act(async () => {
    field.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  });
}

describe("TeamRosterEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getPlayerSubRoles.mockResolvedValue([
      {
        id: 9,
        workspace_id: 1,
        discipline: "overwatch",
        dimension: "player_role",
        attrs: {},
        role: "tank",
        slug: "main_heal",
        label: "Main Heal",
        description: null,
        sort_order: 0,
        is_active: true
      }
    ]);
    updatePlayer.mockResolvedValue({});
  });

  it("reads child roles from its authorized owner prop without a tournament.read request", async () => {
    await mount({ discipline: "lol" });
    expect(getPlayerSubRoles).toHaveBeenCalledWith({ workspace_id: 1, discipline: "lol" }, expect.any(AbortSignal));
  });

  it("shows an owner-scope error instead of silently disabling child-role access", async () => {
    const scope = await mount({ discipline: null });
    expect(scope.textContent).toContain("Owner workspace or discipline is missing");
    expect(getPlayerSubRoles).not.toHaveBeenCalled();
  });

  it("keeps the roster visible when player.read denies only the child-role catalog", async () => {
    getPlayerSubRoles.mockRejectedValue(Object.assign(new Error("Forbidden"), { status: 403 }));
    const scope = await mount();
    expect(rankFields(scope)).toHaveLength(4);
    expect(rankFields(scope).every(field => !field.disabled)).toBe(true);
    expect(rankFields(scope)[0].getAttribute("aria-label")).toBe("Rank of Rein");
    expect(rankFields(scope)[0].value).toBe("3300");
    const message = scope.querySelector<HTMLParagraphElement>('p[role="status"]')!;
    expect(message.textContent).toBe("Could not load the owner's child roles.");
    const subRoleControls = [...scope.querySelectorAll<HTMLButtonElement>('button[aria-label^="Sub-role of "]')];
    expect(subRoleControls).toHaveLength(4);
    expect(subRoleControls.every(control => control.disabled && control.getAttribute("aria-describedby") === message.id)).toBe(true);
  });

  it("orders the roster by role and nests a substitute under the slot it covers", async () => {
    const scope = await mount();

    expect(rankFields(scope).map((field) => field.getAttribute("aria-label"))).toEqual([
      "Rank of Rein",
      "Rank of Sigma",
      "Rank of Tracer",
      "Rank of Mercy"
    ]);
  });

  it("shows role and rank as the site-wide icons, not text", async () => {
    const scope = await mount();

    // Role: an icon-only trigger whose accessible name still carries the value.
    const roleTriggers = Array.from(
      scope.querySelectorAll<HTMLElement>('[aria-label^="Role of "]')
    );
    expect(roleTriggers.map((trigger) => trigger.getAttribute("aria-label"))).toContain(
      "Role of Rein: Tank"
    );
    // …drawn from the owner game's own presentation, never a bundled one.
    expect(roleTriggers[0].querySelector('img[src="/test-roles/tank.svg"]')).not.toBeNull();

    // The supplied OW division stays visible beside the editable rank.
    const divisionIcon = scope.querySelector<HTMLImageElement>('img[alt="Diamond 5"]');
    expect(divisionIcon?.getAttribute("src")).toBe("/divisions/diamond-5.png");
    expect(rankFields(scope)[0].value).toBe("3300");
  });

  it("names and draws a League roster from its own positions, not Overwatch's", async () => {
    const scope = await mount({
      discipline: "lol",
      players: [
        player({ id: 5, name: "Faker", role: { dimension: "position", role: "mid" }, rank: 2900 }),
        player({ id: 6, name: "Canyon", role: { dimension: "position", role: "jungle" }, rank: 2700 }),
        player({ id: 7, name: "Flex One", role: null, rank: 2500 })
      ]
    });

    const triggers = Array.from(scope.querySelectorAll<HTMLElement>('[aria-label^="Role of "]'));
    expect(triggers.map((trigger) => trigger.getAttribute("aria-label"))).toEqual(
      expect.arrayContaining(["Role of Faker: Mid", "Role of Canyon: Jungle", "Role of Flex One: Flex"])
    );
    expect(scope.querySelector('img[src="/test-roles/mid.svg"]')).not.toBeNull();
    expect(scope.querySelector('img[src="/test-roles/tank.svg"]')).toBeNull();
  });

  it("persists a rank edit on blur", async () => {
    const scope = await mount();
    const rein = rankFields(scope).find(
      (field) => field.getAttribute("aria-label") === "Rank of Rein"
    )!;

    await typeAndBlur(rein, "3450");

    expect(updatePlayer).toHaveBeenCalledWith(2, { rank: 3450 });
  });

  it("clears a rank when the field is emptied, and shows an unranked player's field empty", async () => {
    const scope = await mount({ players: [TANK, player({ id: 5, name: "Duelist", rank: null, division: null })] });
    const field = (name: string) => rankFields(scope).find((input) => input.getAttribute("aria-label") === `Rank of ${name}`)!;

    expect(field("Duelist").value).toBe("");
    await typeAndBlur(field("Rein"), "");

    expect(updatePlayer).toHaveBeenCalledWith(2, { rank: null });
  });

  it("persists a newcomer flag toggle", async () => {
    const scope = await mount();
    const toggle = scope.querySelector<HTMLButtonElement>('button[aria-label="Newcomer: Rein"]')!;

    expect(toggle.getAttribute("aria-pressed")).toBe("false");

    await act(async () => {
      toggle.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(updatePlayer).toHaveBeenCalledWith(2, { is_newcomer: true });
  });

  it("disables every roster control without player.update", async () => {
    const scope = await mount({ canUpdatePlayer: false });

    expect(rankFields(scope).every((field) => field.disabled)).toBe(true);
    expect(updatePlayer).not.toHaveBeenCalled();
  });
});
