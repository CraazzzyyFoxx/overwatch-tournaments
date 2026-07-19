"use client";

import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { DraftFormat } from "@/types/draft.types";

import { buildDraftSchedule } from "./setup-model";
import { registrationLabel } from "./setup-types";

interface DraftSetupPreviewProps {
  orderedCaptainIds: number[];
  pool: AdminRegistration[];
  rounds: number;
  format: DraftFormat;
  roundRules: string[];
}

export function DraftSetupPreview({
  orderedCaptainIds,
  pool,
  rounds,
  format,
  roundRules
}: DraftSetupPreviewProps) {
  const t = useTranslations("draftAdmin");
  const schedule = buildDraftSchedule(orderedCaptainIds, rounds, format, roundRules);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{t("schedulePreview")}</h3>
        <Badge variant="secondary">{t(`formats.${format}.title`)}</Badge>
      </div>
      <div className="space-y-2">
        {schedule.map((entry) => (
          <div
            key={entry.round}
            className="flex min-w-0 items-center gap-3 rounded-xl border border-border/70 bg-muted/20 px-3 py-2.5"
          >
            <span className="w-16 shrink-0 text-xs font-medium text-muted-foreground">
              {t("roundNumber", { round: entry.round })}
            </span>
            <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
              {entry.teamIds.map((id, index) => {
                const registration = pool.find((candidate) => candidate.id === id);
                return (
                  <span key={id} className="flex shrink-0 items-center gap-1">
                    <span className="max-w-32 truncate rounded-lg bg-background px-2.5 py-1 text-xs shadow-sm">
                      {registration ? registrationLabel(registration) : `#${id}`}
                    </span>
                    {index < entry.teamIds.length - 1 && (
                      <ArrowRight className="h-3 w-3 text-muted-foreground" />
                    )}
                  </span>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

