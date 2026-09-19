// @vitest-environment happy-dom
//
// The header of every T3 hub. What is pinned here:
//  1. exactly one `<h1>` — the bug `AdminPageHeader` was created to fix was
//     hand-rolled headers shipping with no heading element at all;
//  2. the middot between meta fragments is hidden from assistive tech, so a
//     screen reader does not read "dot" between every count;
//  3. the status pill renders its label, and absent status renders nothing;
//  4. `backHref` is a real link with an accessible name;
//  5. `level={2}` emits an `<h2>` instead, for an entity nested inside a hub
//     that already owns the page's `<h1>`.
import { act, forwardRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EntityHubHeader } from "@/components/kit/EntityHubHeader";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

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

let container: HTMLElement;
let root: Root;

async function render(props: Partial<React.ComponentProps<typeof EntityHubHeader>> = {}) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <EntityHubHeader
        title="Anak Cup #14"
        status={{ label: "Live", tone: "danger" }}
        meta={["Aug 30 – Sep 14", "16 teams", "42/60 encounters"]}
        backHref="/admin/tournaments"
        actions={<button type="button">Open analytics</button>}
        {...props}
      />
    );
  });
}

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

describe("EntityHubHeader", () => {
  it("renders exactly one h1 carrying the entity name", async () => {
    await render();

    const headings = container.querySelectorAll("h1");
    expect(headings).toHaveLength(1);
    expect(headings[0].textContent).toBe("Anak Cup #14");
  });

  it("renders the status pill and drops it when absent", async () => {
    await render();
    expect(container.textContent).toContain("Live");

    await act(async () => {
      root.render(<EntityHubHeader title="Anak Cup #14" meta={["16 teams"]} />);
    });
    expect(container.textContent).not.toContain("Live");
  });

  it("hides the meta separators from assistive technology", async () => {
    await render();

    const separators = [...container.querySelectorAll("span[aria-hidden]")].filter(
      (node) => node.textContent === "·"
    );
    expect(separators).toHaveLength(2);
    expect(container.textContent).toContain("16 teams");
  });

  it("renders back navigation as a named link", async () => {
    await render();

    const back = container.querySelector('a[href="/admin/tournaments"]');
    expect(back?.getAttribute("aria-label")).toBe("Back");
  });

  it("renders the actions slot", async () => {
    await render();

    expect(container.textContent).toContain("Open analytics");
  });

  it("drops to an h2 for an entity nested in a hub that owns the h1", async () => {
    await render({ level: 2 });

    // A stage inside the tournament hub: same header, one rank down, so the
    // page keeps exactly one h1 and the outline stays readable.
    expect(container.querySelectorAll("h1")).toHaveLength(0);
    const heading = container.querySelector("h2");
    expect(heading?.textContent).toBe("Anak Cup #14");
    expect(heading?.className).toContain("text-lg");
  });
});
