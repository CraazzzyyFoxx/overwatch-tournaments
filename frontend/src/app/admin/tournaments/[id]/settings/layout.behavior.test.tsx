// @vitest-environment happy-dom
//
// The settings rail. What is pinned here:
//  1. every section of `SETTINGS_SECTIONS` reaches the rail — the labels and
//     the groups are two separate lists, and a section in neither is a page
//     with no way in;
//  2. a section the caller may not open is absent, not disabled: pre-game
//     follows `match.update`, links `tournament_link.read`, danger
//     `tournament.delete`;
//  3. the rail is navigation only — no query of its own beyond the tournament
//     the hub shell has already cached.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, forwardRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SETTINGS_SECTIONS } from "../tab-guards";
import { SETTINGS_SECTION_LABELS } from "./settings-sections";
import TournamentSettingsLayout from "./layout";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getTournament = vi.fn();
vi.mock("@/services/admin.service", () => ({
  default: { getTournament: (...args: unknown[]) => getTournament(...args) }
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "14" }),
  usePathname: () => "/admin/tournaments/14/settings/rules",
  useRouter: () => ({ push: vi.fn() })
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

let granted: string[] = [];
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    isLoaded: true,
    canAccessPermission: (permission: string) => granted.includes(permission)
  })
}));

let container: HTMLDivElement;
let root: Root;

async function render() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
      >
        <TournamentSettingsLayout>
          <p>section body</p>
        </TournamentSettingsLayout>
      </QueryClientProvider>
    );
  });
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
}

function railLabels() {
  return [...container.querySelectorAll("nav a")].map((link) => link.textContent);
}

beforeEach(() => {
  getTournament.mockReset().mockResolvedValue({
    id: 14,
    workspace_id: 3,
    team_formation: "balancer"
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("Settings rail", () => {
  it("offers every section, in rail order, to a caller who may open them all", async () => {
    granted = [
      "tournament.update",
      "match.update",
      "tournament_link.read",
      "tournament.delete",
      "team.create"
    ];
    await render();

    expect(railLabels()).toEqual(SETTINGS_SECTIONS.map((key) => SETTINGS_SECTION_LABELS[key]));
    expect(container.textContent).toContain("section body");
  });

  it("omits the sections this caller may not open", async () => {
    granted = ["tournament.update"];
    await render();

    const labels = railLabels();
    expect(labels).toContain("General");
    expect(labels).not.toContain("Pre-game phase");
    expect(labels).not.toContain("Links");
    expect(labels).not.toContain("Delete tournament");
    // Both registration sections write the form, which needs `team.create`.
    expect(labels).not.toContain("Admission");
  });

  it("marks the section named by the path", async () => {
    granted = ["tournament.update"];
    await render();

    const current = [...container.querySelectorAll("nav a")].filter(
      (link) => link.getAttribute("aria-current") === "page"
    );
    expect(current.map((link) => link.textContent)).toEqual(["Rules & scoring"]);
  });
});
