import { describe, expect, it } from "vitest";

import { auditDiffRows } from "@/components/kit/audit-log";

const role = (code: string, rank: number | null) => ({
  role: code,
  subrole: "main",
  is_active: true,
  is_primary: code === "damage",
  rank_value: rank,
});

describe("auditDiffRows on a list of records", () => {
  it("pairs elements by identity, so dropping the first role reads as that role removed", () => {
    const rows = auditDiffRows(
      { roles: [role("damage", null), role("support", null)] },
      { roles: [role("support", 4000)] },
    );

    expect(rows).toHaveLength(1);
    expect(rows[0].children?.map((child) => [child.field, child.kind])).toEqual([
      ["damage", "removed"],
      ["support", "changed"],
    ]);
    // Only what moved on the surviving role, not its whole record.
    expect(rows[0].children?.[1].children).toEqual([
      { field: "rank_value", kind: "changed", before: "null", after: "4000" },
    ]);
  });
});
