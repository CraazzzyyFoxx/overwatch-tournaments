"use client";

import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

export type PhaseState = "done" | "current" | "todo";

export interface Phase {
  key: string;
  label: string;
  state: PhaseState;
}

export interface PhaseStripProps {
  phases: Phase[];
}

/**
 * Where an entity is in its lifecycle: tournament phases (F3), draft
 * Setup·Ready·Live·Done (F5/F6).
 *
 * Indicator only — no phase is clickable here. Advancing a phase is an action
 * with consequences and lives in the header or the phase's own screen, so a
 * misclick on a progress bar cannot start a draft.
 */
export function PhaseStrip({ phases }: Readonly<PhaseStripProps>) {
  return (
    <ol aria-label="Phases" className="flex flex-wrap items-center gap-x-2 gap-y-1">
      {phases.map((phase, index) => (
        <li key={phase.key} className="flex items-center gap-2">
          {index > 0 ? (
            <span aria-hidden className="h-px w-4 shrink-0 bg-border sm:w-6" />
          ) : null}
          <span
            aria-current={phase.state === "current" ? "step" : undefined}
            className={cn(
              "inline-flex items-center gap-1.5 text-xs",
              phase.state === "current" && "font-medium text-foreground",
              phase.state === "done" && "text-muted-foreground",
              phase.state === "todo" && "text-muted-foreground/60"
            )}
          >
            <span
              aria-hidden
              className={cn(
                "flex size-4 shrink-0 items-center justify-center rounded-full border",
                phase.state === "done" && "border-primary/50 bg-primary/15 text-primary",
                phase.state === "current" && "border-primary bg-primary/10",
                phase.state === "todo" && "border-border"
              )}
            >
              {phase.state === "done" ? <Check aria-hidden className="size-2.5" /> : null}
            </span>
            {phase.label}
          </span>
        </li>
      ))}
    </ol>
  );
}
