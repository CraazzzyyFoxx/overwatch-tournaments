import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";

const route = vi.hoisted(() => ({ pathname: "/" }));

vi.mock("next/navigation", () => ({ usePathname: () => route.pathname }));
vi.mock("./useCanAccessAdminEntry", () => ({ useCanAccessAdminEntry: () => false }));

// Must follow the hoisted vi.mock calls above.
import messages from "@/i18n/messages/en.json";
import { SectionTabs, SiteNav } from "./SiteNav";

function render(pathname: string, node: ReactNode): string {
  route.pathname = pathname;
  return renderToStaticMarkup(
    <NextIntlClientProvider locale="en" messages={messages}>
      {node}
    </NextIntlClientProvider>
  );
}

/** Link labels in order, each suffixed with its aria-current when it has one. */
function links(html: string): string[] {
  return [...html.matchAll(/<a ([^>]*)>([^<]+)<\/a>/g)].map(([, attrs, label]) => {
    const current = /aria-current="(\w+)"/.exec(attrs)?.[1];
    return current ? `${label}=${current}` : label;
  });
}

describe("SiteNav section links", () => {
  it("marks a section as the location from any page under it", () => {
    expect(links(render("/users", <SiteNav variant="desktop" />))).toEqual([
      "Tournaments",
      "Players=page",
      "Play"
    ]);
    // Analytics is the section's fourth page, not its landing page.
    expect(links(render("/tournaments/analytics", <SiteNav variant="desktop" />))).toContain(
      "Tournaments=true"
    );
    expect(links(render("/balancer/mix/42", <SiteNav variant="desktop" />))).toContain("Play=true");
  });

  it("marks nothing outside the tree, including a path that only shares a prefix", () => {
    for (const pathname of ["/", "/users-archive"]) {
      expect(links(render(pathname, <SiteNav variant="desktop" />))).toEqual([
        "Tournaments",
        "Players",
        "Play"
      ]);
    }
  });
});

describe("SectionTabs", () => {
  it("lists the current section's pages with only the open one current", () => {
    // /tournaments/analytics also sits under /tournaments; only one may be current.
    expect(links(render("/tournaments/analytics", <SectionTabs />))).toEqual([
      "Tournaments",
      "Encounters",
      "Analytics=page"
    ]);
  });

  it("stays out of detail pages, which carry their own tab row", () => {
    expect(render("/tournaments/winter-cup/bracket", <SectionTabs />)).toBe("");
    expect(render("/users/some-player", <SectionTabs />)).toBe("");
    expect(render("/", <SectionTabs />)).toBe("");
  });
});
