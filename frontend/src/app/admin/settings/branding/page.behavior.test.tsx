// @vitest-environment happy-dom
//
// One workspace settings section, and the two claims all five make:
//
//   1. the gate is the PAGE's, not the rail's. Hiding a link is not access
//      control — `/admin/settings/branding` typed into the address bar has to
//      be refused too;
//   2. a section PATCHes its own changed fields and nothing else. The
//      pre-redesign screen was one 784-line form that sent every field it
//      held on every save, so touching a brand colour recorded a rewrite of
//      the visibility flags, the domain and the SEO text in the audit trail
//      (`model_dump(exclude_unset=True)` records exactly the keys a PATCH
//      sends).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Workspace } from "@/types/workspace.types";
import BrandingSettingsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getById = vi.fn();
const update = vi.fn();

vi.mock("@/services/workspace.service", () => ({
  default: {
    getById: (...args: unknown[]) => getById(...args),
    update: (...args: unknown[]) => update(...args)
  }
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() })
}));

let workspaceAdmin = true;
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    isLoaded: true,
    isSuperuser: false,
    isWorkspaceAdmin: () => workspaceAdmin,
    canAccessPermission: () => true
  })
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), apiError: vi.fn() }
}));

const fetchWorkspaces = vi.fn();
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (
    selector: (state: { currentWorkspaceId: number; fetchWorkspaces: () => void }) => unknown
  ) => selector({ currentWorkspaceId: 7, fetchWorkspaces })
}));

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

const WORKSPACE: Workspace = {
  id: 7,
  slug: "owt",
  name: "Overwatch Tournaments",
  description: "The league",
  icon_url: null,
  is_active: true,
  is_hidden: false,
  timezone: "Europe/Moscow",
  branding_enabled: true,
  brand_primary: "#0ea5a4",
  brand_secondary: "#7c5cff",
  brand_background: "#0b0d10",
  brand_surface: "#14181d",
  brand_accent: null,
  brand_foreground: null,
  brand_muted: null,
  brand_border: null,
  brand_ring: null,
  brand_destructive: null,
  subdomain: "owt",
  seo_title: "OWT",
  seo_description: null,
  custom_domain: null,
  custom_domain_verified_at: null,
  custom_domain_verification_token: null,
  discord_guild_id: "123456789012345678",
  default_division_grid_version_id: null,
  default_division_grid_version: null,
  newcomer_scope: "global"
};

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

async function render() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
      >
        <BrandingSettingsPage />
      </QueryClientProvider>
    );
  });
  await settle();
}

/** Type into a controlled input the way React's synthetic layer sees it. */
async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      globalThis.HTMLInputElement.prototype,
      "value"
    )?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(2);
}

function button(label: string) {
  return [...document.querySelectorAll("button")].find(
    (node) => node.textContent?.trim() === label
  );
}

beforeEach(() => {
  workspaceAdmin = true;
  fetchWorkspaces.mockReset();
  getById.mockReset().mockResolvedValue(WORKSPACE);
  update.mockReset().mockResolvedValue(WORKSPACE);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("Workspace settings › Branding", () => {
  it("refuses the section to a caller who does not administer the workspace", async () => {
    workspaceAdmin = false;
    await render();

    expect(container.textContent).toContain("Not your workspace");
    expect(container.querySelector("#brand-primary")).toBeNull();
  });

  it("keeps the save bar away until something actually changed", async () => {
    await render();

    expect(container.querySelector<HTMLInputElement>("#brand-primary")?.value).toBe("#0ea5a4");
    expect(container.querySelector('[aria-label="unsavedChanges"]')).toBeNull();
  });

  it("PATCHes the edited colour alone — no visibility, domain or general field", async () => {
    await render();

    await type(container.querySelector<HTMLInputElement>("#brand-primary")!, "#ff0055");
    // next-intl is the identity here: the summary renders as its key, and the
    // PATCH below is what pins "one field".
    expect(container.querySelector('[aria-label="unsavedChanges"]')?.textContent).toContain(
      "changedFields"
    );

    await act(async () => {
      button("save")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(update).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledWith(7, { brand_primary: "#ff0055" });
    // The whole point of the section split, spelled out: Visibility's fields,
    // Domain's fields and General's fields stay out of Branding's request.
    const [, payload] = update.mock.calls[0] as [number, Record<string, unknown>];
    for (const foreign of [
      "is_hidden",
      "newcomer_scope",
      "subdomain",
      "seo_title",
      "seo_description",
      "name",
      "description",
      "timezone",
      "discord_guild_id"
    ]) {
      expect(payload).not.toHaveProperty(foreign);
    }
  });

  it("discards back to the stored palette", async () => {
    await render();

    await type(container.querySelector<HTMLInputElement>("#brand-primary")!, "#000000");
    await act(async () => {
      button("discard")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(container.querySelector<HTMLInputElement>("#brand-primary")?.value).toBe("#0ea5a4");
    expect(update).not.toHaveBeenCalled();
  });
});
