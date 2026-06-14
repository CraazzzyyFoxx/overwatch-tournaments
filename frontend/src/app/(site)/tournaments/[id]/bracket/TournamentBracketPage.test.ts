import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

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
});
