import type { DraftBoard } from "@/types/draft.types";
import { remainingMs } from "./draft-logic";

export type DraftAccent = "live" | "paused" | "blocked" | "urgent" | "done" | "idle";

const DEFAULT_URGENT_MS = 10_000;

export function resolveDraftAccent(
  board: DraftBoard,
  opts: { urgentMs?: number; nowMs?: number } = {}
): DraftAccent {
  const { session, current_pick } = board;
  if (session.blocked_reason === "role_shortage") return "blocked";
  if (session.status === "paused") return "paused";
  if (session.status === "completed") return "done";
  if (session.status !== "live" || !current_pick?.clock_expires_at) return "idle";
  const now = opts.nowMs ?? Date.now();
  const ms = remainingMs(current_pick.clock_expires_at, now);
  return ms > 0 && ms <= (opts.urgentMs ?? DEFAULT_URGENT_MS) ? "urgent" : "live";
}

export function accentToken(accent: DraftAccent): string {
  switch (accent) {
    case "live":
      return "var(--aqt-teal)";
    case "paused":
      return "var(--aqt-amber)";
    case "blocked":
    case "urgent":
      return "var(--aqt-live)";
    case "done":
      return "var(--aqt-support)";
    case "idle":
      return "var(--aqt-fg-faint)";
  }
}
