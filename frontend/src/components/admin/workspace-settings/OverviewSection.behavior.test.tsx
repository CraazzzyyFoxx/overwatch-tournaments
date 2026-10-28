// @vitest-environment happy-dom
//
// The root of both settings shells. What is pinned here:
//  1. the checklist reads the record: an icon and a bound Discord guild are
//     done, everything this workspace has not set up is not;
//  2. every "Set up" link stays inside the shell the reader is in:
//     `/admin/settings/<section>` for the current workspace,
//     `/admin/workspaces/8/<section>` for a superuser looking at another one;
//  3. the overview is read-only: it never mounts a save bar.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, forwardRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SettingsRootPage from "@/app/admin/settings/page";
import WorkspaceRootPage from "@/app/admin/workspaces/[id]/page";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Workspace } from "@/types/workspace.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getById = vi.fn();
vi.mock("@/services/workspace.service", () => ({
  default: { getById: (...args: unknown[]) => getById(...args), update: vi.fn() }
}));

let pathname = "/admin/settings";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useParams: () => ({ id: "8" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })
}));

vi.mock("next/link", () => ({
  default: forwardRef<
    HTMLAnchorElement,
    { href: string; children: React.ReactNode } & React.AnchorHTMLAttributes<HTMLAnchorElement>
  >(function Link({ href, children, ...props }, ref) {
    return (
      <a ref={ref} href={href} {...props}>
        {children}
      </a>
    );
  })
}));

vi.mock("next/image", () => ({
  default: (props: React.ImgHTMLAttributes<HTMLImageElement>) => (
    // eslint-disable-next-line @next/next/no-img-element -- this IS the next/image stand-in
    <img {...props} alt={props.alt ?? ""} />
  )
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    isLoaded: true,
    isSuperuser: true,
    isWorkspaceAdmin: () => true,
    canAccessPermission: () => true
  })
}));

vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (
    selector: (state: { currentWorkspaceId: number; fetchWorkspaces: () => void }) => unknown
  ) => selector({ currentWorkspaceId: 8, fetchWorkspaces: vi.fn() })
}));

vi.mock("@/components/kit/SaveBar", () => ({
  SaveBar: () => <div data-save-bar />
}));

const WORKSPACE: Workspace = {
  id: 8,
  slug: "rivals",
  name: "Rivals Cup",
  description: null,
  disciplines_enabled: ["overwatch"],
  tagline: null,
  about: null,
  discord_url: null,
  twitch_url: null,
  boosty_url: null,
  icon_url: "/icon.png",
  is_active: true,
  is_hidden: false,
  timezone: "UTC",
  branding_enabled: false,
  brand_primary: null,
  brand_secondary: null,
  brand_background: null,
  brand_surface: null,
  brand_accent: null,
  brand_foreground: null,
  brand_muted: null,
  brand_border: null,
  brand_ring: null,
  brand_destructive: null,
  subdomain: null,
  seo_title: null,
  seo_description: null,
  custom_domain: null,
  custom_domain_verified_at: null,
  custom_domain_verification_token: null,
  discord_guild_id: "123456789",
  discord_guild_verified_at: "2026-10-01T00:00:00Z",
  verification_status: "unverified",
  default_division_grid_versions: {},
  effective_division_grid_versions: {},
  newcomer_scope: "workspace"
};

let container: HTMLDivElement;
let root: Root;

async function render(Page: () => React.ReactElement) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
      >
        <TooltipProvider>
          <Page />
        </TooltipProvider>
      </QueryClientProvider>
    );
  });
  for (let turn = 0; turn < 4; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

/** Checklist rows by title: done or not, and where "Set up" points. */
function rows() {
  return Object.fromEntries(
    [...container.querySelectorAll('[aria-label="Setup checklist"] > li')].map((row) => [
      row.querySelector("p")?.textContent,
      {
        done: row.querySelector(".sr-only")?.textContent === "Done",
        href: row.querySelector("a")?.getAttribute("href") ?? null
      }
    ])
  );
}

beforeEach(() => {
  pathname = "/admin/settings";
  getById.mockReset().mockResolvedValue(WORKSPACE);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("Workspace settings overview", () => {
  it("marks what the record has as done and the rest as not yet", async () => {
    await render(SettingsRootPage);

    expect(getById).toHaveBeenCalledWith(8);
    expect(container.textContent).toContain("Rivals Cup");
    expect(container.textContent).toContain("/workspace/rivals");
    const done = Object.entries(rows())
      .filter(([, row]) => row.done)
      .map(([title]) => title);
    expect(done).toEqual(["Icon", "Discord server"]);
    expect(Object.keys(rows())).toHaveLength(8);
  });

  it.each([
    ["/admin/settings", SettingsRootPage],
    ["/admin/workspaces/8", WorkspaceRootPage]
  ] as const)("links each missing item into its section under %s", async (basePath, Page) => {
    pathname = basePath;
    await render(Page);

    const byTitle = rows();
    expect(byTitle["Description and tagline"].href).toBe(`${basePath}/general#community`);
    expect(byTitle["Site branding"].href).toBe(`${basePath}/branding#palette`);
    expect(byTitle["Subdomain"].href).toBe(`${basePath}/domain#address`);
    // Done items and the superuser-set verification offer nothing to click.
    expect(byTitle["Icon"].href).toBeNull();
    expect(byTitle["Discord server"].href).toBeNull();
    expect(byTitle["Platform verification"].href).toBeNull();
  });

  // The ghost of General under it is a form, but an inert preview of one.
  it("is read-only: no save bar, no form controls", async () => {
    await render(SettingsRootPage);

    const outsidePreview = (selector: string) =>
      [...container.querySelectorAll(selector)].filter((node) => !node.closest("[inert]"));
    expect(outsidePreview("[data-save-bar]")).toEqual([]);
    expect(outsidePreview("input, textarea, select, [role='switch']")).toEqual([]);
  });
});
