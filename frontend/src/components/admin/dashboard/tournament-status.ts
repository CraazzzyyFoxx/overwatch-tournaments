import type { Tone } from "@/components/kit/tone";

/**
 * Single source of truth for how a tournament's lifecycle reads on the
 * dashboard. The active-tournament pill and the recent-tournaments rows show
 * the same tournament's status side by side, so they index the same tone here
 * instead of hand-picking a colour each (they used to disagree: one green
 * family in the pill, a solid default badge in the rows).
 */
export function tournamentStatus(isFinished: boolean): { label: string; tone: Tone } {
  return isFinished
    ? { label: "Finished", tone: "neutral" }
    : { label: "Active", tone: "success" };
}
