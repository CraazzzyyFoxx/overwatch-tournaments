// @vitest-environment happy-dom
//
// The Rules section renders the organizer's published document. What is pinned:
//
//  1. the document is rendered as Markdown, not as raw text — a heading is a
//     heading and a pipe table is a table;
//  2. author-written HTML stays inert on a public page;
//  3. an unpublished (or cleared) document is an honest `TournamentPageState`
//     empty card, because the URL stays reachable after the rail drops the tab.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Tournament } from "@/types/tournament.types";

import TournamentRulesPage from "./TournamentRulesPage";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SLUG = "anak-open";
const getPublicOverview = vi.fn();

vi.mock("@/services/tournament.service", () => ({
  default: { getPublicOverview: (...args: unknown[]) => getPublicOverview(...args) }
}));

function tournament(rules: string | null): Tournament {
  return { id: 7, slug: SLUG, name: "Anak Open", rules } as unknown as Tournament;
}

let container: HTMLDivElement;
let root: Root;
let client: QueryClient;

/** Let queued promise callbacks and React Query's own scheduling drain. */
async function settle(ticks = 4) {
  for (let i = 0; i < ticks; i += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount() {
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <TournamentRulesPage slug={SLUG} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
  return container;
}

beforeEach(() => {
  getPublicOverview.mockReset();
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  client.clear();
});

describe("Tournament Rules section", () => {
  it("renders the published document as Markdown, with HTML left inert", async () => {
    getPublicOverview.mockResolvedValue(
      tournament("# Format\n\n| Round | Best of |\n| --- | --- |\n| Final | 5 |\n\n<b>bold?</b>")
    );

    const html = await mount();

    expect(html.querySelector("h2")?.textContent).toBe("Format");
    expect(html.querySelectorAll("th")).toHaveLength(2);
    expect(html.querySelector("b")).toBeNull();
    expect(html.textContent).toContain("<b>bold?</b>");
  });

  it("shows the empty card when nothing is published", async () => {
    // Whitespace only: the same state as `null`, because that is exactly what
    // clearing the editor sends (the form normalises blank to `null`).
    getPublicOverview.mockResolvedValue(tournament("   \n  "));

    const html = await mount();

    expect(html.textContent).toContain(en.tournamentDetail.rules.emptyTitle);
    expect(html.querySelector("h2")).toBeNull();
  });

  it("links every table-of-contents entry to a heading that exists", async () => {
    getPublicOverview.mockResolvedValue(
      tournament(
        "# Regulations\n\n## Формат **турнира**\n\nProse.\n\n### Чек-ин\n\nProse.\n\n```\n## not a section\n```\n\n## Замены\n\nProse."
      )
    );

    const html = await mount();

    // Two rails are mounted (the collapsed one for small viewports and the
    // sticky one); CSS decides which is visible, so read the first.
    const nav = html.querySelector("nav");
    const targets = [...(nav?.querySelectorAll("a") ?? [])].map((a) => a.getAttribute("href"));
    // `#` is the document title, the fenced line is code, and emphasis inside a
    // heading is not part of its text.
    expect(targets).toEqual(["#формат-турнира", "#чек-ин", "#замены"]);
    for (const target of targets) {
      expect(html.querySelector(`[id="${target?.slice(1)}"]`)).not.toBeNull();
    }
  });

  it("drops the rail when the document has a single section", async () => {
    getPublicOverview.mockResolvedValue(tournament("## Format\n\nOne section only."));

    const html = await mount();

    expect(html.querySelector("nav")).toBeNull();
    expect(html.querySelector("h3")?.textContent).toBe("Format");
  });
});
