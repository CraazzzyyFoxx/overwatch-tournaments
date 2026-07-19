import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, mock } from "bun:test";

mock.module("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string) => `draftRedesign.${key}`
}));

const routeDir = import.meta.dirname;
const skeletonPath = join(routeDir, "DraftRoomSkeleton.tsx");
const loadingStatePath = join(routeDir, "draft-loading-state.ts");
const skeletonModule = existsSync(skeletonPath) ? await import("./DraftRoomSkeleton") : null;
const loadingStateModule = existsSync(loadingStatePath)
  ? await import("./draft-loading-state")
  : null;

function sourceFor(path: string): string {
  const absolutePath = join(routeDir, path);
  return existsSync(absolutePath) ? readFileSync(absolutePath, "utf8") : "";
}

describe("standalone Draft loading skeleton", () => {
  it("shows the initial skeleton only for an active first fetch without data", () => {
    expect(loadingStateModule).not.toBeNull();
    if (!loadingStateModule) return;

    const shouldShow = loadingStateModule.shouldShowInitialDraftSkeleton;

    expect(shouldShow({ data: undefined, isPending: true, isFetching: true })).toBe(true);
    expect(shouldShow({ data: undefined, isPending: true, isFetching: false })).toBe(false);
    expect(shouldShow({ data: undefined, isPending: false, isFetching: false })).toBe(false);
    expect(shouldShow({ data: { id: 72 }, isPending: false, isFetching: true })).toBe(false);
    expect(shouldShow({ data: { id: 72 }, isPending: false, isFetching: false })).toBe(false);
  });

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
    expect(page).toContain("shouldShowInitialDraftSkeleton(tournamentQuery)");
    expect(page).toContain("return <DraftRoomSkeleton />");
    expect(page).not.toContain("Loader2");

    expect(board).toContain("DraftBoardSkeleton");
    expect(board).toContain("shouldShowInitialDraftSkeleton(boardQuery)");
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

  it("matches the loaded board width and mobile Back toolbar geometry", () => {
    const css = sourceFor("DraftRoom.module.css");
    const page = sourceFor("page.tsx");
    const board = sourceFor("../../(site)/tournaments/[id]/draft/_components/DraftBoard.tsx");

    expect(board).toContain("max-w-[min(2000px,96vw)]");
    expect(css).toMatch(
      /\.skeletonWorkspace\s*\{[\s\S]*?max-width:\s*min\(2000px,\s*96vw\);[\s\S]*?margin-inline:\s*auto/
    );

    expect(page).toContain("min-h-16");
    expect(page).toContain("gap-4");
    expect(page).toContain("px-4");
    expect(page).toContain("min-h-11");
    expect(page).toContain("gap-2");
    expect(page).toContain("px-3");
    expect(page).toContain('t("room.backShort")');
    expect(css).toMatch(
      /\.skeletonToolbarInner\s*\{[\s\S]*?min-height:\s*4rem;[\s\S]*?gap:\s*1rem/
    );
    expect(css).toMatch(
      /@media \(max-width:\s*640px\)[\s\S]*?\.skeletonBackAction\s*\{[\s\S]*?width:\s*6rem;[\s\S]*?min-width:\s*6rem;[\s\S]*?gap:\s*0\.5rem;[\s\S]*?padding-inline:\s*0\.75rem/
    );
    expect(css).toMatch(
      /@media \(max-width:\s*640px\)[\s\S]*?\.skeletonBackLabel\s*\{[\s\S]*?display:\s*block;[\s\S]*?width:\s*2\.75rem/
    );
    expect(css).toMatch(
      /@media \(max-width:\s*640px\)[\s\S]*?\.skeletonToolbarName\s*\{[\s\S]*?padding-left:\s*1rem/
    );
  });
});
