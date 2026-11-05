import { describe, expect, it } from "vitest";

import { isJobOfNode } from "./useBalancerRealtime";

const job = (formation_node_id?: number | null) => ({ job_id: "j", status: "succeeded", formation_node_id });

describe("isJobOfNode", () => {
  it("ignores a job of another formation node", () => {
    expect(isJobOfNode(job(1), 2)).toBe(false);
  });

  it("follows the job of the node on screen", () => {
    expect(isJobOfNode(job(2), 2)).toBe(true);
  });

  it("follows an event that names no node", () => {
    expect(isJobOfNode(job(null), 2)).toBe(true);
    expect(isJobOfNode(job(), 2)).toBe(true);
  });
});
