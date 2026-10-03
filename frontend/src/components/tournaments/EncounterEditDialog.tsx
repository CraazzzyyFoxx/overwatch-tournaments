"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";

import { EYEBROW_CLASS } from "@/components/kit/tone";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { stageNeedsWinner, type EncounterScore } from "@/lib/encounter/score";
import { notify } from "@/lib/notify";
import { utcToZonedInput, zonedInputToUtc } from "@/lib/workspace/timezone";
import { useTranslations } from "next-intl";
import adminService from "@/services/admin.service";
import captainService from "@/services/captain.service";
import { CaptainReportsView, pickReport } from "@/components/tournaments/CaptainReportsView";
import { refreshEncounterViews } from "@/components/tournaments/refreshEncounterViews";
import type {
  EncounterEditableStatus,
  EncounterSetResultInput,
  EncounterUpdateInput
} from "@/types/admin.types";
import type { CaptainReport, Encounter } from "@/types/encounter.types";
import type { StageType } from "@/types/tournament.types";
import { cn } from "@/lib/utils";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

interface EncounterEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  encounter: Encounter;
  /**
   * The viewer holds `match.update`, so the match's structure — best-of and
   * start time — is theirs to change. A referee holds `match.result` alone:
   * the two controls are hidden and left out of the payload, or the server
   * would refuse the whole save over fields they never touched.
   */
  canEditStructure?: boolean;
  /** The encounter's stage type: an elimination stage cannot record a draw. */
  stageType?: StageType | null;
}

// Editable statuses only. Completion moves score, status, result_status and
// the audit row together, so it belongs to the result action below.
const ENCOUNTER_STATUSES = ["open", "pending"] as const;
const COMPLETED_STATUS = "completed";
const BEST_OF_OPTIONS = [1, 2, 3, 5, 7] as const;

type EncounterStatusOption = (typeof ENCOUNTER_STATUSES)[number] | typeof COMPLETED_STATUS;

/**
 * Where the score about to be confirmed comes from. A report side is sent as
 * `adopt_report_team_id`, so the audit records whose word was taken, not just
 * the number.
 */
type ResultSource = "agreed" | "home" | "away" | "current" | "manual";
type ResultChoice = { source: ResultSource; score: EncounterScore };

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

function reportScore(report: CaptainReport): EncounterScore {
  return { homeScore: report.home_score, awayScore: report.away_score };
}

/**
 * The score the dialog opens on, in the server's own fallback order: the two
 * reports when they agree, the only report when one captain has filed, then the
 * encounter's own score (a pre-game room's live series count) unless it is
 * still 0:0. Nothing otherwise — a 0:0 nobody reported is not a result, and
 * confirming it would record a draw.
 */
function suggestResult(
  encounter: Encounter,
  homeReport: CaptainReport | null,
  awayReport: CaptainReport | null
): ResultChoice | null {
  const single = homeReport ?? awayReport;
  if (homeReport && awayReport) {
    if (
      homeReport.home_score === awayReport.home_score &&
      homeReport.away_score === awayReport.away_score
    ) {
      return { source: "agreed", score: reportScore(homeReport) };
    }
  } else if (single) {
    return { source: homeReport ? "home" : "away", score: reportScore(single) };
  }
  const home = encounter.score?.home ?? 0;
  const away = encounter.score?.away ?? 0;
  return home === 0 && away === 0
    ? null
    : { source: "current", score: { homeScore: home, awayScore: away } };
}

export function EncounterEditDialog({
  open,
  onOpenChange,
  encounter,
  canEditStructure = true,
  stageType = null
}: Readonly<EncounterEditDialogProps>) {
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
        <EncounterEditDialogBody
          key={resetKey}
          encounter={encounter}
          onOpenChange={onOpenChange}
          canEditStructure={canEditStructure}
          stageType={stageType}
        />
      ) : null}
    </Dialog>
  );
}

/**
 * Two tabs with one write each, because the server has two writers: the
 * result block confirms through the result endpoint (score, status, audit and
 * bracket advancement in one transaction), the settings block saves the
 * match's structure through the field update. Save used to carry the score as
 * well, which looked like recording a result but never completed the match.
 */
