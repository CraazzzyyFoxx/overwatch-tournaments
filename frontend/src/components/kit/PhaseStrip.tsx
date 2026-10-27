"use client";

import { Check } from "lucide-react";
import { useTranslations } from "next-intl";

import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

export type PhaseState = "done" | "current" | "todo";

export interface Phase {
  key: string;
  label: string;
  state: PhaseState;
}

export interface PhaseStripProps {
  phases: Phase[];
  /**
   * `compact`: unlabelled segments, for a card whose heading already names the
   * current phase. Each name stays in `title` and for screen readers.
   */
  variant?: "labelled" | "compact";
}

/**
 * Where an entity is in its lifecycle: tournament phases (F3), draft
 * Setup·Ready·Live·Done (F5/F6).
 *
 * Indicator only — no phase is clickable here. Advancing a phase is an action
 * with consequences and lives in the header or the phase's own screen, so a
 * misclick on a progress bar cannot start a draft.
 */
export function PhaseStrip({ phases, variant = "labelled" }: Readonly<PhaseStripProps>) {
  const t = useTranslations("kit.actions");
  if (variant === "compact") {
    return (
      <ol aria-label={t("phases")} className="flex w-full max-w-60 items-center gap-1">
        {phases.map((phase) => (
          <li
            key={phase.key}
            title={phase.label}
            aria-current={phase.state === "current" ? "step" : undefined}
            className="min-w-0 flex-1"
          >
            <span
              aria-hidden
              className={cn(
                "block h-1.5 rounded-full",
                phase.state === "done" && "bg-primary/45",
                phase.state === "current" && "bg-primary",
                phase.state === "todo" && "bg-border"
              )}
            />
            <span className="sr-only">{phase.label}</span>
          </li>
        ))}
      </ol>
    );
  }
  return (
    <ol aria-label={t("phases")} className="flex flex-wrap items-center gap-x-2 gap-y-1">
      {phases.map((phase, index) => (
        <li key={phase.key} className="flex items-center gap-2">
          {index > 0 ? <Separator className="w-4 sm:w-6" /> : null}
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
