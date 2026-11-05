"use client";

import { useTranslations } from "next-intl";

import { PhaseStrip, type Phase } from "@/components/kit/PhaseStrip";
import type { Tournament } from "@/types/tournament.types";
import { effectivePhases } from "./effective-phases";

/**
 * Where the tournament is in its derived status chain (D19).
 *
 * Indicator only: the status is derived from the nodes, and `FlowNodeControls` in the hub header moves them.
 */
export function PhaseStepper({ tournament }: Readonly<{ tournament: Tournament }>) {
  const tStatus = useTranslations("common.statusBadge");
  const strip: Phase[] = effectivePhases(tournament.status).map((phase) => ({
    key: phase.key,
    label: tStatus(phase.key),
    state: phase.key === tournament.status ? "current" : phase.reached ? "done" : "todo"
  }));

  return <PhaseStrip phases={strip} />;
}
