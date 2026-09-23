// @vitest-environment happy-dom
//
// The chrome both workspace-settings shells share. What is pinned here:
//  1. section <-> route: the URL alone decides the heading and which rail item
//     is current, so a shared link opens the section it names;
//  2. a child screen of a section keeps that section current —
//     `/admin/settings/divisions/import` is Divisions, not a blank rail. The
//     active key comes from the first segment after `basePath`, never the last
//     segment of the path;
//  3. the superuser shell (`/admin/workspaces/[id]`) rails only the sections it
//     actually routes, so it cannot link to a 404.
import { act, forwardRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WORKSPACE_RECORD_SECTIONS } from "./sections";
import { WorkspaceSettingsShell } from "./WorkspaceSettingsShell";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let pathname = "/admin/settings/general";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
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

let container: HTMLDivElement;
let root: Root;

async function render(node: React.ReactNode) {
  await act(async () => root.render(node));
}

/** The rail's links only — the narrow-viewport `Select` renders the same list. */
function railLinks() {
  return [...container.querySelectorAll("nav a")] as HTMLAnchorElement[];
}

function currentLabel() {
  return container.querySelector('nav a[aria-current="page"]')?.textContent?.trim();
}

beforeEach(() => {
  pathname = "/admin/settings/general";
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("WorkspaceSettingsShell", () => {
  it("names the section the URL points at, and makes exactly that rail item current", async () => {
    pathname = "/admin/settings/branding";
    await render(
      <WorkspaceSettingsShell basePath="/admin/settings">
        <p>section body</p>
      </WorkspaceSettingsShell>
    );

    expect(container.querySelector("h1")?.textContent).toBe("Branding");
    expect(currentLabel()).toBe("Branding");
    expect(container.querySelectorAll('nav a[aria-current="page"]')).toHaveLength(1);
    expect(container.textContent).toContain("section body");
  });

  it("keeps a section current for its child screens", async () => {
    pathname = "/admin/settings/divisions/import";
    await render(
      <WorkspaceSettingsShell basePath="/admin/settings">
        <p>import wizard</p>
      </WorkspaceSettingsShell>
    );

    expect(container.querySelector("h1")?.textContent).toBe("Divisions");
    expect(currentLabel()).toBe("Divisions");
  });

  it("stands aside entirely for the full-screen division-grid editor", async () => {
    // Next.js nests layouts: the editor's own `v/layout.tsx` cannot remove this
    // one, so the header and the rail would eat a column of its three-column
    // workspace unless the chrome itself steps out of the way.
    pathname = "/admin/settings/divisions/v/12";
    await render(
      <WorkspaceSettingsShell basePath="/admin/settings">
        <p>grid editor</p>
      </WorkspaceSettingsShell>
    );

    expect(container.textContent).toBe("grid editor");
    expect(container.querySelector("h1")).toBeNull();
    expect(container.querySelector("nav")).toBeNull();
  });

  it("rails all twelve sections of the workspace hub", async () => {
    await render(
      <WorkspaceSettingsShell basePath="/admin/settings">
        <p />
      </WorkspaceSettingsShell>
    );

    expect(railLinks().map((link) => link.getAttribute("href"))).toEqual([
      "/admin/settings/general",
      "/admin/settings/branding",
      "/admin/settings/visibility",
      "/admin/settings/domain",
      "/admin/settings/discord",
      "/admin/settings/notifications",
      "/admin/settings/divisions",
      "/admin/settings/statuses",
      "/admin/settings/sub-roles",
      "/admin/settings/registration-forms",
      "/admin/settings/subscriptions",
      "/admin/settings/quota"
    ]);
  });

  it("rails only the routed sections under a workspace id", async () => {
    pathname = "/admin/workspaces/8/general";
    await render(
      <WorkspaceSettingsShell
        basePath="/admin/workspaces/8"
        sections={WORKSPACE_RECORD_SECTIONS}
      >
        <p />
      </WorkspaceSettingsShell>
    );

    expect(railLinks().map((link) => link.getAttribute("href"))).toEqual([
      "/admin/workspaces/8/general",
      "/admin/workspaces/8/branding",
      "/admin/workspaces/8/visibility",
      "/admin/workspaces/8/domain",
      "/admin/workspaces/8/discord",
      "/admin/workspaces/8/notifications"
    ]);
    expect(currentLabel()).toBe("General");
    expect(container.textContent).not.toContain("Divisions");
  });
});
