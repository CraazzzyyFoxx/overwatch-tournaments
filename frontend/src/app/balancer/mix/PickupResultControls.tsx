"use client";

import { teamAccent } from "@/app/balancer/mix/pickup-chrome";
import { cn } from "@/lib/utils";
import type { CustomGameOutcome } from "@/services/custom-game.service";

/** Draw: neutral but as solid as the two win buttons, so the row reads as one control. */
const DRAW_TONE =
  "border-[color:var(--aqt-border-3)] bg-white/[0.06] text-[color:var(--aqt-fg)] hover:bg-white/[0.1] hover:border-[color:var(--aqt-fg-faint)]";

type PickupResultControlsProps = {
  /** How many teams the open balance produced — one win button each. */
  teamCount: number;
  /** Host overrides by position, falling back to `Team N` per button. */
  teamNames?: readonly string[];
  saving: boolean;
  /** The host's configured rank-adjustment-per-win, shown on the win buttons; `null`/`0` hides it. */
  pointsPerWin?: number | null;
  onRecord: (outcome: CustomGameOutcome) => void;
};

/**
 * Recording who won one match of a mix — repeatable, does not close it.
 *
 * Laid out as the matchup's footer: a three-column grid whose outer cells
 * mirror the two team columns above it (same `1fr | divider | 1fr` shape as
 * `VariantView`), so "Wolves win" sits under Wolves and Draw sits under the VS
 * seam. A host records the result by clicking under the team they were just
 * reading out, and the row stays out of the captured card so the shared
 * screenshot carries no buttons.
 *
 * A click adds the match to the permanent history straight away and the
 * controls go right back to their resting state -- there is nothing to stay
 * "pressed", so several matches can be logged back to back. The caller only
 * renders this for a writer of an open mix; a viewer or a closed mix reads the
 * history instead of three dead buttons.
 */
export function PickupResultControls({
  teamCount,
  teamNames,
  saving,
  pointsPerWin,
  onRecord
}: Readonly<PickupResultControlsProps>) {
  // A recorded match is always two-sided (`record_outcome` refuses anything
  // else, and the mix solver only ever produces two teams), so the winner is
  // exactly 1, 2 or a draw -- the same shape the server stores.
  const teams = Array.from({ length: Math.min(teamCount, 2) }, (_, index) => ({
    index,
    label: `${teamNames?.[index] ?? `Team ${index + 1}`} win`,
    winner: (index === 0 ? 1 : 2) as 1 | 2
  }));

  const points = pointsPerWin ? (
    <span className="text-[0.9em] tabular-nums opacity-70"> +{pointsPerWin}</span>
  ) : null;

  const teamButton = (team: (typeof teams)[number]) => {
    const accent = teamAccent(team.index);
    return (
      <button
        key={team.index}
        type="button"
        disabled={saving}
        onClick={() => onRecord({ winner: team.winner })}
        className={cn(
          "flex h-10 w-full items-center justify-center gap-2 rounded-lg border text-sm font-semibold transition-colors",
          accent.win,
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:color-mix(in_srgb,var(--aqt-teal)_35%,transparent)]",
          "disabled:cursor-default disabled:opacity-60"
        )}
      >
        <span
          aria-hidden="true"
          className={cn("inline-block size-2 shrink-0 rounded-full", accent.bar)}
        />
        <span className="truncate">{team.label}</span>
        {/* A draw never adjusts ranks, so it never earns the hint. The leading
            space is collapsed by flex but keeps the accessible name readable. */}
        {points}
      </button>
    );
  };

  return (
    // The middle track matches `VariantView`'s VS divider (`lg:w-16`) so Draw
    // lands on the seam; below `lg` the teams stack but this row stays on one
    // line -- three buttons fit where two rosters do not.
    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
      {teams[0] ? teamButton(teams[0]) : <span />}
      <button
        type="button"
        disabled={saving}
        onClick={() => onRecord({ winner: null })}
        className={cn(
          "flex h-10 min-w-16 items-center justify-center rounded-lg border px-3 text-sm font-semibold transition-colors",
          DRAW_TONE,
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:color-mix(in_srgb,var(--aqt-teal)_35%,transparent)]",
          "disabled:cursor-default disabled:opacity-60"
        )}
      >
        Draw
      </button>
      {teams[1] ? teamButton(teams[1]) : <span />}
    </div>
  );
}
