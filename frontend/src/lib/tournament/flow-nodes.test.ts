import { describe, expect, it } from "vitest";

import type { TournamentFlowNode } from "@/types/flow.types";

import {
  currentRegistrationNode,
  formationModes,
  hasTeamIntake,
  isCheckInOpen,
  isSignUpLate,
  isSignUpOpen,
  nodeDraftFormat,
  listedRegistrationNode,
  primaryFormationMode,
  registrationIntake
} from "./flow-nodes";

function node(id: number, status: string, kind = "registration"): TournamentFlowNode {
  return { id, kind, name: `Node ${id}`, status, config: {}, schedule: [], stage_id: null } as TournamentFlowNode;
}

const idOf = (nodes: TournamentFlowNode[]) => currentRegistrationNode({ flow_nodes: nodes })?.id ?? null;

describe("currentRegistrationNode", () => {
  it("prefers the first open node", () => {
    expect(idOf([node(3, "check_in"), node(5, "open"), node(4, "open")])).toBe(4);
  });

  it("prefers the check-in node where the viewer has an entry, even beside an open one", () => {
    const nodes = [node(3, "check_in"), node(4, "check_in"), node(5, "open")];
    expect(currentRegistrationNode({ flow_nodes: nodes }, [4])?.id).toBe(4);
    expect(currentRegistrationNode({ flow_nodes: nodes }, [5])?.id).toBe(5);
    expect(currentRegistrationNode({ flow_nodes: nodes }, [])?.id).toBe(5);
  });

  it("falls back to the first node in check-in", () => {
    expect(idOf([node(3, "closed"), node(5, "check_in"), node(4, "check_in")])).toBe(4);
  });

  it("falls back to the latest node that left draft", () => {
    expect(idOf([node(3, "closed"), node(4, "closed"), node(5, "draft")])).toBe(4);
  });

  it("is none for draft-only, formation-only or absent nodes", () => {
    expect(idOf([node(3, "draft")])).toBeNull();
    expect(idOf([node(9, "forming", "formation")])).toBeNull();
    expect(currentRegistrationNode(undefined)).toBeNull();
  });
});

describe("listedRegistrationNode", () => {
  it("lists the first registration node before any intake opens (announced tournament)", () => {
    expect(listedRegistrationNode({ flow_nodes: [node(7, "draft"), node(6, "draft")] })?.id).toBe(6);
  });

  it("keeps the current node, or the node it is given", () => {
    const nodes = [node(3, "closed"), node(4, "open")];
    expect(listedRegistrationNode({ flow_nodes: nodes })?.id).toBe(4);
    expect(listedRegistrationNode({ flow_nodes: nodes }, nodes[0])?.id).toBe(3);
  });

  it("is none without a registration node", () => {
    expect(listedRegistrationNode({ flow_nodes: [node(9, "forming", "formation")] })).toBeNull();
  });
});

const withConfig = (n: TournamentFlowNode, config: Record<string, unknown>) => ({ ...n, config }) as TournamentFlowNode;

describe("formation modes and intake", () => {
  const graph = {
    flow_nodes: [
      withConfig(node(1, "open"), { intake: "team" }),
      withConfig(node(7, "draft", "formation"), { mode: "draft" }),
      withConfig(node(5, "draft", "formation"), { mode: "balancer" })
    ]
  };

  it("lists every formation mode and names the first by graph order as primary", () => {
    expect([...formationModes(graph)].sort()).toEqual(["balancer", "draft"]);
    expect(primaryFormationMode(graph)).toBe("balancer");
  });

  it("has no mode without a formation node or without the flow_nodes entity", () => {
    expect(formationModes({ flow_nodes: [node(1, "open")] }).size).toBe(0);
    expect(primaryFormationMode({})).toBeNull();
    expect(primaryFormationMode(undefined)).toBeNull();
  });

  it("reads the intake of the current registration node, solo by default", () => {
    expect(registrationIntake(graph)).toBe("team");
    expect(registrationIntake({ flow_nodes: [node(1, "open")] })).toBe("solo");
    expect(registrationIntake({ flow_nodes: [] })).toBe("solo");
    expect(registrationIntake(graph, withConfig(node(2, "open"), { intake: "solo" }))).toBe("solo");
  });

  it("offers team screens when any registration node takes teams", () => {
    expect(hasTeamIntake(graph)).toBe(true);
    expect(hasTeamIntake({ flow_nodes: [withConfig(node(1, "draft"), { intake: "solo" })] })).toBe(false);
  });

  it("reads a draft node's draft format, null when it has none", () => {
    expect(nodeDraftFormat(withConfig(node(1, "draft", "formation"), { mode: "draft" }))).toBeNull();
    const format = { format: "linear", round_rules: [], avg_tie_seed_reverse: false };
    expect(nodeDraftFormat(withConfig(node(1, "draft", "formation"), { mode: "draft", draft_format: format }))).toEqual(format);
  });
});

