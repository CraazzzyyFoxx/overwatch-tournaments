"use client";

import { Ban, Check, CircleDashed, MapPin, Shuffle } from "lucide-react";
import { useTranslations } from "next-intl";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { MapRead } from "@/types/map.types";
import type { EncounterMapPoolEntry } from "@/types/tournament.types";

import { parseStepToken, type VetoSide } from "./veto-model";

interface VetoStepTimelineProps {
  sequence: string[];
  pool: EncounterMapPoolEntry[];
  currentStepIndex: number | null;
  isComplete: boolean;
  mapsById: Record<number, MapRead | undefined>;
  sideName: (side: VetoSide) => string;
}

export function VetoStepTimeline({
  sequence,
  pool,
  currentStepIndex,
  isComplete,
  mapsById,
  sideName,
}: VetoStepTimelineProps) {
  const t = useTranslations("encounters.veto.room");
  // Done-ness derives from committed pool actions, not from the step pointer:
  // every acted entry carries a global action_index (bans, picks, decider).
  const actedCount = pool.reduce(
    (count, entry) => (entry.action_index != null ? count + 1 : count),
    0,
  );

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t("steps.title")}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-1.5">
        {sequence.map((token, index) => {
          const step = parseStepToken(token);
          const done = isComplete || index < actedCount;
          const current = !done && currentStepIndex === index;
          const actedEntry = done
            ? pool.find((entry) => entry.action_index === index)
            : undefined;
          const actedMapName =
            actedEntry != null
              ? mapsById[actedEntry.map_id]?.name ?? t("maps.mapNumber", { id: actedEntry.map_id })
              : null;

          const Icon = done ? Check : step.action === "decider" ? Shuffle : current ? MapPin : CircleDashed;
          const actionLabel =
            step.action === "decider"
              ? t("steps.decider")
              : step.action === "ban"
                ? t("steps.ban")
                : t("steps.pick");

          return (
            <div
              key={`${token}-${index}`}
              aria-current={current ? "step" : undefined}
              className={cn(
                "flex items-center gap-2.5 rounded-lg border px-3 py-2 text-sm",
                current
                  ? "border-[color:var(--aqt-teal)]/45 bg-[color:var(--aqt-teal)]/10"
                  : "border-[color:var(--aqt-border)]",
                done ? "opacity-70" : null,
              )}
            >
              <span className="w-5 shrink-0 text-right font-mono text-xs text-[color:var(--aqt-fg-faint)]">
                {index + 1}
              </span>
              <Icon
                aria-label={done ? t("steps.done") : current ? t("steps.current") : t("steps.pending")}
                className={cn(
                  "h-4 w-4 shrink-0",
                  done
                    ? "text-[color:var(--aqt-support)]"
                    : current
                      ? "text-[color:var(--aqt-teal)]"
                      : "text-[color:var(--aqt-fg-faint)]",
                )}
              />
              <span
                className={cn(
                  "inline-flex items-center gap-1 font-medium",
                  step.action === "ban" ? "text-[color:var(--aqt-rose)]" : null,
                  step.action === "pick" ? "text-[color:var(--aqt-support)]" : null,
                )}
              >
                {step.action === "ban" ? <Ban className="h-3.5 w-3.5" aria-hidden /> : null}
                {actionLabel}
              </span>
              {step.side ? (
                <span className="min-w-0 truncate text-[color:var(--aqt-fg-muted)]">
                  {sideName(step.side)}
                </span>
              ) : null}
              {actedMapName ? (
                <span className="ml-auto min-w-0 truncate font-medium">{actedMapName}</span>
              ) : null}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
