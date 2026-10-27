"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useFormatter } from "@/lib/datetime/client";

import { AdminReportPairCell } from "@/components/admin/AdminReportPairCell";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { InspectorSection } from "@/components/kit/InspectorField";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageStateCard } from "@/components/ui/page-state-card";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Skeleton } from "@/components/ui/skeleton";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { EncounterReportsRow, EncounterSetResultInput } from "@/types/admin.types";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { stageNeedsWinner } from "@/lib/encounter/score";
import { reportOf, scoreline } from "@/lib/encounter/reports";
import { seatsBySlot } from "@/lib/encounter/seats";

/**
 * How the score is decided: one participation's report is adopted (its
 * `encounter_team_id`, as a string) or the score is typed (`"manual"`). Mirrors
 * the server's resolution order so what the dialog previews is what the server
 * stores — the two must not drift.
 */
type Mode = string;

export interface ResolveResultDialogProps {
  row: EncounterReportsRow | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Invalidations the caller owns — the dialog does not know its surroundings. */
  onResolved?: () => void;
}

/**
 * The single admin write surface for an encounter result.
 *
 * Score, status, result_status and the audit row move together in one request,
 * so a dispute can never be left half-resolved the way "edit the score, then
 * confirm" could. An already-confirmed encounter offers Reopen instead: the
 * server refuses a second confirmation, and a disabled button would leave no
 * way forward.
 */
export function ResolveResultDialog({
  row,
  open,
  onOpenChange,
  onResolved
}: Readonly<ResolveResultDialogProps>) {
  const t = useTranslations("adminTournaments.resolve");
  const tActions = useTranslations("adminMatches.reports.actions");
  const format = useFormatter();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);
  // The reason is written verbatim into the audit journal, so it belongs to the
  // encounter it was typed for: another row reads as empty rather than inheriting it.
  const [reopenDraft, setReopenDraft] = useState<{ rowId: number | null; text: string }>({
    rowId: null,
    text: ""
  });
  const reopenReason = reopenDraft.rowId === row?.id ? reopenDraft.text : "";
  const setReopenReason = (text: string) => setReopenDraft({ rowId: row?.id ?? null, text });

  const isConfirmed = row?.result_status === "confirmed";

  const auditQuery = useQuery({
    queryKey: encounterQueryKeys.resultAudit(row?.id),
    queryFn: () => adminService.getEncounterResultAudit(row!.id),
    enabled: open && historyOpen && row != null
  });

  const resolveMutation = useMutation({
    mutationFn: (payload: EncounterSetResultInput) => adminService.setEncounterResult(row!.id, payload),
    onSuccess: () => {
      notify.success(t("confirmed"));
      onOpenChange(false);
      onResolved?.();
    },
    onError: (error: unknown) => notify.apiError(error, { title: t("confirmError") })
  });

  const reopenMutation = useMutation({
    mutationFn: () => adminService.reopenEncounterResult(row!.id, reopenReason.trim()),
    onSuccess: () => {
      notify.success(t("reopened"));
      setReopenDraft({ rowId: null, text: "" });
      setReopenOpen(false);
      onOpenChange(false);
      onResolved?.();
    },
    onError: (error: unknown) => notify.apiError(error, { title: t("reopenError") })
  });

  if (!row) return null;

  const seatIds = seatsBySlot(row.participations).map((seat) => seat.encounter_team_id);

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) setHistoryOpen(false);
          onOpenChange(next);
        }}
      >
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{isConfirmed ? t("confirmed") : t("resolve")}</DialogTitle>
            <DialogDescription>
              {t("description", {
                name: row.name,
                stage: row.stage_name ?? t("unassigned"),
                bestOf: row.best_of
              })}
            </DialogDescription>
          </DialogHeader>

          <AdminReportPairCell
            participations={row.participations}
            reports={row.reports}
            standingsMatch={row.standings_match}
            seriesScoreValid={row.series_score_valid}
          />

          {row.replay_codes.length > 0 ? (
            <InspectorSection title={t("replayCodes")}>
              <ul className="space-y-1">
                {row.replay_codes.map((entry) => (
                  <li
                    key={`${entry.position}-${entry.encounter_team_id}`}
                    className="flex gap-2 text-xs"
                  >
                    <span className="text-muted-foreground">
                      {t("replayMap", {
                        seat:
                          row.participations.find((seat) => seat.encounter_team_id === entry.encounter_team_id)
                            ?.name ?? t("retiredSeat"),
                        mapIndex: entry.position
                      })}
                    </span>
                    <span className="font-mono">{entry.code}</span>
                  </li>
                ))}
              </ul>
            </InspectorSection>
          ) : null}

          {isConfirmed ? (
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">{t("alreadyConfirmed")}</p>
              <Label htmlFor="reopen-reason">{t("reopenReason")}</Label>
              <Input
                id="reopen-reason"
                value={reopenReason}
                maxLength={500}
                onChange={(event) => setReopenReason(event.target.value)}
              />
            </div>
          ) : (
            // Keyed by encounter: switching rows must start from that row's
            // evidence, and a `key` does that without an effect that writes
            // state on every open.
            <ResolveForm
              key={row.id}
              row={row}
              pending={resolveMutation.isPending}
              onConfirm={(payload) => resolveMutation.mutate(payload)}
            />
          )}

          <Collapsible open={historyOpen} onOpenChange={setHistoryOpen} asChild>
            <section className="border-t border-border/60 pt-3">
              <h3>
                <CollapsibleTrigger
                  className={cn(
                    eyebrowClass("muted"),
                    "group flex w-full items-center gap-1.5 rounded-sm text-left focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
                  )}
                >
                  <ChevronRight aria-hidden className="size-3.5 group-data-[state=open]:rotate-90" />
                  {t("history")}
                </CollapsibleTrigger>
              </h3>
              <CollapsibleContent className="mt-2">
                {auditQuery.isPending ? (
                  <Skeleton className="h-4 w-full" />
                ) : auditQuery.isError ? (
                  <PageStateCard state="error" onAction={() => void auditQuery.refetch()} />
                ) : auditQuery.data.length === 0 ? (
                  // Encounters that predate the audit trail have nothing to
                  // show; saying so beats an empty box that reads as a failure.
                  <p className="text-xs text-muted-foreground">{t("noChanges")}</p>
                ) : (
                  <ul className="space-y-1">
                    {auditQuery.data.map((entry) => (
                      <li key={entry.id} className="text-xs text-muted-foreground">
                        {t.rich("historyEntry", {
                          actionText: tActions(entry.action),
                          actor: entry.actor_name ?? t("automatedProcess"),
                          standing: scoreline(entry.after, seatIds),
                          when: format.dateTime(new Date(entry.created_at), {
                            dateStyle: "medium",
                            timeStyle: "short"
                          }),
                          action: (chunks) => <span className="font-medium text-foreground">{chunks}</span>,
                          score: (chunks) => <span className="tabular-nums">{chunks}</span>
                        })}
                      </li>
                    ))}
                  </ul>
                )}
              </CollapsibleContent>
            </section>
          </Collapsible>

          {isConfirmed ? (
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                {t("close")}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={reopenReason.trim() === ""}
                onClick={() => setReopenOpen(true)}
              >
                {t("reopen")}
              </Button>
            </DialogFooter>
          ) : null}
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={reopenOpen}
        onOpenChange={setReopenOpen}
        intent={{
          title: t("reopenTitle"),
          description:
            t("reopenDescription"),
          confirmLabel: t("reopen"),
          tone: "warning"
        }}
        pending={reopenMutation.isPending}
        onConfirm={() => reopenMutation.mutate()}
      />
    </>
  );
}