const NOW = Date.parse("2026-08-20T12:00:00Z");
const HOUR = 60 * 60 * 1000;
const iso = (offset: number) => new Date(NOW + offset).toISOString();

function windowed(
  status: string,
  rows: { phase: "open" | "check_in"; starts_at?: string; ends_at?: string | null }[] = [],
  config: Record<string, unknown> = {}
): TournamentFlowNode {
  return {
    ...node(1, status),
    config,
    schedule: rows.map((row) => ({ starts_at: iso(-24 * HOUR), ends_at: null, ...row }))
  } as TournamentFlowNode;
}

describe("isSignUpOpen", () => {
  it("needs the open status; an open node with no row is open", () => {
    expect(isSignUpOpen(windowed("draft"), NOW)).toBe(false);
    expect(isSignUpOpen(windowed("closed"), NOW)).toBe(false);
    expect(isSignUpOpen(windowed("open"), NOW)).toBe(true);
    expect(isSignUpOpen(null, NOW)).toBe(false);
  });

  it("includes both bounds of the window", () => {
    expect(isSignUpOpen(windowed("open", [{ phase: "open", starts_at: iso(0) }]), NOW)).toBe(true);
    expect(isSignUpOpen(windowed("open", [{ phase: "open", ends_at: iso(0) }]), NOW)).toBe(true);
    expect(isSignUpOpen(windowed("open", [{ phase: "open", ends_at: iso(-HOUR) }]), NOW)).toBe(false);
    expect(isSignUpOpen(windowed("open", [{ phase: "open", starts_at: iso(HOUR) }]), NOW)).toBe(false);
  });

  it("lets allow_late_registration lift only ends_at", () => {
    const late = { allow_late_registration: true };
    expect(isSignUpOpen(windowed("open", [{ phase: "open", ends_at: iso(-HOUR) }], late), NOW)).toBe(true);
    expect(isSignUpOpen(windowed("open", [{ phase: "open", starts_at: iso(HOUR) }], late), NOW)).toBe(false);
  });

  it("stays open in check-in only with allow_late_registration", () => {
    expect(isSignUpOpen(windowed("check_in"), NOW)).toBe(false);
    expect(isSignUpOpen(windowed("check_in", [], { allow_late_registration: true }), NOW)).toBe(true);
  });
});

describe("isSignUpLate", () => {
  it("is late in check-in or past the open row's end, never before it", () => {
    expect(isSignUpLate(windowed("check_in"), NOW)).toBe(true);
    expect(isSignUpLate(windowed("open", [{ phase: "open", ends_at: iso(-HOUR) }]), NOW)).toBe(true);
    expect(isSignUpLate(windowed("open", [{ phase: "open", ends_at: iso(HOUR) }]), NOW)).toBe(false);
    expect(isSignUpLate(windowed("open"), NOW)).toBe(false);
    expect(isSignUpLate(windowed("closed", [{ phase: "open", ends_at: iso(-HOUR) }]), NOW)).toBe(false);
  });
});

describe("isCheckInOpen", () => {
  it("needs the check_in status and the check_in row; no row means open", () => {
    expect(isCheckInOpen(windowed("open"), NOW)).toBe(false);
    expect(isCheckInOpen(windowed("check_in"), NOW)).toBe(true);
    expect(isCheckInOpen(windowed("check_in", [{ phase: "check_in", ends_at: iso(-HOUR) }]), NOW)).toBe(false);
    expect(isCheckInOpen(windowed("check_in", [{ phase: "check_in", starts_at: iso(HOUR) }]), NOW)).toBe(false);
    expect(isCheckInOpen(windowed("check_in", [{ phase: "check_in", ends_at: iso(0) }]), NOW)).toBe(true);
  });
});
