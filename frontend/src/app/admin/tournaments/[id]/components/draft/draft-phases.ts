import type { Phase } from "@/components/kit/PhaseStrip";
import type { DraftStatus } from "@/types/draft.types";

const PHASES = [
  { key: "setup", label: "Setup" },
  { key: "ready", label: "Ready" },
  { key: "live", label: "Live" },
  { key: "done", label: "Done" }
] as const;

/**
 * Where the draft session stands, on the four-phase scale of F5/F6.
 *
 * One URL used to show either the setup wizard or the control room with no
 * indication of which, or of what comes next; this is that missing scale.
 *
 * `paused` is still Live (a paused draft is a running one waiting on the
 * organizer, not a phase of its own), and `cancelled` is back at Setup —
 * a cancelled session leaves the screen showing a fresh wizard, so claiming
 * any later phase would contradict what is on it.
 */
export function draftPhases(status: DraftStatus | null): Phase[] {
  const current =
    status === "ready" ? 1 : status === "live" || status === "paused" ? 2 : status === "completed" ? 3 : 0;

  return PHASES.map((phase, index) => ({
    key: phase.key,
    label: phase.label,
    state: index < current ? "done" : index === current ? "current" : "todo"
  }));
}
