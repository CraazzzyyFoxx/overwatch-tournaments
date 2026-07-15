import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key
}));

import {
  TournamentBracketSkeleton,
  TournamentHeroesSkeleton,
  TournamentMatchesSkeleton,
  TournamentParticipantsSkeleton,
  TournamentShellSkeleton,
  TournamentStandingsSkeleton,
  TournamentTeamsSkeleton
} from "./TournamentSkeletons";
import { TournamentPageState } from "./TournamentPageState";

const tournamentRoot = resolve(process.cwd(), "src/app/(site)/tournaments/[id]");

describe("tournament skeleton compositions", () => {
  it.each([
    ["shell", TournamentShellSkeleton],
    ["bracket", TournamentBracketSkeleton],
    ["teams", TournamentTeamsSkeleton],
    ["participants", TournamentParticipantsSkeleton],
    ["matches", TournamentMatchesSkeleton],
    ["heroes", TournamentHeroesSkeleton],
    ["standings", TournamentStandingsSkeleton]
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
    ["heroes", "TournamentHeroesSkeleton"],
    ["standings", "TournamentStandingsSkeleton"]
  ])("wires %s/loading.tsx to the shared %s", (route, exportName) => {
    const source = readFileSync(resolve(tournamentRoot, route, "loading.tsx"), "utf8");

    expect(source).toContain(exportName);
    expect(source).toContain(`return <${exportName} />`);
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
    expect(Object.keys(en.tournamentDetail.nav.phase).sort()).toEqual(
      Object.keys(ru.tournamentDetail.nav.phase).sort()
    );
    expect(Object.keys(en.tournamentDetail.loading.pages).sort()).toEqual(
      Object.keys(ru.tournamentDetail.loading.pages).sort()
    );
    expect(Object.keys(en.tournamentDetail.pageState).sort()).toEqual(
      Object.keys(ru.tournamentDetail.pageState).sort()
    );
  });
});
