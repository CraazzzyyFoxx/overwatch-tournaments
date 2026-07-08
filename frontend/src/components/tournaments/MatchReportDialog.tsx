"use client";

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";

import { EncounterScoreControls } from "@/components/admin/EncounterScoreControls";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { useTranslations } from "next-intl";
import captainService from "@/services/captain.service";
import { Encounter } from "@/types/encounter.types";

interface MatchReportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  encounter: Encounter;
}

const MATCH_QUALITY_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as const;

type MatchQuality = (typeof MATCH_QUALITY_OPTIONS)[number];

function closenessFloatToStars(closeness: number | null | undefined): MatchQuality {
  if (closeness == null || closeness <= 0) return 6;
  return Math.max(1, Math.min(10, Math.round(closeness * 10))) as MatchQuality;
}

export function MatchReportDialog({ open, onOpenChange, encounter }: MatchReportDialogProps) {
  const resetKey = [
    encounter.id,
    encounter.score?.home ?? 0,
    encounter.score?.away ?? 0,
    encounter.closeness ?? "none"
  ].join(":");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open ? (
        <MatchReportDialogBody key={resetKey} encounter={encounter} onOpenChange={onOpenChange} />
      ) : null}
    </Dialog>
  );
}

function MatchReportDialogBody({ encounter, onOpenChange }: Omit<MatchReportDialogProps, "open">) {
  const qc = useQueryClient();
  const t = useTranslations();
  const homeTeamLabel = encounter.home_team?.name?.trim() || t("common.homeTeam");
  const awayTeamLabel = encounter.away_team?.name?.trim() || t("common.awayTeam");

  const [homeScore, setHomeScore] = useState(() => encounter.score?.home ?? 0);
  const [awayScore, setAwayScore] = useState(() => encounter.score?.away ?? 0);
  const [closeness, setCloseness] = useState<MatchQuality>(() =>
    closenessFloatToStars(encounter.closeness)
  );

  const refreshEncounterViews = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ["encounters"] }),
      qc.invalidateQueries({ queryKey: ["standings", encounter.tournament_id] }),
      qc.invalidateQueries({ queryKey: ["tournament"] }),
      qc.invalidateQueries({ queryKey: ["encounter"] }),
      qc.invalidateQueries({ queryKey: ["bracket"] })
    ]);
  };

  const validationError = useMemo(() => {
    if (homeScore < 0 || awayScore < 0) {
      return t("matchEdit.negativeScoreError");
    }
    return null;
  }, [homeScore, awayScore, t]);

  const submitMutation = useMutation({
    mutationFn: () =>
      captainService.submitMatchReport(encounter.id, {
        home_score: homeScore,
        away_score: awayScore,
        closeness
      }),
    onSuccess: async () => {
      notify.success(t("matchReport.submittedForConfirmation"));
      await refreshEncounterViews();
      onOpenChange(false);
    }
  });

  return (
    <DialogContent className="max-w-md bg-[#0c0d0f] border-zinc-800/80 text-white rounded-2xl p-6 shadow-2xl [&>button]:text-zinc-400 [&>button]:hover:text-white [&>button]:hover:bg-zinc-900">
      <DialogHeader className="space-y-1">
        <DialogTitle className="text-white text-lg font-bold tracking-tight">
          {t("matchReport.title")}
        </DialogTitle>
        <DialogDescription className="text-zinc-400 text-sm font-semibold mt-1">
          {encounter.home_team?.name} vs {encounter.away_team?.name}
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-4 mt-2">
        <EncounterScoreControls
          idPrefix={`match-report-${encounter.id}`}
          homeScore={homeScore}
          awayScore={awayScore}
          homeLabel={homeTeamLabel}
          awayLabel={awayTeamLabel}
          presetLabel={t("matchReport.quickResult")}
          onScoreChange={(score) => {
            setHomeScore(score.homeScore);
            setAwayScore(score.awayScore);
          }}
        />

        <div className="space-y-3 rounded-xl border border-zinc-800/80 bg-zinc-950/40 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-500">
                {t("matchReport.matchQuality")}
              </p>
              <p className="mt-0.5 text-[11px] font-medium text-zinc-500">
                {t("matchReport.howClose")}
              </p>
            </div>
            <div className="rounded-lg border border-zinc-800 bg-[#09090b] px-3.5 py-1 text-xs font-bold text-white">
              {t(`matchReport.qualityDescriptions.${closeness}`)}
            </div>
          </div>

          <div className="grid grid-cols-5 gap-2">
            {MATCH_QUALITY_OPTIONS.map((val) => {
              const isSelected = val === closeness;

              return (
                <button
                  key={val}
                  type="button"
                  className={cn(
                    "flex min-h-12 flex-col items-center justify-center gap-1 rounded-lg border px-1.5 py-1.5 text-center transition-all duration-150 focus-visible:outline-none",
                    isSelected
                      ? "border-yellow-500/50 bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/20"
                      : "border-zinc-800 bg-zinc-900/40 text-zinc-400 hover:bg-zinc-800 hover:text-white hover:border-zinc-700"
                  )}
                  onClick={() => setCloseness(val)}
                  aria-pressed={isSelected}
                  aria-label={t("matchReport.qualityAria", {
                    score: String(val),
                    description: t(`matchReport.qualityDescriptions.${val}`)
                  })}
                >
                  <Star
                    className={cn(
                      "h-4.5 w-4.5 transition-colors duration-150",
                      isSelected
                        ? "fill-yellow-400 text-yellow-400"
                        : "text-zinc-600 hover:text-zinc-500"
                    )}
                  />
                  <span className="text-[10.5px] font-bold font-mono">{val}/10</span>
                </button>
              );
            })}
          </div>

          <div className="flex items-center justify-between gap-3 text-[11px] text-zinc-500 font-medium pt-1">
            <span>{t("matchReport.qualityLegend.oneSided")}</span>
            <span>{t("matchReport.qualityLegend.toTheEnd")}</span>
          </div>
        </div>

        {validationError && <p className="text-sm text-red-500 font-semibold">{validationError}</p>}
      </div>

      <DialogFooter className="mt-6 flex flex-row items-center justify-end gap-2">
        <Button
          variant="outline"
          onClick={() => onOpenChange(false)}
          className="border-zinc-800 bg-transparent text-white font-semibold rounded-lg hover:bg-zinc-900 hover:text-white transition-colors h-10 px-5"
        >
          {t("matchEdit.cancel")}
        </Button>
        <Button
          onClick={() => submitMutation.mutate()}
          disabled={!!validationError || submitMutation.isPending}
          className="bg-white text-zinc-950 font-bold rounded-lg hover:bg-zinc-200 transition-colors h-10 px-5"
        >
          {submitMutation.isPending ? t("matchReport.submitting") : t("matchReport.submit")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
