import { describe, expect, it } from "vitest";
import { resolveDraftAccent, accentToken } from "./draft-visual";
import type { DraftBoard } from "@/types/draft.types";

function board(partial: Partial<DraftBoard["session"]>, currentExpires?: string | null): DraftBoard {
  return {
    session: { status: "live", blocked_reason: null, ...partial } as DraftBoard["session"],
    teams: [], picks: [], players: [],
    current_pick: currentExpires === undefined ? null : ({ clock_expires_at: currentExpires } as any),
    server_time: "", last_event_id: null,
  } as DraftBoard;
}

describe("resolveDraftAccent", () => {
  it("maps paused → paused", () => {
    expect(resolveDraftAccent(board({ status: "paused" }))).toBe("paused");
  });
  it("maps role_shortage block → blocked", () => {
    expect(resolveDraftAccent(board({ status: "live", blocked_reason: "role_shortage" }))).toBe("blocked");
  });
  it("maps completed → done", () => {
    expect(resolveDraftAccent(board({ status: "completed" }))).toBe("done");
  });
  it("maps live with plenty of time → live", () => {
    const now = 1_000_000;
    const expires = new Date(now + 30_000).toISOString();
    expect(resolveDraftAccent(board({ status: "live" }, expires), { nowMs: now })).toBe("live");
  });
  it("maps live under the urgent threshold → urgent", () => {
    const now = 1_000_000;
    const expires = new Date(now + 4_000).toISOString();
    expect(resolveDraftAccent(board({ status: "live" }, expires), { nowMs: now, urgentMs: 10_000 })).toBe("urgent");
  });
  it("maps setup/ready (no clock) → idle", () => {
    expect(resolveDraftAccent(board({ status: "ready" }))).toBe("idle");
  });
  it("accentToken returns a css var", () => {
    expect(accentToken("blocked")).toBe("var(--aqt-live)");
    expect(accentToken("live")).toBe("var(--aqt-teal)");
  });
});
