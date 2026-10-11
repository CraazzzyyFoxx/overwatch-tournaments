import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key
}));
vi.mock("next/image", () => ({
  // eslint-disable-next-line @next/next/no-img-element -- this IS the next/image stand-in
  default: ({ src, alt }: { src: string; alt: string }) => <img src={src} alt={alt} />
}));

import { TournamentLinkChips } from "./TournamentLinkChips";
import type { TournamentLink, TournamentLinkKind } from "@/types/stream.types";

let nextId = 1;
function link(over: Partial<TournamentLink> = {}): TournamentLink {
  return {
    id: nextId++,
    tournament_id: 1,
    kind: "discord",
    label: null,
    url: "https://discord.gg/x",
    sort_order: 0,
    is_active: true,
    ...over
  };
}

describe("TournamentLinkChips", () => {
  it("renders nothing at all when the entity was not requested", () => {
    // `undefined`, not `[]`: every read that does not opt into the `links` entity
    // omits the key, and an empty heading on a public page is noise.
    expect(renderToStaticMarkup(<TournamentLinkChips links={undefined} />)).toBe("");
  });

  it("never renders an official broadcast, even as the only link", () => {
    // The dock owns streams and renders them WITH live status and a player. A
    // second, statusless copy here is the regression this pins.
    const html = renderToStaticMarkup(
      <TournamentLinkChips links={[link({ kind: "stream", url: "https://twitch.tv/cast" })]} />
    );

    expect(html).toBe("");
  });

  it("drops a stream link but keeps the rest of the row", () => {
    const html = renderToStaticMarkup(
      <TournamentLinkChips
        links={[
          link({ kind: "stream", url: "https://twitch.tv/cast" }),
          link({ kind: "rules", url: "https://example.com/rules" })
        ]}
      />
    );

    expect(html).toContain("https://example.com/rules");
    expect(html).not.toContain("twitch.tv/cast");
  });

  it("excludes a soft-deleted link", () => {
    const html = renderToStaticMarkup(
      <TournamentLinkChips
        links={[link({ kind: "rules", url: "https://example.com/retired", is_active: false })]}
      />
    );

    expect(html).toBe("");
  });

  it("drops a bracket link that only points back at this site's bracket tab", () => {
    // The rail already has the tab and the overview already previews it; the
    // organizer's EXTERNAL bracket is the one worth a chip.
    const internal = renderToStaticMarkup(
      <TournamentLinkChips
        links={[
          link({ kind: "bracket", url: "/tournaments/gandon-cup-10/bracket?stage=3" }),
          link({ kind: "bracket", url: "https://owt.craazzzyyfoxx.me/tournaments/gandon-cup-10/bracket" })
        ]}
      />
    );
    expect(internal).toBe("");

    const external = renderToStaticMarkup(
      <TournamentLinkChips links={[link({ kind: "bracket", url: "https://challonge.com/anak" })]} />
    );
    expect(external).toContain("https://challonge.com/anak");
  });

  it("orders by sort_order, breaking ties on id like the backend does", () => {
    const html = renderToStaticMarkup(
      <TournamentLinkChips
        links={[
          { ...link({ kind: "rules", url: "https://e/third" }), id: 50, sort_order: 5 },
          { ...link({ kind: "vod", url: "https://e/second" }), id: 90, sort_order: 1 },
          { ...link({ kind: "bracket", url: "https://e/first" }), id: 10, sort_order: 1 }
        ]}
      />
    );

    // sort_order 1 twice: the lower id wins, which is why the tie-break is
    // asserted rather than the sort alone.
    const order = ["https://e/first", "https://e/second", "https://e/third"].map((u) =>
      html.indexOf(u)
    );
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(order.every((i) => i >= 0)).toBe(true);
  });

  it("falls back to the kind's name, never to the raw URL", () => {
    // A URL as the CAPTION would put tracking query strings on screen, and a
    // whitespace-only label must not render an empty chip. The url itself
    // legitimately stays in `href` — so this asserts the visible text, not the
    // markup, which is the distinction a naive `not.toContain(url)` gets wrong.
    const html = renderToStaticMarkup(
      <TournamentLinkChips
        links={[link({ kind: "vod", label: "   ", url: "https://youtube.com/p?list=X&utm=y" })]}
      />
    );
    const visibleText = html.replace(/<[^>]*>/g, "");

    expect(visibleText).toContain("tournamentDetail.links.kinds.vod");
    expect(visibleText).not.toContain("youtube.com");
  });

  it("prefers the organizer's label when there is one", () => {
    const html = renderToStaticMarkup(
      <TournamentLinkChips links={[link({ kind: "rules", label: "Ruleset v3" })]} />
    );

    expect(html).toContain("Ruleset v3");
    expect(html).not.toContain("tournamentDetail.links.kinds.rules");
  });

  it("opens every chip in a new tab without leaking the referrer", () => {
    const html = renderToStaticMarkup(
      <TournamentLinkChips links={[link({ kind: "bracket", url: "https://challonge.com/x" })]} />
    );

    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it("covers every kind the backend vocabulary declares", () => {
    // The registry is exhaustive by type, but the LABELS are message keys the
    // compiler cannot check against the backend list. Read the source of truth
    // and assert each kind renders something other than a raw enum token — the
    // same file-reading approach `tournament-shared-ui.test.tsx` already uses to
    // pin cross-boundary agreement.
    const model = readFileSync(
      resolve(process.cwd(), "../backend/shared/models/tournament/link.py"),
      "utf8"
    );
    const block = model.match(/TournamentLinkKind\s*=\s*Literal\[([^\]]*)\]/);
    expect(block).not.toBeNull();
    const kinds = [...(block?.[1] ?? "").matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
    expect(kinds).toContain("stream");
    expect(kinds.length).toBeGreaterThan(1);

    for (const kind of kinds) {
      const html = renderToStaticMarkup(
        <TournamentLinkChips links={[link({ kind: kind as TournamentLinkKind })]} />
      );
      if (kind === "stream") {
        expect(html, "stream belongs to the dock").toBe("");
        continue;
      }
      expect(html, `no chip rendered for kind "${kind}"`).not.toBe("");
      expect(html, `kind "${kind}" rendered a raw token`).toContain(
        `tournamentDetail.links.kinds.${kind}`
      );
    }
  });
});
