import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

import type { TournamentStatus } from "@/types/tournament.types";

const bracketModule = (await import("./TournamentBracketPage")) as typeof import("./TournamentBracketPage") & {
  getBracketRefetchInterval?: (status: TournamentStatus) => number | false;
};

describe("TournamentBracketPage", () => {
  it("mounts tournament realtime once from the shared client tournament layout", () => {
    const layoutSource = readFileSync(join(import.meta.dir, "../layout.tsx"), "utf8");
    const clientLayoutSource = readFileSync(
      join(import.meta.dir, "../_components/TournamentClientLayout.tsx"),
      "utf8"
    );

    expect(layoutSource).toContain("TournamentClientLayout");
    expect(layoutSource).toContain("tournamentId={tournamentId}");
    expect(clientLayoutSource).toContain("useTournamentRealtime({");
    expect(clientLayoutSource).toContain("workspaceId: tournament?.workspace_id");
  });

  it("filters playoff standings by the active stage before rendering", () => {
    const source = readFileSync(join(import.meta.dir, "TournamentBracketPage.tsx"), "utf8");

    expect(source).toContain("const stagePlayoffStandings = playoffStandings.filter(");
    expect(source).toContain("standing.stage_id === stage.id");
  });

  it.each([
    ["live", 15_000],
    ["playoffs", 15_000],
    ["registration", false],
    ["draft", false],
    ["check_in", false],
    ["completed", false],
    ["archived", false],
  ] as const)("uses the lifecycle polling policy for %s", (status, expected) => {
    expect(bracketModule.getBracketRefetchInterval?.(status)).toBe(expected);
  });

  it("uses canonical concurrent bracket queries with lean standings", () => {
    const source = readFileSync(join(import.meta.dir, "TournamentBracketPage.tsx"), "utf8");

    expect(source).toContain("tournamentQueryKeys.encounters(");
    expect(source).toContain("tournamentQueryKeys.bracketStandings(");
    expect(source).toContain("workspaceId: tournament.workspace_id");
    expect(source).toContain("includeMatchesHistory: false");
    expect(source).toContain("includeTeamGroup: false");
    expect(source).toContain("refetchInterval: getBracketRefetchInterval(tournament.status)");
    expect(source).toContain("refetchIntervalInBackground: false");
    expect(source).not.toContain("enabled:");
  });

  it("keeps stale bracket content visible during refreshes and errors", () => {
    const source = readFileSync(join(import.meta.dir, "TournamentBracketPage.tsx"), "utf8");

    expect(source).toContain("encountersQuery.isPending && !encountersQuery.data");
    expect(source).toContain("standingsQuery.isPending && !standingsQuery.data");
    expect(source).toContain('state="initial-error"');
    expect(source).toContain('state="refresh-error"');
    expect(source).toContain("isFetching");
    expect(source).toContain(
      "(encountersQuery.isFetching || standingsQuery.isFetching) && !hasRefreshError ?"
    );
    expect(source).toContain('t("tournamentDetail.pageState.updating")');
  });
});
