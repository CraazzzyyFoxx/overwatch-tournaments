import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, mock } from "bun:test";

// Module mocks are process-wide in bun: every mock of next-intl in the draft
// suite exposes the same hooks, or whichever file loads first breaks the rest.
mock.module("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string) => `draftRedesign.${key}`
}));
mock.module("@/lib/datetime/client", () => ({
  useFormatter: () => ({ dateTime: () => "", number: (value: number) => String(value), relativeTime: () => "" })
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

  it("matches the loaded room: header, clock strip, pool and teams panels", () => {
    expect(skeletonModule).not.toBeNull();
    if (!skeletonModule) return;

    for (const Skeleton of [skeletonModule.DraftRoomSkeleton, skeletonModule.DraftBoardSkeleton]) {
      const html = renderToStaticMarkup(React.createElement(Skeleton));

      for (const region of [
        "header",
        "back-action",
        "status-pill",
        "clock-strip",
        "timer",
        "tick-track",
        "pool",
        "teams"
      ]) {
        expect(html).toContain(`data-draft-skeleton="${region}"`);
      }

      expect(html.match(/data-draft-skeleton="pool-row"/g)?.length).toBeGreaterThanOrEqual(6);
      expect(html.match(/data-draft-skeleton="team-row"/g)?.length).toBeGreaterThanOrEqual(4);
    }
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

  it("contains the 360px layout and disables shimmer for reduced motion", () => {
    const css = sourceFor("DraftRoom.module.css");

    expect(css).toMatch(/\.skeletonRoom\s*\{[\s\S]*?overflow-x:\s*clip/);
    expect(css).toMatch(/\.skeletonPanel\s*\{[\s\S]*?min-width:\s*0/);
    expect(css).toMatch(/@media\s*\(max-width:\s*640px\)[\s\S]*?\.skeletonHeaderRow/);
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
    expect(css).toMatch(/prefers-reduced-motion:[\s\S]*?\.skeletonBlock[\s\S]*?animation:\s*none/);
  });
});
