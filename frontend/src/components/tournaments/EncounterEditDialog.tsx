"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";

import { eyebrowClass } from "@/components/ui/eyebrow";
import { EncounterScoreControls } from "@/components/tournaments/EncounterScoreControls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DateTimePicker } from "@/components/ui/date-picker";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
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
import { CaptainReportsView } from "@/components/tournaments/CaptainReportsView";
import { refreshEncounterViews } from "@/components/tournaments/refreshEncounterViews";
import type { EncounterEditableStatus, EncounterUpdateInput } from "@/types/admin.types";
import { reportOf, scoreline } from "@/lib/encounter/reports";
import { seatsBySlot } from "@/lib/encounter/seats";
import type { CaptainReport, Encounter, EncounterTeam } from "@/types/encounter.types";
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
 * Where the score about to be confirmed comes from. A taken report is sent as
 * `adopt_report_team_id`, so the audit records whose word was taken, not just
 * the number.
 */
type ResultSource = "agreed" | "report" | "current" | "manual";
type ResultChoice = {
  source: ResultSource;
  /** The participation whose report is taken; only with source `report`. */
  reportTeamId?: number;
  /** Slot 1 against slot 2. */
  score: EncounterScore;
};

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

/** A duel report's standing, slot 1 against slot 2. */
function reportScore(report: CaptainReport, [first, second]: readonly [number, number]): EncounterScore {
  const of = (id: number) => report.results.find((line) => line.encounter_team_id === id)?.score ?? 0;
  return { one: of(first), two: of(second) };
}

/**
 * The score the dialog opens on, in the server's own fallback order: the
 * reports when they agree, the only report when one captain has filed, then the
 * encounter's own standing (a pre-game room's live series count) unless it is
 * still 0:0. Nothing otherwise — a 0:0 nobody reported is not a result, and
 * confirming it would record a draw.
 */
