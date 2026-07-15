import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, mock } from "bun:test";

mock.module("next-intl", () => ({
  useTranslations: () => (key: string) => `draftRedesign.${key}`
}));

const routeDir = import.meta.dirname;
const skeletonPath = join(routeDir, "DraftRoomSkeleton.tsx");
const skeletonModule = existsSync(skeletonPath) ? await import("./DraftRoomSkeleton") : null;

function sourceFor(path: string): string {
  const absolutePath = join(routeDir, path);
  return existsSync(absolutePath) ? readFileSync(absolutePath, "utf8") : "";
}

describe("standalone Draft loading skeleton", () => {
  it("renders one localized busy region around non-interactive Draft geometry", () => {
    expect(skeletonModule).not.toBeNull();
    if (!skeletonModule) return;

    const html = renderToStaticMarkup(React.createElement(skeletonModule.DraftRoomSkeleton));

    expect(html.match(/role="status"/g)).toHaveLength(1);
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain("draftRedesign.loadingTitle");
    expect(html).toContain('aria-hidden="true"');
    expect(html).not.toMatch(/<(?:a|button|h[1-6])\b/);
    expect(html).not.toMatch(/Loader2|animate-spin|spinner/i);
  });

  it("matches the standalone toolbar, hero, timer, controls, rosters and pick slots", () => {
    expect(skeletonModule).not.toBeNull();
    if (!skeletonModule) return;

    const html = renderToStaticMarkup(React.createElement(skeletonModule.DraftRoomSkeleton));

    for (const region of [
      "toolbar",
      "back-action",
      "standalone-hero",
      "status-summary",
      "board-controls",
      "timer",
      "roster-left",
      "board",
      "roster-right"
    ]) {
      expect(html).toContain(`data-draft-skeleton="${region}"`);
    }

    expect(html.match(/data-draft-skeleton="pick-slot"/g)?.length).toBeGreaterThanOrEqual(6);
  });

  it("uses the canonical composition in route and client initial loading states", () => {
    const loading = sourceFor("loading.tsx");
    const page = sourceFor("page.tsx");
    const board = sourceFor("../../(site)/tournaments/[id]/draft/_components/DraftBoard.tsx");

    expect(loading).toContain('import { DraftRoomSkeleton } from "./DraftRoomSkeleton"');
    expect(loading).toContain("return <DraftRoomSkeleton />");
    expect(page).toContain('import { DraftRoomSkeleton } from "./DraftRoomSkeleton"');
    expect(page).toMatch(/tournamentQuery\.isPending\s*&&\s*!tournament/);
    expect(page).toContain("return <DraftRoomSkeleton />");
    expect(page).not.toContain("Loader2");

    expect(board).toContain("DraftBoardSkeleton");
    expect(board).toMatch(/boardQuery\.isPending\s*&&\s*!board/);
    expect(board).toMatch(/boardQuery\.isError\s*&&\s*!board/);
    expect(board).not.toContain("Loader2");
  });

  it("retains loaded content during background failures and preserves the real Back action", () => {
    const page = sourceFor("page.tsx");

    expect(page).toMatch(/tournamentQuery\.isError\s*&&\s*!tournament/);
    expect(page).toContain("href={`/tournaments/${tournamentId}`}");
    expect(page).toContain("styles.toolbar");
    expect(page).toContain("sticky top-0");
    expect(page).toContain('t("room.back")');
  });

  it("contains the 360px layout and disables shimmer for reduced motion", () => {
    const css = sourceFor("DraftRoom.module.css");

    expect(css).toMatch(/\.skeletonRoom\s*\{[\s\S]*?overflow-x:\s*clip/);
    expect(css).toMatch(/\.skeletonStage\s*\{[\s\S]*?min-width:\s*0/);
    expect(css).toMatch(/\.skeletonWorkspace\s*\{[\s\S]*?min-height:/);
    expect(css).toMatch(/@media\s*\(max-width:\s*640px\)[\s\S]*?\.skeletonWorkspace/);
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
    expect(css).toMatch(/prefers-reduced-motion:[\s\S]*?\.skeletonBlock[\s\S]*?animation:\s*none/);
  });
});
