// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@craazzzyyfoxx/admin-kit/ui/tooltip";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { navigation } from "@/test/url-navigation";

import AchievementsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/** The page's filtered game (`?discipline=`); `null`: no game chip, every game. */
const scopeGame = vi.hoisted(() => ({ value: null as string | null }));

vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const { default: en } = await import("@/i18n/messages/en.json");
  return {
    ...actual,
    useTranslations: (namespace?: string) =>
      actual.createTranslator({ locale: "en", messages: en, namespace: namespace as never })
  };
});
vi.mock("next/navigation", async () => (await import("@/test/url-navigation")).nextNavigationMock);
vi.mock("@/hooks/useGameScope", async () => {
  const { gameScopeState } = await import("@/test/game-scope");
  return { useGameScope: () => gameScopeState(scopeGame.value) };
});
vi.mock("@/hooks/useGameDescriptors", async () => {
  const { GAME_DESCRIPTORS } = await import("@/test/game-scope");
  return { useGameDescriptors: () => GAME_DESCRIPTORS };
});
vi.mock("@/hooks/usePermissions", () => ({ usePermissions: () => ({ canAccessPermission: () => true }) }));
vi.mock("@/services/admin.service", () => ({ default: {} }));
vi.mock("./_hooks/useAchievementCatalog", () => ({
  useAchievementCatalog: () => ({ tournaments: { results: [] }, overrides: [], allRules: [] })
}));
vi.mock("@/components/admin/AdminPageHeader", () => ({
  AdminPageHeader: ({ actions }: { actions?: ReactNode }) => <div>{actions}</div>
}));
vi.mock("@craazzzyyfoxx/admin-kit/kit/ConfirmDialog", () => ({ ConfirmDialog: () => null }));
vi.mock("@/components/admin/achievements/EvaluationRunSummary", () => ({ EvaluationRunSummary: () => null }));
// `data-form-game` is the game the open create/edit form files the rule under.
vi.mock("./_components/AchievementFormDialog", () => ({
  AchievementFormDialog: ({ form }: { form: { open: boolean; discipline: string | null } }) =>
    form.open ? <output data-form-game={form.discipline ?? ""} /> : null
}));
vi.mock("./_components/AchievementImportDialog", () => ({ AchievementImportDialog: () => null }));
vi.mock("./_components/AchievementOverridesCard", () => ({ AchievementOverridesCard: () => null }));
vi.mock("./_components/DryRunResultPanel", () => ({ DryRunResultPanel: () => null }));
vi.mock("./_components/EvaluateAchievementsDialog", () => ({ EvaluateAchievementsDialog: () => null }));
vi.mock("./_components/AchievementsTable", () => ({ AchievementsTable: () => <div data-table /> }));

let root: Root;
let container: HTMLElement;

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <TooltipProvider>
          <AchievementsPage />
        </TooltipProvider>
      </QueryClientProvider>
    );
  });
}

async function openMenu() {
  const trigger = container.querySelector('button[aria-label="More actions"]');
  expect(trigger).toBeTruthy();
  await act(async () => {
    trigger!.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0 }));
  });
}

const item = (label: string) =>
  Array.from(document.querySelectorAll('[role="menuitem"]')).find((node) => node.textContent?.startsWith(label));
const PER_GAME = ["Export JSON", "Seed defaults", "Hard reset"];
const evaluateButton = () =>
  [...container.querySelectorAll("button")].find((node) => node.textContent === "Evaluate achievements");

beforeEach(() => {
  scopeGame.value = null;
  navigation.reset("/admin/achievements");
  document.body.innerHTML = "";
  container = document.body.appendChild(document.createElement("div"));
  root = createRoot(container);
  // A saved scope and a last game from the site: the admin reads neither.
  useWorkspaceStore.setState({ currentWorkspaceId: 7, gameScope: "lol", lastGame: "lol" });
});

afterEach(async () => {
  await act(async () => root.unmount());
});

async function openCreate() {
  const create = [...container.querySelectorAll("button")].find((node) => node.textContent === "Create achievement");
  await act(async () => create?.click());
  return container.querySelector("[data-form-game]")?.getAttribute("data-form-game");
}

describe("/admin/achievements per filtered game", () => {
  it("disables the per-game bulk actions without a filtered game, says why in text, and keeps import", async () => {
    await mount();

    // Evaluate stays in the header, disabled, described by a visible reason.
    const evaluate = evaluateButton();
    expect(evaluate?.disabled).toBe(true);
    const reason = document.getElementById(evaluate!.getAttribute("aria-describedby")!);
    expect(reason?.textContent).toBe("Pick a game in the filter");

    await openMenu();
    for (const label of PER_GAME) {
      expect(item(label)?.hasAttribute("data-disabled"), label).toBe(true);
      expect(item(label)?.textContent, label).toContain("Pick a game in the filter");
    }
    expect(item("Import…")?.hasAttribute("data-disabled")).toBe(false);
  });

  it("acts on the filtered game", async () => {
    scopeGame.value = "lol";
    await mount();

    expect(evaluateButton()?.disabled).toBe(false);
    expect(evaluateButton()?.hasAttribute("aria-describedby")).toBe(false);
    await openMenu();
    for (const label of PER_GAME) expect(item(label)?.hasAttribute("data-disabled"), label).toBe(false);
  });

  it("starts a new rule in the filtered game", async () => {
    scopeGame.value = "lol";
    await mount();

    expect(await openCreate()).toBe("lol");
  });

  it("starts a new rule in the first enabled game without a filtered game", async () => {
    await mount();

    expect(await openCreate()).toBe("overwatch");
  });
});
