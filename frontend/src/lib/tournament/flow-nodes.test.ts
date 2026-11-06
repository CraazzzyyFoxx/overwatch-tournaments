import { describe, expect, it } from "vitest";

import type { TournamentFlowNode } from "@/types/flow.types";

import { currentRegistrationNode, isCheckInOpen, isSignUpLate, isSignUpOpen } from "./flow-nodes";

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
