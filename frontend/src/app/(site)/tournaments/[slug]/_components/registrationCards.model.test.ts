import { describe, expect, it } from "vitest";

import type { Tournament } from "@/types/tournament.types";

import { registrationCardNodes } from "./registrationCards.model";

const node = (id: number, status: string) => ({
  id,
  kind: "registration",
  name: `Day ${id}`,
  status,
  stage_id: null,
  config: {},
  schedule: []
});
const t = (...nodes: ReturnType<typeof node>[]) => ({ flow_nodes: nodes }) as unknown as Tournament;

describe("register cards", () => {
  it("a single intake keeps the header button only", () => {
    expect(registrationCardNodes(t(node(1, "open")))).toEqual([]);
  });

  it("several intakes get one card per node open for sign-up", () => {
    expect(
      registrationCardNodes(
        t(node(1, "closed"), node(2, "open"), node(3, "draft"), node(4, "open"))
      ).map((n) => n.id)
    ).toEqual([2, 4]);
  });

  it("no card while no intake is open", () => {
    expect(registrationCardNodes(t(node(1, "closed"), node(2, "draft")))).toEqual([]);
  });
});
