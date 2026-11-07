// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it } from "vitest";

import { BalanceEditor } from "@/components/balancer/BalanceEditor";
import ru from "@/i18n/messages/ru.json";
import type { RoleOntology } from "@/lib/roster/ontology";
import { LOL_METADATA, OW_METADATA } from "@/test/discipline-metadata";
import type { InternalBalancePayload, InternalBalancePlayer } from "@/types/balancer-admin.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

function seat(name: string, role: string): InternalBalancePlayer {
  return {
    uuid: name,
    name,
    assigned_rating: 2000,
    role_discomfort: 0,
    is_captain: false,
    is_flex: false,
    role_preferences: [role],
    all_ratings: { [role]: 2000 },
  };
}

function payloadOf(roster: Record<string, InternalBalancePlayer[]>): InternalBalancePayload {
  return {
    teams: [{ id: 1, name: "Team One", average_mmr: 2000, roster }],
    statistics: {},
    benched_players: [],
  };
}

async function mount(payload: InternalBalancePayload, ontology: RoleOntology) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <QueryClientProvider client={new QueryClient()}>
        <BalanceEditor value={payload} onChange={() => {}} divisionGrid={{ tiers: [] }} ontology={ontology} />
      </QueryClientProvider>,
    );
  });
  return container;
}

/** The role glyph of each player row, top to bottom, named by the owner game's dictionary. */
function rowRoles(scope: Element): string[] {
  return [...scope.querySelectorAll("tbody tr td:first-child [role='img']")].map(
    (node) => node.getAttribute("aria-label") ?? "",
  );
}

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("BalanceEditor", () => {
  it("draws an Overwatch 1-2-2 team in the game's role order, with no open row", async () => {
    const scope = await mount(
      payloadOf({
        support: [seat("Sup One", "support"), seat("Sup Two", "support")],
        damage: [seat("Dps One", "damage"), seat("Dps Two", "damage")],
        tank: [seat("Tank One", "tank")],
        flex: [],
      }),
      OW_METADATA,
    );

    expect(rowRoles(scope)).toEqual(["Tank", "Damage", "Damage", "Support", "Support"]);
    expect(scope.textContent).not.toContain("Drop flex");
  });

  it("draws every player of a League team in its own positions", async () => {
    const names = ["Top Laner", "Jungler", "Mid Laner", "Bot Laner", "Support Main"];
    const scope = await mount(
      payloadOf({
        support: [seat(names[4], "support")],
        bot: [seat(names[3], "bot")],
        mid: [seat(names[2], "mid")],
        jungle: [seat(names[1], "jungle")],
        top: [seat(names[0], "top")],
      }),
      LOL_METADATA,
    );

    for (const name of names) expect(scope.textContent).toContain(name);
    expect(rowRoles(scope)).toEqual(["Top", "Jungle", "Mid", "Bot", "Support"]);
  });

  it("reads Russian in the ru locale", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const payload: InternalBalancePayload = {
      ...payloadOf({ tank: [seat("Tank One", "tank")], damage: [], support: [] }),
      benched_players: [seat("Bench One", "support")],
    };
    await act(async () => {
      createRoot(container).render(
        <NextIntlClientProvider locale="ru" messages={ru}>
          <QueryClientProvider client={new QueryClient()}>
            <BalanceEditor value={payload} onChange={() => {}} divisionGrid={{ tiers: [] }} ontology={OW_METADATA} />
            <BalanceEditor value={null} onChange={() => {}} divisionGrid={{ tiers: [] }} ontology={OW_METADATA} />
          </QueryClientProvider>
        </NextIntlClientProvider>,
      );
    });

    const text = container.textContent ?? "";
    for (const copy of ["Не влезли в команды", "Сумма:", "Сред.:", "Игрок", "Ранг", "Запустите балансировщик"]) {
      expect(text).toContain(copy);
    }
    for (const copy of ["Didn't fit a team", "Total:", "Avg:", "Player", "Prefs", "Run the balancer"]) {
      expect(text).not.toContain(copy);
    }
  });
});
