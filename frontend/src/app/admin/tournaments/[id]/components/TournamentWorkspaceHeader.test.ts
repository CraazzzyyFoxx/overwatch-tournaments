import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

const headerSource = readFileSync(
  join(import.meta.dir, "TournamentWorkspaceHeader.tsx"),
  "utf8"
);

describe("TournamentWorkspaceHeader", () => {
  it("renders the tournament status control for manual status management", () => {
    expect(headerSource).toContain('from "./TournamentStatusControl"');
    expect(headerSource).toContain("<TournamentStatusControl");
  });
});