/**
 * The score decision. Split out and mounted with a `key` so each encounter gets
 * a fresh form: the alternative is an effect that resets five pieces of state
 * whenever the row changes, which fights React instead of using it.
 */
function ResolveForm({
  row,
  pending,
  onConfirm
}: Readonly<{
  row: EncounterReportsRow;
  pending: boolean;
  onConfirm: (payload: EncounterSetResultInput) => void;
}>) {
  const t = useTranslations("adminTournaments.resolve");
  const modeFieldId = useId();
  const seats = seatsBySlot(row.participations);
  const seatIds = seats.map((seat) => seat.encounter_team_id);
  // A duel's standing is whole games; a lobby's is points, which may be fractional.
  const wholeScores = seats.length === 2;
  // Preselect the first seat with evidence. When only one captain has reported
  // that report is all there is, so defaulting to manual entry would make the
  // commonest case the most laborious.
  const firstReport = seats.map((seat) => reportOf(row.reports, seat.encounter_team_id)).find((report) => report);
  const [mode, setMode] = useState<Mode>(firstReport ? String(firstReport.encounter_team_id) : "manual");
  const [scores, setScores] = useState<Record<number, string>>(() =>
    Object.fromEntries(
      seatIds.map((id) => [
        id,
        String(firstReport?.results.find((line) => line.encounter_team_id === id)?.score ?? "")
      ])
    )
  );
  const [closeness, setCloseness] = useState("");
  // The journal's line for this decision; the server refuses a result without one.
  const [reason, setReason] = useState("");

  const adopted = mode === "manual" ? null : (reportOf(row.reports, Number(mode)) ?? null);
  const preview = (() => {
    if (adopted) {
      return seatIds.map(
        (id) => adopted.results.find((line) => line.encounter_team_id === id)?.score ?? 0
      );
    }
    const entered = seatIds.map((id) => scores[id] ?? "");
    if (entered.some((value) => value.trim() === "")) return null;
    const numbers = entered.map(Number);
    return numbers.every(
      (value) => Number.isFinite(value) && value >= 0 && (!wholeScores || Number.isInteger(value))
    )
      ? numbers
      : null;
  })();

  // An elimination bracket needs a winner and the finalizer rejects a draw with
  // a 400. Blocking here means the admin learns it while the score is still in
  // front of them, rather than after a round trip.
  const drawBlocked =
    preview != null &&
    wholeScores &&
    preview[0] === preview[1] &&
    stageNeedsWinner(row.stage_type);

  const closenessNumber = closeness === "" ? null : Number(closeness);
  const closenessInvalid =
    closenessNumber != null &&
    (!Number.isInteger(closenessNumber) || closenessNumber < 1 || closenessNumber > 10);

  const options: Array<{ value: Mode; label: string; disabled: boolean; detail: string }> = [
    ...seats.map((seat) => {
      const report = reportOf(row.reports, seat.encounter_team_id);
      return {
        value: String(seat.encounter_team_id),
        label: t("adoptReport", { name: seat.name }),
        disabled: report == null,
        detail: report ? scoreline(report.results, seatIds) : t("noReport")
      };
    }),
    { value: "manual", label: t("manualScore"), disabled: false, detail: "" }
  ];

  function submit() {
    const closenessField = closenessNumber ?? undefined;
    if (adopted) {
      // `adopt_report_team_id` rather than the numbers it happens to hold: the
      // audit records whose report was believed, not just the standing.
      onConfirm({
        reason: reason.trim(),
        results: [],
        adopt_report_team_id: adopted.encounter_team_id,
        closeness: closenessField
      });
      return;
    }
    onConfirm({
      reason: reason.trim(),
      results: seatIds.map((id, index) => ({ encounter_team_id: id, score: preview?.[index] ?? 0 })),
      closeness: closenessField
    });
  }

  return (
    <>
      <fieldset className="space-y-2">
        <legend
          id={`${modeFieldId}-legend`}
          className={eyebrowClass("muted")}
        >
          {t("whichScore")}
        </legend>
        {/* `aria-labelledby` rather than a repeated `aria-label`: the legend is
            already on screen, and duplicating it would announce it twice. */}
        <RadioGroup
          value={mode}
          onValueChange={(next) => setMode(next)}
          aria-labelledby={`${modeFieldId}-legend`}
        >
          {options.map((option) => (
            <div
              key={option.value}
              className="flex items-center gap-2 data-[disabled=true]:opacity-50"
              data-disabled={option.disabled}
            >
              <RadioGroupItem
                id={`${modeFieldId}-${option.value}`}
                value={option.value}
                disabled={option.disabled}
              />
              {/* `<button>` is a labelable element, so `htmlFor` both names the
                  radio and makes the whole row its hit target. */}
              <Label
                htmlFor={`${modeFieldId}-${option.value}`}
                className="flex flex-wrap items-center gap-2 font-normal"
              >
                <span>{option.label}</span>
                {option.detail ? (
                  <span className="text-xs tabular-nums text-muted-foreground">{option.detail}</span>
                ) : null}
              </Label>
            </div>
          ))}
        </RadioGroup>

        {mode === "manual" ? (
          <div className="flex flex-wrap items-end gap-2 pt-1">
            {seats.map((seat) => (
              <div key={seat.encounter_team_id} className="space-y-1">
                <Label htmlFor={`${modeFieldId}-score-${seat.encounter_team_id}`}>{seat.name}</Label>
                <Input
                  id={`${modeFieldId}-score-${seat.encounter_team_id}`}
                  inputMode={wholeScores ? "numeric" : "decimal"}
                  size="sm"
                  className="w-20"
                  value={scores[seat.encounter_team_id] ?? ""}
                  onChange={(event) =>
                    setScores((current) => ({ ...current, [seat.encounter_team_id]: event.target.value }))
                  }
                />
              </div>
            ))}
          </div>
        ) : null}

        <div className="space-y-1 pt-1">
          <Label htmlFor="resolve-closeness">{t("closeness")}</Label>
          <Input
            id="resolve-closeness"
            inputMode="numeric"
            size="sm"
            className="w-20"
            value={closeness}
            onChange={(event) => setCloseness(event.target.value)}
            placeholder={t("auto")}
            aria-invalid={closenessInvalid}
          />
          <p className="text-xs text-muted-foreground">
            {t("closenessHelp")}
          </p>
        </div>

        <div className="space-y-1 pt-1">
          <Label htmlFor={`${modeFieldId}-reason`}>{t("reason")}</Label>
          <Input
            id={`${modeFieldId}-reason`}
            value={reason}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
          />
          <p className="text-xs text-muted-foreground">{t("reasonHelp")}</p>
        </div>
      </fieldset>

      <p className="text-sm" aria-live="polite">
        {preview ? (
          <>
            {t.rich("willRecordScore", {
              standing: preview.join(" \u2013 "),
              score: (chunks) => (
                <span className="font-semibold tabular-nums">{chunks}</span>
              )
            })}
          </>
        ) : (
          <span className="text-muted-foreground">{t("noScore")}</span>
        )}
        {drawBlocked ? (
          <span className="block text-danger">
            {t("drawBlocked")}
          </span>
        ) : null}
        {closenessInvalid ? (
          <span className="block text-danger">{t("closenessInvalid")}</span>
        ) : null}
      </p>

      <DialogFooter>
        <Button
          type="button"
          disabled={
            preview == null || drawBlocked || closenessInvalid || reason.trim() === "" || pending
          }
          onClick={submit}
        >
          {pending ? <Spinner /> : null}
          {t("confirm")}
        </Button>
      </DialogFooter>
    </>
  );
}
