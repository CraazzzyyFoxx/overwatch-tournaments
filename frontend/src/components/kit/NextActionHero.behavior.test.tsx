// @vitest-environment happy-dom
//
// The one thing worth doing next. What is pinned here:
//  1. the call to action is a real link, so it is keyboard-reachable and
//     middle-clickable — the tile grid it replaces used click handlers;
//  2. the arrow is decoration and stays hidden from assistive technology;
//  3. the eyebrow and the title both render, because the eyebrow is what tells
//     the reader why this item outranked the rest.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NextActionHero } from "@/components/kit/NextActionHero";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: { href: string; children: React.ReactNode } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={href} {...props}>
      {children}
    </a>
  )
}));

let container: HTMLElement;
let root: Root;

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

describe("NextActionHero", () => {
  it("renders the ranked action as a link", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(
        <NextActionHero
          eyebrow="Next action"
          title="Anak Cup #14 — 4 unconfirmed results block Round 3"
          href="/admin/tournaments/14/matches/reports?status=disputed"
          cta="Open Matches › Reports"
        />
      );
    });

    expect(container.textContent).toContain("Next action");
    expect(container.textContent).toContain("block Round 3");

    const link = container.querySelector("a");
    expect(link?.getAttribute("href")).toBe(
      "/admin/tournaments/14/matches/reports?status=disputed"
    );
    expect(link?.textContent).toContain("Open Matches › Reports");
    expect(link?.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });
});
