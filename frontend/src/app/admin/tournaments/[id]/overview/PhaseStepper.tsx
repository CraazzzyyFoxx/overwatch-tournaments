"use client";

import { AlertTriangle } from "lucide-react";

import { PhaseStrip, type Phase } from "@/components/kit/PhaseStrip";
import { TOURNAMENT_STATUS_LABELS } from "@/lib/tournament/lifecycle";
import type { Tournament } from "@/types/tournament.types";
import { effectivePhases } from "./effective-phases";

/**
 * Where the tournament is in its effective phase chain (D19).
 *
 * Indicator only now: the status control moved to the hub header, where a
 * phase transition belongs. Two identical badge + transition clusters mutating
 * the same status left no way to tell which one was authoritative, and the
 * surviving one was inside a progress bar.
 *
 * A force-transition can leave the tournament on a status outside the chain.
 * That phase is flagged `drifted` and printed beside the strip rather than
 * appended after the terminal phase, which would read as normal progress.
 */
export function PhaseStepper({ tournament }: Readonly<{ tournament: Tournament }>) {
  const phases = effectivePhases({
    teamFormation: tournament.team_formation,
    schedule: tournament.phase_schedule.map((entry) => entry.status),
    currentStatus: tournament.status
  });
  const drifted = phases.find((phase) => phase.drifted);
  const strip: Phase[] = phases
    .filter((phase) => !phase.drifted)
    .map((phase) => ({
      key: phase.key,
      label: TOURNAMENT_STATUS_LABELS[phase.key] ?? phase.key,
      state:
        !drifted && phase.key === tournament.status
          ? "current"
          : phase.reached
            ? "done"
            : "todo"
    }));

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <PhaseStrip phases={strip} />
      {drifted ? (
        <p className="inline-flex items-center gap-1.5 text-xs font-medium text-warning">
          <AlertTriangle className="size-3.5" aria-hidden />
          Off track: {TOURNAMENT_STATUS_LABELS[drifted.key] ?? drifted.key}
        </p>
      ) : null}
    </div>
  );
}
