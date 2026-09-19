import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, mock } from "bun:test";

mock.module("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string) => `draftRedesign.${key}`
}));

const componentDir = import.meta.dirname;
const routeDir = join(componentDir, "..", "..", "app", "draft", "[id]");
const skeletonPath = join(componentDir, "DraftRoomSkeleton.tsx");
const loadingStatePath = join(componentDir, "draft-loading-state.ts");
const skeletonModule = existsSync(skeletonPath) ? await import("@/components/draft/DraftRoomSkeleton") : null;
const loadingStateModule = existsSync(loadingStatePath)
  ? await import("@/components/draft/draft-loading-state")
  : null;

function sourceFor(path: string): string {
  const absolutePath = join(componentDir, path);
  return existsSync(absolutePath) ? readFileSync(absolutePath, "utf8") : "";
}

function routeSourceFor(path: string): string {
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
    const loading = routeSourceFor("loading.tsx");
    const page = routeSourceFor("page.tsx");
    const board = sourceFor("DraftBoard.tsx");

    expect(loading).toContain('import { DraftRoomSkeleton } from "@/components/draft/DraftRoomSkeleton"');
    expect(loading).toContain("return <DraftRoomSkeleton />");
    expect(page).toContain('import { DraftRoomSkeleton } from "@/components/draft/DraftRoomSkeleton"');
    expect(page).toContain("shouldShowInitialDraftSkeleton(tournamentQuery)");
    expect(page).toContain("return <DraftRoomSkeleton />");
    expect(page).not.toContain("Loader2");

    expect(board).toContain("DraftBoardSkeleton");
    expect(board).toContain("shouldShowInitialDraftSkeleton(boardQuery)");
    expect(board).toMatch(/boardQuery\.isError\s*&&\s*!board/);
    expect(board).not.toContain("Loader2");
  });

  // The loaded room's Back action lives in DraftPageHero (rendered by
  // DraftBoard), not on this route's page.tsx -- it moved there in the draft
  // redesign, along with the breadcrumb. page.tsx kept only the error branch.
  // These assertions still pointed at page.tsx and had been failing since; the
  // file is bun:test-only and nothing in CI ran it until now.
  it("retains loaded content during background failures and preserves the real Back action", () => {
    const page = routeSourceFor("page.tsx");
    const hero = sourceFor("DraftPageHero.tsx");

    expect(page).toMatch(/tournamentQuery\.isError\s*&&\s*!tournament/);
    expect(hero).toContain("href={`/tournaments/${tournament.id}`}");
    expect(hero).toContain('aria-label={t("room.back")}');
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

  it("matches the loaded board width and the skeleton's Back-action geometry", () => {
    const css = sourceFor("DraftRoom.module.css");
    const board = sourceFor("DraftBoard.tsx");
    const hero = sourceFor("DraftPageHero.tsx");

    expect(board).toContain("max-w-[min(2000px,96vw)]");
    expect(css).toMatch(
      /\.skeletonWorkspace\s*\{[\s\S]*?max-width:\s*min\(2000px,\s*96vw\);[\s\S]*?margin-inline:\s*auto/
    );

    // 2.75rem is 44px is `h-11`: the skeleton's collapsed Back block has to
    // reserve exactly the box the hero's real Back control occupies, or the
    // first paint after the skeleton shifts. The old responsive toolbar this
    // test used to compare against (min-h-16 / room.backShort on page.tsx) no
    // longer exists anywhere -- only the skeleton side of that pairing survived.
    expect(hero).toContain("h-11 w-11");
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
