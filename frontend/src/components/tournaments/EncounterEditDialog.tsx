"use client";

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";

import { EncounterScoreControls } from "@/components/admin/EncounterScoreControls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { notify } from "@/lib/notify";
import { useTranslations } from "next-intl";
import adminService from "@/services/admin.service";
import type { EncounterUpdateInput } from "@/types/admin.types";
import { Encounter } from "@/types/encounter.types";
import { cn } from "@/lib/utils";

interface EncounterEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  encounter: Encounter;
}

const ENCOUNTER_STATUSES = ["open", "pending", "completed"] as const;

function closenessFloatToStars(closeness: number | null | undefined): number {
  if (closeness == null || closeness <= 0) return 0;
  return Math.max(1, Math.min(10, Math.round(closeness * 10)));
}

export function EncounterEditDialog({ open, onOpenChange, encounter }: EncounterEditDialogProps) {
  const resetKey = [
    encounter.id,
    encounter.score?.home ?? 0,
    encounter.score?.away ?? 0,
    encounter.status ?? "open",
    encounter.closeness ?? "none"
  ].join(":");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open ? (
        <EncounterEditDialogBody key={resetKey} encounter={encounter} onOpenChange={onOpenChange} />
      ) : null}
    </Dialog>
  );
}

function EncounterEditDialogBody({
  encounter,
  onOpenChange
}: Omit<EncounterEditDialogProps, "open">) {
  const qc = useQueryClient();
  const t = useTranslations();
  const homeTeamLabel = encounter.home_team?.name?.trim() || t("common.homeTeam");
  const awayTeamLabel = encounter.away_team?.name?.trim() || t("common.awayTeam");

  const [homeScore, setHomeScore] = useState(() => encounter.score?.home ?? 0);
  const [awayScore, setAwayScore] = useState(() => encounter.score?.away ?? 0);
  const [status, setStatus] = useState<string>(() => encounter.status ?? "open");
  const [stars, setStars] = useState<number>(() => closenessFloatToStars(encounter.closeness));

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

  const saveMutation = useMutation({
    mutationFn: async () => {
      const encounterPayload: EncounterUpdateInput = {
        home_score: homeScore,
        away_score: awayScore,
        status,
        closeness: stars > 0 ? stars / 10 : null
      };
      await adminService.updateEncounter(encounter.id, encounterPayload);
    },
    onSuccess: async () => {
      notify.success(t("matchEdit.matchUpdated"));
      await refreshEncounterViews();
      onOpenChange(false);
    }
  });

  const confirmMutation = useMutation({
    mutationFn: () => adminService.confirmEncounterResult(encounter.id),
    onSuccess: async () => {
      notify.success(t("matchEdit.resultConfirmed"));
      await refreshEncounterViews();
      onOpenChange(false);
    }
  });

  return (
    <DialogContent className="max-w-md bg-[#0c0d0f] border-zinc-800/80 text-white rounded-2xl p-6 shadow-2xl [&>button]:text-zinc-400 [&>button]:hover:text-white [&>button]:hover:bg-zinc-900">
      <DialogHeader className="space-y-1">
        <DialogTitle className="flex items-center gap-2 text-white text-lg font-bold tracking-tight">
          {t("matchEdit.title")}
          {encounter.result_status === "pending_confirmation" && (
            <Badge className="bg-amber-500/80 text-white border-0">
              {t("matchEdit.pendingConfirmation")}
            </Badge>
          )}
          {encounter.result_status === "disputed" && (
            <Badge className="bg-red-500/80 text-white border-0">{t("matchEdit.disputed")}</Badge>
          )}
        </DialogTitle>
        <DialogDescription className="text-zinc-400 text-sm font-semibold mt-1">
          {encounter.home_team?.name} vs {encounter.away_team?.name}
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-4 mt-2">
        <EncounterScoreControls
          idPrefix={`encounter-edit-${encounter.id}`}
          homeScore={homeScore}
          awayScore={awayScore}
          homeLabel={homeTeamLabel}
          awayLabel={awayTeamLabel}
          onScoreChange={(score) => {
            setHomeScore(score.homeScore);
            setAwayScore(score.awayScore);
          }}
          onPresetSelect={(score) => {
            setHomeScore(score.homeScore);
            setAwayScore(score.awayScore);
            setStatus("completed");
          }}
        />

        <div className="space-y-1.5">
          <Label className="text-[13px] font-bold text-zinc-300">{t("matchEdit.status")}</Label>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-full bg-zinc-950 border-zinc-800/85 text-white font-semibold rounded-lg focus:ring-0 focus:ring-offset-0 focus:border-zinc-300">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#0c0d0f] border-zinc-800 text-white">
              {ENCOUNTER_STATUSES.map((item) => (
                <SelectItem
                  key={item}
                  value={item}
                  className="focus:bg-zinc-800 focus:text-white hover:bg-zinc-800 text-zinc-200 cursor-pointer"
                >
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label className="text-[13px] font-bold text-zinc-300">
            {t("matchEdit.matchCloseness")}
          </Label>
          <div className="flex items-center gap-1.5">
            {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setStars(n === stars ? 0 : n)}
                className="p-0.5 hover:scale-110 transition-transform focus-visible:outline-none"
                aria-label={t("matchEdit.starsAria", { count: n })}
              >
                <Star
                  className={cn(
                    "h-5 w-5 transition-colors duration-150",
                    n <= stars
                      ? "fill-yellow-400 text-yellow-400"
                      : "text-zinc-700 hover:text-zinc-600"
                  )}
                />
              </button>
            ))}
            <span className="ml-2 text-xs font-bold text-zinc-400">
              {stars > 0 ? `${stars}/10` : t("matchEdit.notSet")}
            </span>
          </div>
          <p className="text-[11px] text-zinc-500 font-medium leading-normal mt-1">
            {t("matchEdit.closenessHint")}
          </p>
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
        {encounter.result_status === "pending_confirmation" && (
          <Button
            variant="secondary"
            onClick={() => confirmMutation.mutate()}
            disabled={confirmMutation.isPending}
            className="bg-zinc-800 text-white font-semibold rounded-lg hover:bg-zinc-700 transition-colors h-10 px-5"
          >
            {confirmMutation.isPending ? t("matchEdit.confirming") : t("matchEdit.confirmResult")}
          </Button>
        )}
        <Button
          onClick={() => saveMutation.mutate()}
          disabled={!!validationError || saveMutation.isPending}
          className="bg-white text-zinc-950 font-bold rounded-lg hover:bg-zinc-200 transition-colors h-10 px-5"
        >
          {saveMutation.isPending ? t("matchEdit.saving") : t("matchEdit.save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
