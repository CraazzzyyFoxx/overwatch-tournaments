import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string) => key
}));

// The shell fallback reserves the header its route will get, so it reads the
// pathname; every other skeleton ignores it.
let pathname = "/tournaments/anak-cup";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname
}));

import {
  TournamentBracketSkeleton,
  TournamentHeroesSkeleton,
  TournamentMatchesSkeleton,
  TournamentParticipantsSkeleton,
  TournamentShellSkeleton,
  TournamentTeamsSkeleton
} from "./TournamentSkeletons";
import { TournamentPageState } from "./TournamentPageState";

const tournamentRoot = resolve(process.cwd(), "src/app/(site)/tournaments/[slug]");

describe("tournament skeleton compositions", () => {
  it.each([
    ["shell", TournamentShellSkeleton],
    ["bracket", TournamentBracketSkeleton],
    ["teams", TournamentTeamsSkeleton],
    ["participants", TournamentParticipantsSkeleton],
    ["matches", TournamentMatchesSkeleton],
    ["heroes", TournamentHeroesSkeleton]
  ] as const)("gives the %s region exactly one loading announcement", (variant, Component) => {
    const html = renderToStaticMarkup(<Component />);

    expect(html.match(/role="status"/g)).toHaveLength(1);
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain(`data-skeleton-variant="${variant}"`);
    expect(html).toContain('aria-hidden="true"');
  });

  it.each([
    ["bracket", "TournamentBracketSkeleton"],
    ["teams", "TournamentTeamsSkeleton"],
    ["participants", "TournamentParticipantsSkeleton"],
    ["matches", "TournamentMatchesSkeleton"],
    ["stats", "TournamentHeroesSkeleton"]
  ])("wires %s/loading.tsx to the shared %s", (route, exportName) => {
    const source = readFileSync(resolve(tournamentRoot, route, "loading.tsx"), "utf8");

    expect(source).toContain(exportName);
    expect(source).toContain(`return <${exportName} />`);
  });

  it("matches the Bracket hierarchy and reserves the header the shell will render", () => {
    const skeletonSource = readFileSync(
      resolve(tournamentRoot, "_components/TournamentSkeletons.tsx"),
      "utf8"
    );
    const bracketSource = readFileSync(
      resolve(tournamentRoot, "bracket/TournamentBracketPage.tsx"),
      "utf8"
    );
    const shellSource = skeletonSource.slice(
      skeletonSource.indexOf("export function TournamentShellSkeleton"),
      skeletonSource.indexOf("export function TournamentBracketSkeleton")
    );
    const bracketSkeletonSource = skeletonSource.slice(
      skeletonSource.indexOf("export function TournamentBracketSkeleton"),
      skeletonSource.indexOf("export function TournamentTeamsSkeleton")
    );

    expect(bracketSource).toContain('data-page-section="bracket"');
    expect(bracketSource).not.toContain('className="section-head"');
    expect(skeletonSource).not.toContain("PageHeadingSkeleton");
    expect(bracketSkeletonSource).toContain('data-skeleton-region="bracket-toolbar"');
    expect(bracketSkeletonSource).not.toContain("<ControlRowSkeleton />");
    expect(shellSource).not.toContain("styles.skeletonGrid");
  });

  it("falls back to the hero on the overview and to the one-row header elsewhere", () => {
    // `aqt-hero-tint` is the cover-less hero's own wash: present means the full
    // ~220px hero was reserved, absent means the compact header the shell
    // actually renders on a section route.
    pathname = "/tournaments/anak-cup";
    expect(renderToStaticMarkup(<TournamentShellSkeleton />)).toContain("aqt-hero-tint");

    for (const section of ["/tournaments/anak-cup/bracket", "/tournaments/anak-cup/teams/"]) {
      pathname = section;
      const html = renderToStaticMarkup(<TournamentShellSkeleton />);
      expect(html).not.toContain("aqt-hero-tint");
      expect(html).toContain('data-shell-region="compact-header"');
    }

    pathname = "/tournaments/anak-cup";
  });
});

