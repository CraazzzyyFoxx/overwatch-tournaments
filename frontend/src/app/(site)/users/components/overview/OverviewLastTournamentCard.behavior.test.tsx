// @vitest-environment happy-dom
//
// A player entered in a tournament that has no recorded maps yet (not played,
// or results not uploaded) gets an all-zero payload. Rendered literally that is
// "Placed 0 · 0m playtime · 0 maps · 0W · 0L", which reads as lost data — the
// card must say there is no data yet instead.
import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { UserTournamentWithStats } from "@/types/user.types";

vi.mock("next/navigation", () => ({
  usePathname: () => "/users/Player-1",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: () => {}, replace: () => {} })
}));
vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));
vi.mock("@/app/(site)/users/components/overview/LobbyLeaderboardModal", () => ({ default: () => null }));

import OverviewLastTournamentCard from "./OverviewLastTournamentCard";

function tournament(over: Partial<UserTournamentWithStats> = {}): UserTournamentWithStats {
  return {
    id: 5,
    name: "Spring Cup #5",
    division: 5,
    division_grid_version: null,
    role: "Damage",
    group_placement: 0,
    playoff_placement: 0,
    maps_won: 0,
    maps: 0,
    playtime: 0,
    stats: {} as UserTournamentWithStats["stats"],
    ...over
  };
}

function render(t: UserTournamentWithStats) {
  return renderToStaticMarkup(
    <NextIntlClientProvider locale="en" messages={en}>
      <OverviewLastTournamentCard tournament={t} tournaments={[]} userId={1} mapPips={[]} />
    </NextIntlClientProvider>
  );
}

describe("OverviewLastTournamentCard without recorded maps", () => {
  it("states that there is no data instead of printing zeros", () => {
    const html = render(tournament());

    expect(html).toContain(en.users.overview.lastTournament.noData);
    expect(html).not.toContain(en.users.overview.lastTournament.placed);
    expect(html).not.toContain(en.users.overview.lastTournament.mapWinrate);
  });

  it("shows the real numbers once the tournament has maps", () => {
    const html = render(tournament({ maps: 10, maps_won: 2, group_placement: 14, playtime: 6660 }));

    expect(html).not.toContain(en.users.overview.lastTournament.noData);
    expect(html).toContain(en.users.overview.lastTournament.placed);
    expect(html).toContain(">14<");
  });
});
