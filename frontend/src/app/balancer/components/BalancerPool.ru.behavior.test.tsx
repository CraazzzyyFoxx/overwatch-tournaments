// @vitest-environment happy-dom
//
// The balancer's pool and workspace roster read Russian under the ru catalog:
// both used to hard-code English, so a Russian organiser saw an English panel.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import ru from "@/i18n/messages/ru.json";
import type { PlayerValidationState } from "@/components/balancer/balancer-page-helpers";
import { OW_METADATA } from "@/test/discipline-metadata";
import type { BalancerPlayerRecord } from "@/types/balancer-admin.types";

import { BalancingPoolSidebar } from "./BalancingPoolSidebar";
import { WorkspacePlayersSidebar } from "./WorkspacePlayersSidebar";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

vi.mock("@/components/PlayerRoleIcon", () => ({ default: () => null }));
vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));
vi.mock("@/components/RankHistory", () => ({ default: () => null }));
// A closed dnd-kit dialog; inlining it would load a second React copy under pnpm.
vi.mock("./PoolTriageBoard", () => ({ PoolTriageBoard: () => null }));
vi.mock("@/hooks/useDisciplineMetadata", async () => {
  // `vi.mock` is hoisted above the static imports, so its factory loads the fixture itself.
  const { OW_METADATA: metadata } = await import("@/test/discipline-metadata");
  return { useDisciplineMetadata: () => ({ data: metadata }) };
});
vi.mock("@/hooks/useCurrentWorkspace", () => ({ useDivisionGrid: () => ({ tiers: [] }) }));
vi.mock("@/services/workspace-player.service", () => ({
  workspacePlayerKeys: {
    all: (workspaceId: number) => ["workspace-players", workspaceId],
    list: (workspaceId: number) => ["workspace-players", workspaceId, "list"],
  },
  workspacePlayerService: {
    list: () =>
      Promise.resolve({
        results: [{ member_id: 1, player_id: 10, identity: { provider: "battlenet", handle: "Aria#1111" }, display_name: null, display: { name: "Aria#1111", tag: null, canonical: "Aria#1111", snapshot: null }, ranks: {}, author_ranks: {} }],
        total: 1,
        page: 1,
        per_page: 30,
      }),
  },
}));

function player(id: number, battleTag: string, overrides: Partial<BalancerPlayerRecord> = {}): BalancerPlayerRecord {
  return {
    id,
    tournament_id: 80,
    application_id: id,
    identity: battleTag,
    identity_key: battleTag.toLowerCase(),
    additional_handles: [],
    user_id: id,
    role_entries_json: [
      { role: "support", subtype: null, priority: 1, division_number: 12, rank_value: 900, is_active: true, is_declared_active: true, ow_rank_value: null },
    ],
    is_flex: false,
    is_in_pool: true,
    admin_notes: null,
    ...overrides,
  };
}

const POOL_STATES: PlayerValidationState[] = [
  { player: player(1, "Aria#1111", { additional_handles: ["Alt#2222"] }), issues: [] },
  { player: player(2, "Cyrus#3333", { role_entries_json: [] }), issues: [{ code: "missing_ranked_role" }] },
];

async function mountRu(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <NextIntlClientProvider locale="ru" messages={ru}>
        {node}
      </NextIntlClientProvider>,
    );
  });
  // A query resolves after the first commit; a second flush lets it land inside `act`.
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
  return container;
}

describe("the balancer pool in Russian", () => {
  it("names the pool, its filters, rows and issues in Russian", async () => {
    const scope = await mountRu(
      <BalancingPoolSidebar
        allPlayerValidationStates={POOL_STATES}
        ontology={OW_METADATA}
        divisionGrid={{ tiers: [] }}
        applications={[]}
        selectedPlayerId={null}
        onSelectPlayer={() => {}}
      />,
    );
    const text = scope.textContent ?? "";

    expect(text).toContain("Пул балансировки");
    expect(text).toContain("Нужна правка");
    expect(text).toContain("Нет ролей с рангом");
    expect(text).toContain("1 доп. аккаунт");
    expect(scope.querySelector("[aria-label='Выбрать Aria#1111']")).not.toBeNull();
    expect(scope.querySelector("[title='Копировать ник']")).not.toBeNull();
    expect(text).not.toMatch(/Balancing Pool|Need Fix|No ranked roles|1 alt/);
    expect(scope.querySelector("[aria-label='Select Aria#1111']")).toBeNull();
  });

  it("names the workspace roster in Russian", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const scope = await mountRu(
      <QueryClientProvider client={client}>
        <WorkspacePlayersSidebar workspaceId={7} discipline="overwatch" canEdit />
      </QueryClientProvider>,
    );
    const text = scope.textContent ?? "";

    expect(text).toContain("1 игрок");
    expect(text).toContain("Общий запасной ранг");
    expect(scope.querySelector("ul[aria-label='Игроки воркспейса']")).not.toBeNull();
    expect(scope.querySelector("[title='Изменить Aria#1111']")).not.toBeNull();
    expect(text).not.toMatch(/Shared fallback|No ranks yet|1 player/);
  });
});