describe("TournamentPageState", () => {
  it("keeps stale content visible with a refresh error and retry action", () => {
    const html = renderToStaticMarkup(
      <TournamentPageState state="refresh-error" onRetry={() => undefined} isUpdating>
        <p>preserved result</p>
      </TournamentPageState>
    );

    expect(html).toContain("preserved result");
    expect(html).toContain("tournamentDetail.pageState.refreshError.title");
    expect(html).toContain("tournamentDetail.pageState.retry");
    expect(html.match(/role="status"/g)).toHaveLength(1);
    expect(html).toContain('aria-live="polite"');
    expect(html).not.toContain('role="alert"');
  });

  it("distinguishes initial error, true empty, and filtered empty actions", () => {
    const initial = renderToStaticMarkup(
      <TournamentPageState state="initial-error" onRetry={() => undefined} />
    );
    const empty = renderToStaticMarkup(<TournamentPageState state="empty" />);
    const filtered = renderToStaticMarkup(
      <TournamentPageState state="filtered-empty" onReset={() => undefined} />
    );

    expect(initial).toContain("tournamentDetail.pageState.initialError.title");
    expect(initial).toContain("tournamentDetail.pageState.retry");
    expect(empty).toContain("tournamentDetail.pageState.empty.title");
    expect(empty).not.toContain("<button");
    expect(filtered).toContain("tournamentDetail.pageState.filteredEmpty.title");
    expect(filtered).toContain("tournamentDetail.pageState.resetFilters");

    // Only the failure the user did not cause is announced assertively; the two
    // empty states are polite. This comes from the shared PageStateCard now.
    expect(initial).toContain('role="alert"');
    expect(empty).toContain('role="status"');
    expect(filtered).toContain('role="status"');
  });

  it("renders the three terminal states through the shared PageStateCard", () => {
    const source = readFileSync(resolve(tournamentRoot, "_components/TournamentPageState.tsx"), "utf8");

    expect(source).toContain('from "@/components/ui/page-state-card"');
    // Only `refresh-error` keeps a bespoke body, because it is the one state
    // that must render below stale content instead of replacing it.
    expect(source).toContain("styles.refreshState");
    expect(source).not.toContain("styles.stateCard");
  });
});

describe("tournament navigation and loading source contracts", () => {
  it("keeps overflow operable and locked items focusable", () => {
    const source = readFileSync(
      resolve(tournamentRoot, "_components/TournamentSectionNav.tsx"),
      "utf8"
    );

    expect(source).toContain("aria-disabled={!item.available || undefined}");
    expect(source).toContain('type="button"');
    expect(source).not.toContain("disabled={!item.available}");
    expect(source).toContain("observeTournamentRail");
    expect(source).toContain("scrollTournamentRail");
    expect(source).toContain("disabled={!railState.hasOverflow || !railState.canScrollPrevious}");
    expect(source).toContain("disabled={!railState.hasOverflow || !railState.canScrollNext}");
    expect(source).toContain("styles.scrollControlHidden");
    expect(source).toContain("measurementContainer: frame");
    expect(source).toContain("styles.railFrameWithControls");
    expect(source).toContain('inline: "center"');
    expect(source).toContain("scrollIntoView");
  });

  it("contains sticky overflow at 360px and disables motion when requested", () => {
    const css = readFileSync(resolve(tournamentRoot, "TournamentDetail.module.css"), "utf8");

    expect(css).toMatch(/position:\s*sticky/);
    expect(css).toMatch(/overflow-x:\s*auto/);
    expect(css).toMatch(/max-width:\s*100%/);
    expect(css).toMatch(
      /\.railFrame\s*\{[\s\S]*?grid-template-columns:\s*0\s+minmax\(0,\s*1fr\)\s+0/
    );
    expect(css).toMatch(
      /\.railFrameWithControls\s*\{[\s\S]*?grid-template-columns:\s*2rem\s+minmax\(0,\s*1fr\)\s+2rem/
    );
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
    expect(css).toMatch(/animation:\s*none/);
  });

  it("keeps the Teams skeleton at one mobile and two desktop columns", () => {
    const skeletonSource = readFileSync(
      resolve(tournamentRoot, "_components/TournamentSkeletons.tsx"),
      "utf8"
    );
    const css = readFileSync(resolve(tournamentRoot, "TournamentDetail.module.css"), "utf8");

    expect(skeletonSource).toContain("styles.teamsSkeletonGrid");
    expect(css).toMatch(
      /\.teamsSkeletonGrid\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\)/
    );
    expect(css).toMatch(
      /@media \(min-width:\s*641px\)[\s\S]*?\.teamsSkeletonGrid\s*\{[\s\S]*?repeat\(2,\s*minmax\(0,\s*1fr\)\)/
    );
  });
});

describe("tournament detail locale parity", () => {
  it("keeps all new navigation/loading/page-state paths synchronized", () => {
    const en = JSON.parse(
      readFileSync(resolve(process.cwd(), "src/i18n/messages/en.json"), "utf8")
    );
    const ru = JSON.parse(
      readFileSync(resolve(process.cwd(), "src/i18n/messages/ru.json"), "utf8")
    );

    expect(Object.keys(en.tournamentDetail.nav.reasons).sort()).toEqual(
      Object.keys(ru.tournamentDetail.nav.reasons).sort()
    );
    expect(Object.keys(en.tournamentDetail.loading.pages).sort()).toEqual(
      Object.keys(ru.tournamentDetail.loading.pages).sort()
    );
    expect(Object.keys(en.tournamentDetail.pageState).sort()).toEqual(
      Object.keys(ru.tournamentDetail.pageState).sort()
    );
    expect(Object.keys(en.tournamentDetail.publicPages).sort()).toEqual(
      Object.keys(ru.tournamentDetail.publicPages).sort()
    );
    expect(en.tournamentDetail.publicPages.matches).toBeDefined();
    expect(ru.tournamentDetail.publicPages.matches).toBeDefined();
  });
});