function EncounterEditDialogBody({
  encounter,
  onOpenChange,
  canEditStructure = true,
  stageType = null
}: Readonly<Omit<EncounterEditDialogProps, "open">>) {
  const qc = useQueryClient();
  const t = useTranslations();
  const homeTeamLabel = encounter.home_team?.name?.trim() || t("common.homeTeam");
  const awayTeamLabel = encounter.away_team?.name?.trim() || t("common.awayTeam");
  const isConfirmed = encounter.result_status === "confirmed";

  const [status, setStatus] = useState<EncounterStatusOption>(() => normalizeStatus(encounter.status));
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
  // A referee on a completed match has nothing left the field update would take.
  const canSaveSettings = canEditStructure || !isCompleted;
  // A half-typed datetime would otherwise be sent as "clear the time".
  const settingsError =
    scheduledAt !== "" && zonedInputToUtc(scheduledAt, timeZone) === null
      ? t("matchEdit.scheduledAtInvalid")
      : null;

  const [stars, setStars] = useState<number>(() => closenessFloatToStars(encounter.closeness));
  // `null` follows the suggestion: the reports arrive after the dialog opens,
  // and the score has to follow them until the admin makes a choice of their own.
  const [picked, setPicked] = useState<ResultChoice | null>(null);

  const reportsQuery = useQuery({
    queryKey: encounterQueryKeys.captainReports(encounter.id),
    queryFn: () => captainService.getReports(encounter.id)
  });
  const reports = reportsQuery.data?.reports ?? [];
  const homeReport = pickReport(reports, "home", encounter.home_team_id);
  const awayReport = pickReport(reports, "away", encounter.away_team_id);
  const result = picked ?? suggestResult(encounter, homeReport, awayReport);
  // The finalizer rejects a draw on an elimination stage with a 400; saying so
  // while the score is still on screen beats learning it from a toast.
  const drawBlocked =
    result != null &&
    result.score.homeScore === result.score.awayScore &&
    stageNeedsWinner(stageType);

  let sourceHint: string | null = null;
  if (result == null) {
    sourceHint = t("matchEdit.noScoreSelected");
  } else if (result.source === "agreed") {
    sourceHint = t("matchEdit.sourceAgreed");
  } else if (result.source === "current") {
    sourceHint = t("matchEdit.sourceCurrent");
  } else if (result.source === "home" || result.source === "away") {
    sourceHint = t(homeReport && awayReport ? "matchEdit.sourceReport" : "matchEdit.sourceSingleReport", {
      team: result.source === "home" ? homeTeamLabel : awayTeamLabel
    });
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      const encounterPayload: EncounterUpdateInput = {
        ...(canEditStructure
          ? {
              best_of: bestOf,
              scheduled_at: scheduledAt ? zonedInputToUtc(scheduledAt, timeZone) : null
            }
          : {}),
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

  const confirmMutation = useMutation({
    mutationFn: (choice: ResultChoice) => {
      const report =
        choice.source === "home" ? homeReport : choice.source === "away" ? awayReport : null;
      const score: EncounterSetResultInput = report
        ? { adopt_report_team_id: report.team_id }
        : { home_score: choice.score.homeScore, away_score: choice.score.awayScore };
      return adminService.setEncounterResult(encounter.id, {
        ...score,
        ...(stars > 0 ? { closeness: stars } : {})
      });
    },
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

  // Both tabs stay mounted: an unsaved start time or score survives a switch.
  const tabContentClass = "max-h-[70vh] space-y-4 overflow-y-auto pr-1 data-[state=inactive]:hidden";

  return (
    <DialogContent className="max-w-lg">
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

      <Tabs defaultValue="result" className="mt-2">
        <TabsList>
          <TabsTrigger value="result">{t("matchEdit.resultSection")}</TabsTrigger>
          <TabsTrigger value="settings">{t("matchEdit.settingsSection")}</TabsTrigger>
        </TabsList>

        <TabsContent value="result" forceMount className={tabContentClass}>
          {reports.length > 0 && (
            <CaptainReportsView encounter={encounter} reports={reports} form={reportsQuery.data?.form} />
          )}

          {isConfirmed ? (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-border/60 bg-muted/10 p-4">
              <div>
                <p className={EYEBROW_CLASS}>{t("matchEdit.matchScore")}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{t("matchEdit.confirmedHint")}</p>
              </div>
              <div className="rounded-lg border border-border/60 bg-background px-3.5 py-1.5 text-lg font-bold tracking-label text-foreground tabular-nums">
                {encounter.score?.home ?? 0} – {encounter.score?.away ?? 0}
              </div>
            </div>
          ) : (
            <>
              {(homeReport || awayReport) && (
                <div className="space-y-1.5">
                  <p className="text-xs font-semibold text-muted-foreground">{t("matchEdit.takeReport")}</p>
                  <div className="flex flex-wrap gap-2">
                    {(["home", "away"] as const).map((side) => {
                      const report = side === "home" ? homeReport : awayReport;
                      if (!report) return null;
                      const selected = result?.source === side;
                      return (
                        <Button
                          key={side}
                          type="button"
                          variant="ghost"
                          aria-pressed={selected}
                          onClick={() => setPicked({ source: side, score: reportScore(report) })}
                          className={cn(
                            "h-9 rounded-lg border px-3 font-semibold transition-all duration-150",
                            selected
                              ? "border-primary bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground"
                              : "border-border/60 bg-muted/10 text-foreground hover:border-border hover:bg-accent hover:text-accent-foreground"
                          )}
                        >
                          {side === "home" ? homeTeamLabel : awayTeamLabel}
                          <span className="ml-2 font-mono tabular-nums">
                            {report.home_score} – {report.away_score}
                          </span>
                        </Button>
                      );
                    })}
                  </div>
                </div>
              )}

              <EncounterScoreControls
                idPrefix={`encounter-edit-${encounter.id}`}
                homeScore={result?.score.homeScore ?? 0}
                awayScore={result?.score.awayScore ?? 0}
                homeLabel={homeTeamLabel}
                awayLabel={awayTeamLabel}
                bestOf={encounter.best_of}
                onScoreChange={(score) => setPicked({ source: "manual", score })}
              />

              <p className="text-label font-medium leading-normal text-[color:var(--aqt-fg-dim)]" aria-live="polite">
                {sourceHint}
                {drawBlocked ? (
                  <span className="block font-semibold text-destructive">{t("matchEdit.drawBlocked")}</span>
                ) : null}
              </p>
            </>
          )}

          <div className="space-y-1.5">
            <Label className="text-caption font-bold text-[color:var(--aqt-fg-muted)]">
              {t("matchEdit.matchCloseness")}
            </Label>
            {isConfirmed ? (
              <p className="text-xs font-bold text-[color:var(--aqt-fg-muted)]">
                {stars > 0 ? `${stars}/10` : t("matchEdit.notSet")}
              </p>
            ) : (
              <>
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
              </>
            )}
          </div>

          <div className="flex justify-end">
            {isConfirmed ? (
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
                onClick={() => result && confirmMutation.mutate(result)}
                // Not while the reports load: the score would still be the
                // encounter's own, not the one they are about to suggest.
                disabled={result == null || drawBlocked || reportsQuery.isPending || confirmMutation.isPending}
                className="h-10 px-5 font-bold"
              >
                {confirmMutation.isPending
                  ? t("matchEdit.confirming")
                  : result
                    ? t("matchEdit.confirmScore", { home: result.score.homeScore, away: result.score.awayScore })
                    : t("matchEdit.confirmResult")}
              </Button>
            )}
          </div>
        </TabsContent>

        <TabsContent value="settings" forceMount className={tabContentClass}>
          {canEditStructure && (
            <>
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
            </>
          )}

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

          {settingsError && <p className="text-sm text-destructive font-semibold">{settingsError}</p>}

          {canSaveSettings && (
            <div className="flex justify-end">
              <Button
                variant="outline"
                onClick={() => saveMutation.mutate()}
                disabled={!!settingsError || saveMutation.isPending}
                className="h-10 px-5 font-semibold"
              >
                {saveMutation.isPending ? t("matchEdit.saving") : t("matchEdit.save")}
              </Button>
            </div>
          )}
        </TabsContent>
      </Tabs>

      <DialogFooter className="mt-4">
        <Button
          variant="outline"
          onClick={() => onOpenChange(false)}
          className="h-10 px-5 font-semibold"
        >
          {t("matchEdit.cancel")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
