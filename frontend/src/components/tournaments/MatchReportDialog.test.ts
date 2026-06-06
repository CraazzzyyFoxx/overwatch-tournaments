import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "bun:test";

describe("MatchReportDialog", () => {
  it("submits the selected 1..10 closeness score without converting it to a fraction", () => {
    const source = readFileSync(join(import.meta.dir, "MatchReportDialog.tsx"), "utf8");

    expect(source).toContain("closeness\n      })");
    expect(source).not.toContain("closeness: closeness / 10");
  });
});