function suggestResult(
  seats: readonly [EncounterTeam, EncounterTeam],
  reports: readonly CaptainReport[]
): ResultChoice | null {
  const ids: [number, number] = [seats[0].id, seats[1].id];
  const scorelines = reports.map((report) => reportScore(report, ids));
  if (reports.length === seats.length) {
    const [head] = scorelines;
    if (scorelines.every((line) => line.one === head.one && line.two === head.two)) {
      return { source: "agreed", score: head };
    }
  } else if (reports.length === 1) {
    return { source: "report", reportTeamId: reports[0].encounter_team_id, score: scorelines[0] };
  }
  const current = { one: seats[0].score, two: seats[1].score };
  return current.one === 0 && current.two === 0 ? null : { source: "current", score: current };
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
    encounter.result_version,
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
  const seats = seatsBySlot(encounter.teams);
  // A result needs both seats filled: a duel with an empty seat has no standing to write.
  const pair = seats.length === 2 ? ([seats[0], seats[1]] as const) : null;
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
  // The journal's line for whatever the admin writes below: required by the server.
  const [reason, setReason] = useState("");

  const reportsQuery = useQuery({
    queryKey: encounterQueryKeys.captainReports(encounter.id),
    queryFn: () => captainService.getReports(encounter.id)
  });
  const reports = reportsQuery.data?.reports ?? [];
  const result = picked ?? (pair ? suggestResult(pair, reports) : null);
  // The finalizer rejects a draw on an elimination stage with a 400; saying so
  // while the score is still on screen beats learning it from a toast.
  const drawBlocked =
    result != null && result.score.one === result.score.two && stageNeedsWinner(stageType);

  let sourceHint: string | null = null;
  if (result == null) {
    sourceHint = t("matchEdit.noScoreSelected");
  } else if (result.source === "agreed") {
    sourceHint = t("matchEdit.sourceAgreed");
  } else if (result.source === "current") {
    sourceHint = t("matchEdit.sourceCurrent");
  } else if (result.source === "report") {
    sourceHint = t(reports.length === seats.length ? "matchEdit.sourceReport" : "matchEdit.sourceSingleReport", {
      team: seats.find((seat) => seat.id === result.reportTeamId)?.name ?? ""
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
      if (!pair) throw new Error("An encounter with an empty seat has no result to confirm");
      const [first, second] = pair;
      const adopted = choice.source === "report" ? choice.reportTeamId : undefined;
      return adminService.setEncounterResult(encounter.id, {
        reason: reason.trim(),
        results:
          adopted != null
            ? []
            : [
                { encounter_team_id: first.id, score: choice.score.one },
                { encounter_team_id: second.id, score: choice.score.two }
              ],
        ...(adopted != null ? { adopt_report_team_id: adopted } : {}),
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
    mutationFn: () => adminService.reopenEncounterResult(encounter.id, reason.trim()),
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
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          {t("matchEdit.title")}
          {encounter.result_status === "pending_confirmation" && (
            <Badge tone="warning">{t("matchEdit.pendingConfirmation")}</Badge>
          )}
          {encounter.result_status === "disputed" && (
            <Badge tone="danger">{t("matchEdit.disputed")}</Badge>
          )}
        </DialogTitle>
        <DialogDescription>
          {seats.map((seat) => seat.name).join(" vs ")}
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
                <p className={eyebrowClass("muted")}>{t("matchEdit.matchScore")}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{t("matchEdit.confirmedHint")}</p>
              </div>
              <div className="rounded-lg border border-border/60 bg-background px-3.5 py-1.5 text-lg font-bold tracking-label text-foreground tabular-nums">
                {seats.map((seat) => seat.score).join(" – ")}
              </div>
            </div>
          ) : (
            <>
              {pair && reports.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-xs font-semibold text-muted-foreground">{t("matchEdit.takeReport")}</p>
                  <div className="flex flex-wrap gap-2">
                    {seats.map((seat) => {
                      const report = reportOf(reports, seat.id);
                      if (!report) return null;
                      const selected = result?.source === "report" && result.reportTeamId === seat.id;
                      return (
                        <Button
                          key={seat.id}
                          type="button"
                          variant="ghost"
                          aria-pressed={selected}
                          onClick={() =>
                            setPicked({
                              source: "report",
                              reportTeamId: seat.id,
                              score: reportScore(report, [pair[0].id, pair[1].id])
                            })
                          }
                          className={cn(
                            "rounded-lg border px-3 transition-all duration-150",
                            selected
                              ? "border-primary bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground"
                              : "border-border/60 bg-muted/10 text-foreground hover:border-border hover:bg-accent hover:text-accent-foreground"
                          )}
                        >
                          {seat.name}
                          <span className="ml-2 font-mono tabular-nums">
                            {scoreline(report.results, [pair[0].id, pair[1].id])}
                          </span>
                        </Button>
                      );
                    })}
                  </div>
                </div>
              )}

              {pair ? (
                <EncounterScoreControls
                  idPrefix={`encounter-edit-${encounter.id}`}
                  one={result?.score.one ?? 0}
                  two={result?.score.two ?? 0}
                  firstLabel={pair[0].name}
                  secondLabel={pair[1].name}
                  bestOf={encounter.best_of}
                  onScoreChange={(score) => setPicked({ source: "manual", score })}
                />
              ) : null}

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
                <div className="flex items-center gap-0.5">
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
                    <Button
                      key={n}
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => setStars(n === stars ? 0 : n)}
                      aria-pressed={n <= stars}
                      aria-label={t("matchEdit.starsAria", { count: n })}
                    >
                      <Star
                        aria-hidden
                        className={cn(
                          "transition-colors duration-150",
                          n <= stars
                            ? "fill-[color:var(--aqt-gold)] text-[color:var(--aqt-gold)]"
                            : "text-[color:var(--aqt-fg-faint)]"
                        )}
                      />
                    </Button>
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

          <div className="space-y-1.5">
            <Label htmlFor={`encounter-edit-${encounter.id}-reason`} className="text-caption font-bold text-[color:var(--aqt-fg-muted)]">
              {t("matchEdit.reason")}
            </Label>
            <Input
              id={`encounter-edit-${encounter.id}-reason`}
              value={reason}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
            />
            <p className="text-label font-medium leading-normal text-[color:var(--aqt-fg-dim)]">
              {t("matchEdit.reasonHint")}
            </p>
          </div>

          <div className="flex justify-end">
            {isConfirmed ? (
              <Button
                variant="outline"
                onClick={() => reopenMutation.mutate()}
                disabled={reason.trim().length === 0 || reopenMutation.isPending}
                size="lg"
              >
                {reopenMutation.isPending ? t("matchEdit.reopening") : t("matchEdit.reopenResult")}
              </Button>
            ) : (
              <Button
                onClick={() => result && confirmMutation.mutate(result)}
                // Not while the reports load: the score would still be the
                // encounter's own, not the one they are about to suggest.
                disabled={
                  result == null ||
                  drawBlocked ||
                  reason.trim().length === 0 ||
                  reportsQuery.isPending ||
                  confirmMutation.isPending
                }
                size="lg"
              >
                {confirmMutation.isPending
                  ? t("matchEdit.confirming")
                  : result
                    ? t("matchEdit.confirmScore", { first: result.score.one, second: result.score.two })
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
                  <SelectTrigger variant="surface">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {BEST_OF_OPTIONS.map((n) => (
                      <SelectItem key={n} value={String(n)}>
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
                  variant="surface"
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
              <SelectTrigger variant="surface">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {statusOptions.map((item) => (
                  <SelectItem key={item} value={item}>
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
                size="lg"
              >
                {saveMutation.isPending ? t("matchEdit.saving") : t("matchEdit.save")}
              </Button>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </DialogContent>
  );
}
