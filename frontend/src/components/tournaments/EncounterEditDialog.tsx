"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";

import { EncounterScoreControls } from "@/components/tournaments/EncounterScoreControls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DateTimePicker } from "@/components/ui/date-picker";
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
import { utcToZonedInput, zonedInputToUtc } from "@/lib/workspace/timezone";
import { useTranslations } from "next-intl";
import adminService from "@/services/admin.service";
import captainService from "@/services/captain.service";
import { CaptainReportsView } from "@/components/tournaments/CaptainReportsView";
import { refreshEncounterViews } from "@/components/tournaments/refreshEncounterViews";
import type { EncounterEditableStatus, EncounterUpdateInput } from "@/types/admin.types";
import { Encounter } from "@/types/encounter.types";
import { cn } from "@/lib/utils";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

interface EncounterEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  encounter: Encounter;
}

// Editable statuses only. Completion moves score, status, result_status and
// the audit row together, so it belongs to the result action below.
const ENCOUNTER_STATUSES = ["open", "pending"] as const;
const COMPLETED_STATUS = "completed";
const BEST_OF_OPTIONS = [1, 2, 3, 5, 7] as const;

type EncounterStatusOption = (typeof ENCOUNTER_STATUSES)[number] | typeof COMPLETED_STATUS;

/** A completed encounter keeps `completed` so the select has something to show;
 * anything unrecognised falls back to `open` instead of rendering blank. */
function normalizeStatus(status: string | null | undefined): EncounterStatusOption {
  const value = (status ?? "").toLowerCase();
  if (value === COMPLETED_STATUS) return COMPLETED_STATUS;
  return ENCOUNTER_STATUSES.includes(value as (typeof ENCOUNTER_STATUSES)[number])
    ? (value as (typeof ENCOUNTER_STATUSES)[number])
    : "open";
}

function closenessFloatToStars(closeness: number | null | undefined): number {
  if (closeness == null || closeness <= 0) return 0;
  return Math.max(1, Math.min(10, Math.round(closeness * 10)));
}

