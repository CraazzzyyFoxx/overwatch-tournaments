// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { navigation } from "@/test/url-navigation";

import { useWorkspaceStore } from "@/stores/workspace.store";
import type { Workspace } from "@/types/workspace.types";

import AchievementsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  disciplines: [] as { code: string; name: string; enabled: boolean }[],
}));

vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const { default: en } = await import("@/i18n/messages/en.json");
  return {
    ...actual,
    useTranslations: (namespace?: string) =>
      actual.createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  };
});
vi.mock("next/navigation", async () => (await import("@/test/url-navigation")).nextNavigationMock);
vi.mock("@/services/discipline.service", () => ({ default: { list: async () => mocks.disciplines } }));
vi.mock("@/hooks/usePermissions", () => ({ usePermissions: () => ({ canAccessPermission: () => true }) }));
vi.mock("@/services/admin.service", () => ({ default: {} }));
vi.mock("./_hooks/useAchievementCatalog", () => ({
  useAchievementCatalog: () => ({ tournaments: { results: [] }, overrides: [], allRules: [] }),
}));
vi.mock("@/components/admin/AdminPageHeader", () => ({
  AdminPageHeader: ({ actions }: { actions?: React.ReactNode }) => <div>{actions}</div>,
}));
vi.mock("@craazzzyyfoxx/admin-kit/kit/EmptyNote", () => ({ EmptyNote: ({ children }: { children: React.ReactNode }) => <p>{children}</p> }));
vi.mock("@craazzzyyfoxx/admin-kit/kit/ConfirmDialog", () => ({ ConfirmDialog: () => null }));
vi.mock("@/components/admin/achievements/EvaluationRunSummary", () => ({ EvaluationRunSummary: () => null }));
vi.mock("./_components/AchievementFormDialog", () => ({ AchievementFormDialog: () => null }));
vi.mock("./_components/AchievementImportDialog", () => ({ AchievementImportDialog: () => null }));
vi.mock("./_components/AchievementOverridesCard", () => ({ AchievementOverridesCard: () => null }));
vi.mock("./_components/DryRunResultPanel", () => ({ DryRunResultPanel: () => null }));
// The table is replaced by a probe: the game it lists, the page's filter bar in its toolbar slot, and a row action
// that opens the evaluate picker for rule 11.
vi.mock("./_components/AchievementsTable", () => ({
  AchievementsTable: ({
    discipline,
    toolbar,
    actions,
  }: {
    discipline: string | null;
    toolbar?: ReactNode;
    actions: { onEvaluate: (rule: never) => void };
  }) => (
    <div data-table data-discipline={discipline ?? ""}>
      {toolbar}
      <button data-evaluate onClick={() => actions.onEvaluate({ id: 11, discipline: "overwatch" } as never)} />
    </div>
  ),
}));
vi.mock("./_components/EvaluateAchievementsDialog", () => ({
  EvaluateAchievementsDialog: ({ selectedRuleIds }: { selectedRuleIds: Set<number> }) => (
    <div data-evaluate-open data-selected={[...selectedRuleIds].join(",")} />
  ),
}));
vi.mock("@/components/workspace/DisciplineUnavailable", () => ({
  DisciplineUnavailable: ({ game }: { game: { kind: string } }) => <p data-unavailable={game.kind} />,
}));

function workspace(id: number, disciplines: string[]): Workspace {
  return {
    id,
    slug: `ws-${id}`,
    name: `ws-${id}`,
    description: null,
    icon_url: null,
    is_active: true,
    disciplines_enabled: disciplines,
    default_division_grid_versions: {},
    effective_division_grid_versions: {},
  } as Workspace;
}

let root: Root;
let container: HTMLElement;

const click = (element: Element | null | undefined) =>
  act(async () => {
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
const table = () => container.querySelector("[data-table]");
const evaluateDialog = () => container.querySelector("[data-evaluate-open]");
/** Picks a game in the filter bar's inline select; its listbox portals out of the page (an option reads as its mark, then its name). */
async function pickGame(name: string) {
  await click(container.querySelector('button[role="combobox"][aria-label="Game"]'));
  await click([...document.querySelectorAll('[role="option"]')].find((node) => node.textContent?.endsWith(name)));
}

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <AchievementsPage />
      </QueryClientProvider>
    );
  });
  await act(() => new Promise<void>((done) => setTimeout(done, 0)));
}

afterEach(async () => {
  await act(async () => root.unmount());
});

beforeEach(() => {
  mocks.disciplines = [
    { code: "overwatch", name: "Overwatch", enabled: true },
    { code: "lol", name: "League of Legends", enabled: true },
  ];
  navigation.reset("/admin/achievements");
  document.body.innerHTML = "";
  document.cookie = "owt-discipline=; Max-Age=0; path=/";
  container = document.body.appendChild(document.createElement("div"));
  root = createRoot(container);
  useWorkspaceStore.setState({
    workspaces: [workspace(7, ["overwatch", "lol"]), workspace(8, ["lol"])],
    currentWorkspaceId: 7,
    statsScope: "workspace",
    gameScope: "all",
    lastGame: null,
    hostLockedWorkspaceId: null,
    entityWorkspaceId: null,
  });
});

describe("the achievements page's game select", () => {
  it("lists every game's rules, whatever the saved scope, until the select narrows them to one game", async () => {
    useWorkspaceStore.setState({ gameScope: "overwatch", lastGame: "overwatch" });
    await mount();
    expect(table()?.getAttribute("data-discipline")).toBe("");

    await pickGame("League of Legends");

    expect(navigation.current()).toBe("/admin/achievements?discipline=lol");
    expect(table()?.getAttribute("data-discipline")).toBe("lol");
  });
});

describe("the achievements page keeps each game's drafts to that game", () => {
  it("drops an evaluate selection made for Overwatch when the select moves to League", async () => {
    navigation.reset("/admin/achievements?discipline=overwatch");
    await mount();
    await click(container.querySelector("[data-evaluate]"));
    expect(evaluateDialog()?.getAttribute("data-selected")).toBe("11");

    await pickGame("League of Legends");

    expect(evaluateDialog()).toBeNull();
  });

  it("shows the actionable unavailable state, and no page, when the workspace has no game enabled", async () => {
    mocks.disciplines = [{ code: "overwatch", name: "Overwatch", enabled: false }];
    await mount();

    expect(container.querySelector("[data-unavailable=empty]")).not.toBeNull();
    expect(table()).toBeNull();
  });

  it("shows the error, not another game, for an explicit game the workspace does not run", async () => {
    navigation.reset("/admin/achievements?discipline=starcraft");
    await mount();

    expect(container.querySelector("[data-unavailable=invalid]")).not.toBeNull();
    expect(table()).toBeNull();
    expect(navigation.current()).toBe("/admin/achievements?discipline=starcraft");
  });

  it("follows the page's workspace when its games arrive after the id is already known", async () => {
    mocks.disciplines = [];
    await mount();
    expect(container.querySelector("[data-unavailable=empty]")).not.toBeNull();

    mocks.disciplines = [{ code: "lol", name: "League of Legends", enabled: true }];
    await act(async () => useWorkspaceStore.getState().setCurrentWorkspace(8));
    await act(() => new Promise<void>((done) => setTimeout(done, 0)));

    expect(container.querySelector("[data-unavailable]")).toBeNull();
    expect(table()).not.toBeNull();
  });
});
