// @vitest-environment happy-dom
//
// The one tab row for the admin panel. What is pinned here:
//  1. the active tab carries `aria-current="page"` and no other tab does —
//     routed tabs have no `role=tab`, so this attribute is the whole state;
//  2. `hidden` items are not rendered at all (a permission-gated sub-tab must
//     not be reachable by tabbing to a disabled link);
//  3. ←/→ move focus along the row, because dropping Radix `Tabs` (its roving
//     tabindex breaks a nested sub-tab row) also dropped its arrow keys;
//  4. a badge renders its count, and no badge renders when the count is 0.
import { act, forwardRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminTabs, type AdminTabItem } from "@/components/kit/AdminTabs";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Plain anchor stand-in: next/link's app-router context is not mounted here,
// and this component is asserted on its markup, not on routing.
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

const ITEMS: AdminTabItem[] = [
  { key: "overview", label: "Overview", href: "/admin/tournaments/1/overview" },
  { key: "registration", label: "Registration", href: "/admin/tournaments/1/registration" },
  { key: "teams", label: "Teams", href: "/admin/tournaments/1/teams", badge: 3 },
  { key: "draft", label: "Draft", href: "/admin/tournaments/1/teams/draft", hidden: true },
  {
    key: "matches",
    label: "Matches",
    href: "/admin/tournaments/1/matches",
    badge: 0,
    dot: { tone: "warning", label: "Degraded" }
  }
];

let container: HTMLElement;
let root: Root;

async function render(activeKey = "teams") {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<AdminTabs items={ITEMS} activeKey={activeKey} ariaLabel="Tournament sections" />);
  });
}

function links() {
  return Array.from(container.querySelectorAll<HTMLAnchorElement>("a[data-admin-tab]"));
}

async function keyDown(key: string) {
  await act(async () => {
    document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
  });
}

beforeEach(() => {
  container = document.createElement("div");
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

describe("AdminTabs", () => {
  it("marks exactly the active tab with aria-current", async () => {
    await render("teams");

    const current = links().filter((link) => link.getAttribute("aria-current") === "page");
    expect(current).toHaveLength(1);
    expect(current[0].textContent).toContain("Teams");
  });

  it("does not render hidden items", async () => {
    await render();

    expect(links().map((link) => link.dataset.adminTab)).toEqual([
      "overview",
      "registration",
      "teams",
      "matches"
    ]);
  });

  it("names the row for assistive technology", async () => {
    await render();

    expect(container.querySelector("nav")?.getAttribute("aria-label")).toBe("Tournament sections");
  });

  it("moves focus with the arrow keys and wraps at both ends", async () => {
    await render();
    const all = links();

    all[0].focus();
    await keyDown("ArrowRight");
    expect(document.activeElement).toBe(all[1]);

    await keyDown("ArrowLeft");
    expect(document.activeElement).toBe(all[0]);

    // Wrap backwards from the first tab to the last.
    await keyDown("ArrowLeft");
    expect(document.activeElement).toBe(all[all.length - 1]);
  });

  it("renders a badge only for a non-zero count", async () => {
    await render();

    const teams = links().find((link) => link.dataset.adminTab === "teams");
    const matches = links().find((link) => link.dataset.adminTab === "matches");
    expect(teams?.textContent).toContain("3");
    // The dot's sr-only word rides along; what must be absent is a "0" pill.
    expect(matches?.textContent?.trim()).toBe("DegradedMatches");
    expect(matches?.querySelector(".tabular-nums")).toBeNull();
  });

  it("gives the health dot a word, never colour alone", async () => {
    await render();

    const matches = links().find((link) => link.dataset.adminTab === "matches");
    expect(matches?.querySelector("span[aria-hidden]")).not.toBeNull();
    // The design book bans colour-only encoding: the tone always ships with
    // the state spelled out for assistive tech.
    expect(matches?.querySelector(".sr-only")?.textContent).toBe("Degraded");
  });
});