export function EncounterEditDialog({ open, onOpenChange, encounter }: Readonly<EncounterEditDialogProps>) {
  const resetKey = [
    encounter.id,
    encounter.score?.home ?? 0,
    encounter.score?.away ?? 0,
    encounter.status ?? "open",
    encounter.closeness ?? "none",
    encounter.scheduled_at instanceof Date
      ? encounter.scheduled_at.toISOString()
      : (encounter.scheduled_at ?? "none")
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
}: Readonly<Omit<EncounterEditDialogProps, "open">>) {
  const qc = useQueryClient();
  const t = useTranslations();
  const homeTeamLabel = encounter.home_team?.name?.trim() || t("common.homeTeam");
  const awayTeamLabel = encounter.away_team?.name?.trim() || t("common.awayTeam");

  const [homeScore, setHomeScore] = useState(() => encounter.score?.home ?? 0);
  const [awayScore, setAwayScore] = useState(() => encounter.score?.away ?? 0);
  const [status, setStatus] = useState<EncounterStatusOption>(() => normalizeStatus(encounter.status));
  const [stars, setStars] = useState<number>(() => closenessFloatToStars(encounter.closeness));
  const [bestOf, setBestOf] = useState<number>(() => encounter.best_of ?? 3);
  // The per-match override of the round schedule set in the stage editor. The
  // picker's value carries no zone, so it is read and written in the viewer's
  // own — which is the clock the admin is looking at.
  const timeZone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);
  const [scheduledAt, setScheduledAt] = useState(() =>
    utcToZonedInput(encounter.scheduled_at, timeZone)
  );
  // `completed` is rejected by the field update (completion goes through the
  // result endpoint), so it is shown read-only and left out of the payload.
  const isCompleted = normalizeStatus(encounter.status) === COMPLETED_STATUS;
  const statusOptions: readonly EncounterStatusOption[] = isCompleted ? [COMPLETED_STATUS] : ENCOUNTER_STATUSES;

  const reportsQuery = useQuery({
    queryKey: encounterQueryKeys.captainReports(encounter.id),
    queryFn: () => captainService.getReports(encounter.id)
  });

  const validationError = useMemo(() => {
    if (homeScore < 0 || awayScore < 0) {
      return t("matchEdit.negativeScoreError");
    }
    // A half-typed datetime would otherwise be sent as "clear the time".
    if (scheduledAt !== "" && zonedInputToUtc(scheduledAt, timeZone) === null) {
      return t("matchEdit.scheduledAtInvalid");
    }
    return null;
  }, [homeScore, awayScore, scheduledAt, timeZone, t]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const encounterPayload: EncounterUpdateInput = {
        home_score: homeScore,
        away_score: awayScore,
        closeness: stars > 0 ? stars / 10 : null,
        best_of: bestOf,
        scheduled_at: scheduledAt ? zonedInputToUtc(scheduledAt, timeZone) : null,
        ...(isCompleted ? {} : { status: status as EncounterEditableStatus })
      };
      await adminService.updateEncounter(encounter.id, encounterPayload);
    },
    onSuccess: async () => {
      notify.success(t("matchEdit.matchUpdated"));
      await refreshEncounterViews(qc, encounter.tournament_id);
      onOpenChange(false);
    }
  });

  // Confirming takes the numbers currently on screen, so "fix the score and
  // confirm it" is one request instead of an edit racing a confirm.
  const confirmMutation = useMutation({
    mutationFn: () =>
      adminService.setEncounterResult(encounter.id, {
        home_score: homeScore,
        away_score: awayScore,
        ...(stars > 0 ? { closeness: stars } : {})
      }),
    onSuccess: async () => {
      notify.success(t("matchEdit.resultConfirmed"));
      await refreshEncounterViews(qc, encounter.tournament_id);
      onOpenChange(false);
    },
    onError: (error) => {
      notify.apiError(error, { title: t("matchEdit.confirmErrorMessage") });
    }
  });

  const reopenMutation = useMutation({
    mutationFn: () => adminService.reopenEncounterResult(encounter.id),
    onSuccess: async () => {
      notify.success(t("matchEdit.resultReopened"));
      await refreshEncounterViews(qc, encounter.tournament_id);
      onOpenChange(false);
    },
    onError: (error) => {
      notify.apiError(error, { title: t("matchEdit.reopenErrorMessage") });
    }
  });

  return (
    <DialogContent className="max-w-md">
      <DialogHeader className="space-y-1">
        <DialogTitle className="flex items-center gap-2 text-[color:var(--aqt-fg)] text-lg font-bold tracking-tight">
          {t("matchEdit.title")}
          {encounter.result_status === "pending_confirmation" && (
            <Badge className="border-0 bg-warning text-warning-foreground">
              {t("matchEdit.pendingConfirmation")}
            </Badge>
          )}
          {encounter.result_status === "disputed" && (
            <Badge className="border-0 bg-destructive text-destructive-foreground">{t("matchEdit.disputed")}</Badge>
          )}
        </DialogTitle>
        <DialogDescription className="text-[color:var(--aqt-fg-muted)] text-sm font-semibold mt-1">
          {encounter.home_team?.name} vs {encounter.away_team?.name}
        </DialogDescription>
      </DialogHeader>

      <div className="max-h-[70vh] space-y-4 overflow-y-auto pr-1 mt-2">
        <EncounterScoreControls
          idPrefix={`encounter-edit-${encounter.id}`}
          homeScore={homeScore}
          awayScore={awayScore}
          homeLabel={homeTeamLabel}
          awayLabel={awayTeamLabel}
          bestOf={bestOf}
          onScoreChange={(score) => {
            setHomeScore(score.homeScore);
            setAwayScore(score.awayScore);
          }}
          onPresetSelect={(score) => {
            setHomeScore(score.homeScore);
            setAwayScore(score.awayScore);
          }}
        />

        <div className="space-y-1.5">
          <Label className="text-caption font-bold text-[color:var(--aqt-fg-muted)]">{t("matchEdit.bestOf")}</Label>
          <Select value={String(bestOf)} onValueChange={(value) => setBestOf(Number(value))}>
            <SelectTrigger className="w-full rounded-lg border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] font-semibold text-[color:var(--aqt-fg)]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {BEST_OF_OPTIONS.map((n) => (
                <SelectItem
                  key={n}
                  value={String(n)}
                  className="cursor-pointer"
                >
                  {`BO${n}`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <DateTimePicker
            id={`encounter-scheduled-at-${encounter.id}`}
            timeId={`encounter-scheduled-at-time-${encounter.id}`}
            dateLabel={t("matchEdit.scheduledAt")}
            timeLabel={t("matchEdit.scheduledAtTime")}
            clearLabel={t("matchEdit.scheduledAtClear")}
            placeholder={t("matchEdit.scheduledAtPlaceholder")}
            value={scheduledAt}
            onChange={setScheduledAt}
          />
          <p className="mt-1 text-label font-medium leading-normal text-[color:var(--aqt-fg-dim)]">
            {t("matchEdit.scheduledAtHint")}
          </p>
        </div>

        <div className="space-y-1.5">
          <Label className="text-caption font-bold text-[color:var(--aqt-fg-muted)]">{t("matchEdit.status")}</Label>
          <Select value={status} onValueChange={(value) => setStatus(normalizeStatus(value))} disabled={isCompleted}>
            <SelectTrigger className="w-full rounded-lg border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] font-semibold text-[color:var(--aqt-fg)]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {statusOptions.map((item) => (
                <SelectItem
                  key={item}
                  value={item}
                  className="cursor-pointer"
                >
                  {t(`matchEdit.statuses.${item}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {isCompleted && (
            <p className="text-label text-[color:var(--aqt-fg-dim)] font-medium leading-normal mt-1">
              {t("matchEdit.statusLockedHint")}
            </p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label className="text-caption font-bold text-[color:var(--aqt-fg-muted)]">
            {t("matchEdit.matchCloseness")}
          </Label>
          <div className="flex items-center gap-1.5">
            {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setStars(n === stars ? 0 : n)}
                aria-pressed={n <= stars}
                aria-label={t("matchEdit.starsAria", { count: n })}
                className="rounded p-0.5 transition-opacity hover:opacity-70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                <Star
                  aria-hidden
                  className={cn(
                    "h-5 w-5 transition-colors duration-150",
                    n <= stars
                      ? "fill-[color:var(--aqt-gold)] text-[color:var(--aqt-gold)]"
                      : "text-[color:var(--aqt-fg-faint)]"
                  )}
                />
              </button>
            ))}
            <span className="ml-2 text-xs font-bold text-[color:var(--aqt-fg-muted)]">
              {stars > 0 ? `${stars}/10` : t("matchEdit.notSet")}
            </span>
          </div>
          <p className="text-label text-[color:var(--aqt-fg-dim)] font-medium leading-normal mt-1">
            {t("matchEdit.closenessHint")}
          </p>
        </div>

        {(reportsQuery.data?.reports?.length ?? 0) > 0 && (
          <CaptainReportsView
            encounter={encounter}
            reports={reportsQuery.data?.reports ?? []}
            form={reportsQuery.data?.form}
          />
        )}

        {validationError && <p className="text-sm text-destructive font-semibold">{validationError}</p>}
      </div>

      <DialogFooter className="mt-6 flex flex-row flex-wrap items-center justify-end gap-2">
        <Button
          variant="outline"
          onClick={() => onOpenChange(false)}
          className="h-10 px-5 font-semibold"
        >
          {t("matchEdit.cancel")}
        </Button>
        {encounter.result_status === "confirmed" ? (
          <Button
            variant="secondary"
            onClick={() => reopenMutation.mutate()}
            disabled={reopenMutation.isPending}
            className="h-10 px-5 font-semibold"
          >
            {reopenMutation.isPending ? t("matchEdit.reopening") : t("matchEdit.reopenResult")}
          </Button>
        ) : (
          <Button
            variant="secondary"
            onClick={() => confirmMutation.mutate()}
            disabled={confirmMutation.isPending}
            className="h-10 px-5 font-semibold"
          >
            {confirmMutation.isPending ? t("matchEdit.confirming") : t("matchEdit.confirmResult")}
          </Button>
        )}
        <Button
          onClick={() => saveMutation.mutate()}
          disabled={!!validationError || saveMutation.isPending}
          className="h-10 px-5 font-bold"
        >
          {saveMutation.isPending ? t("matchEdit.saving") : t("matchEdit.save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
