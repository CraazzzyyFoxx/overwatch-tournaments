"use client";

import { useId, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronDown, History, Loader2 } from "lucide-react";

import { AdminReportPairCell } from "@/components/admin/AdminReportPairCell";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
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
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { EncounterReportsRow, EncounterSetResultInput } from "@/types/admin.types";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { cn } from "@/lib/utils";

/**
 * How the score is decided. Mirrors the server's resolution order so what the
 * dialog previews is what the server stores — the two must not drift.
 */
type Mode = "adopt_home" | "adopt_away" | "manual";

/** Stages that cannot end level — the finalizer rejects a draw on these. */
const NEEDS_A_WINNER: Record<string, true> = {
  single_elimination: true,
  double_elimination: true
};

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
  const [historyOpen, setHistoryOpen] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);

  const isConfirmed = row?.result_status === "confirmed";

  const auditQuery = useQuery({
    queryKey: ["encounter-result-audit", row?.id],
    queryFn: () => adminService.getEncounterResultAudit(row!.id),
    enabled: open && historyOpen && row != null
  });

  const resolveMutation = useMutation({
    mutationFn: (payload: EncounterSetResultInput) => adminService.setEncounterResult(row!.id, payload),
    onSuccess: () => {
      notify.success("Result confirmed");
      onOpenChange(false);
      onResolved?.();
    },
    onError: (error: unknown) => notify.apiError(error, { title: "Could not confirm the result" })
  });

  const reopenMutation = useMutation({
    mutationFn: () => adminService.reopenEncounterResult(row!.id),
    onSuccess: () => {
      notify.success("Result reopened");
      setReopenOpen(false);
      onOpenChange(false);
      onResolved?.();
    },
    onError: (error: unknown) => notify.apiError(error, { title: "Could not reopen the result" })
  });

  if (!row) return null;

  const mapCodes = [row.home_report, row.away_report].flatMap((report) =>
    (report?.map_codes ?? []).map((code) => ({ report, code }))
  );

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
            <DialogTitle>{isConfirmed ? "Result confirmed" : "Resolve result"}</DialogTitle>
            <DialogDescription>
              {row.name} &middot; {row.stage_name ?? "Unassigned"} &middot; BO{row.best_of}
            </DialogDescription>
          </DialogHeader>

          <AdminReportPairCell
            homeReport={row.home_report}
            awayReport={row.away_report}
            scoresMatch={row.scores_match}
            seriesScoreValid={row.series_score_valid}
          />

          {mapCodes.length > 0 ? (
            <div className="rounded-lg border border-border/60 p-3">
              <p className={EYEBROW_CLASS}>
                Replay codes
              </p>
              <ul className="mt-2 space-y-1">
                {mapCodes.map(({ report, code }) => (
                  <li key={`${report!.id}-${code.id}`} className="flex gap-2 text-xs">
                    <span className="text-muted-foreground">
                      {report!.side === "away" ? "Away" : "Home"} &middot; Map {code.map_index}
                    </span>
                    <span className="font-mono">{code.code}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {isConfirmed ? (
            <p className="text-sm text-muted-foreground">
              This result is already confirmed. Reopen it to replay or re-report the encounter.
            </p>
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

          <div className="rounded-lg border border-border/60">
            <button
              type="button"
              className={cn(EYEBROW_CLASS, "flex w-full items-center gap-2 p-2 text-left")}
              aria-expanded={historyOpen}
              onClick={() => setHistoryOpen((current) => !current)}
            >
              <History className="size-3.5" aria-hidden />
              Change history
              <ChevronDown
                className={`ml-auto size-3.5 transition-transform ${historyOpen ? "rotate-180" : ""}`}
                aria-hidden
              />
            </button>
            {historyOpen ? (
              <div className="border-t border-border/60 p-2">
                {auditQuery.isLoading ? (
                  <p className="text-xs text-muted-foreground">Loading&hellip;</p>
                ) : (auditQuery.data?.length ?? 0) === 0 ? (
                  // Encounters that predate the audit trail have nothing to
                  // show; saying so beats an empty box that reads as a failure.
                  <p className="text-xs text-muted-foreground">No recorded changes.</p>
                ) : (
                  <ul className="space-y-1">
                    {auditQuery.data!.map((entry) => (
                      <li key={entry.id} className="text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">{entry.action}</span> by{" "}
                        {entry.actor_name ?? "an automated process"} &middot;{" "}
                        <span className="font-mono tabular-nums">
                          {entry.home_score_after} &ndash; {entry.away_score_after}
                        </span>{" "}
                        &middot; {new Date(entry.created_at).toLocaleString()}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ) : null}
          </div>

          {isConfirmed ? (
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                Close
              </Button>
              <Button type="button" variant="secondary" onClick={() => setReopenOpen(true)}>
                Reopen
              </Button>
            </DialogFooter>
          ) : null}
        </DialogContent>
      </Dialog>

      <AlertDialog open={reopenOpen} onOpenChange={setReopenOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reopen this result?</AlertDialogTitle>
            <AlertDialogDescription>
              The encounter leaves the confirmed state and stops counting toward standings until it
              is confirmed again. Any bracket progression it drove is reset.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={reopenMutation.isPending}
              onClick={(event) => {
                event.preventDefault();
                reopenMutation.mutate();
              }}
            >
              Reopen
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
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
  const modeFieldId = useId();
  // Preselect the side with evidence. When only one captain has reported that
  // report is all there is, so defaulting to manual entry would make the
  // commonest case the most laborious.
  const [mode, setMode] = useState<Mode>(
    row.home_report ? "adopt_home" : row.away_report ? "adopt_away" : "manual"
  );
  const [homeScore, setHomeScore] = useState(
    String(row.home_report?.home_score ?? row.away_report?.home_score ?? "")
  );
  const [awayScore, setAwayScore] = useState(
    String(row.home_report?.away_score ?? row.away_report?.away_score ?? "")
  );
  const [closeness, setCloseness] = useState("");

  const preview = useMemo(() => {
    if (mode === "adopt_home" && row.home_report) {
      return { home: row.home_report.home_score, away: row.home_report.away_score };
    }
    if (mode === "adopt_away" && row.away_report) {
      return { home: row.away_report.home_score, away: row.away_report.away_score };
    }
    if (mode !== "manual") return null;
    const home = Number(homeScore);
    const away = Number(awayScore);
    if (homeScore === "" || awayScore === "") return null;
    if (!Number.isInteger(home) || !Number.isInteger(away) || home < 0 || away < 0) return null;
    return { home, away };
  }, [row, mode, homeScore, awayScore]);

  // An elimination bracket needs a winner and the finalizer rejects a draw with
  // a 400. Blocking here means the admin learns it while the score is still in
  // front of them, rather than after a round trip.
  const drawBlocked =
    preview != null &&
    preview.home === preview.away &&
    row.stage_type != null &&
    NEEDS_A_WINNER[row.stage_type] === true;

  const closenessNumber = closeness === "" ? null : Number(closeness);
  const closenessInvalid =
    closenessNumber != null &&
    (!Number.isInteger(closenessNumber) || closenessNumber < 1 || closenessNumber > 10);

  const options: Array<{ value: Mode; label: string; disabled: boolean; detail: string }> = [
    {
      value: "adopt_home",
      label: `Adopt ${row.home_team?.name ?? "home"} report`,
      disabled: row.home_report == null,
      detail: row.home_report
        ? `${row.home_report.home_score} \u2013 ${row.home_report.away_score}`
        : "no report filed"
    },
    {
      value: "adopt_away",
      label: `Adopt ${row.away_team?.name ?? "away"} report`,
      disabled: row.away_report == null,
      detail: row.away_report
        ? `${row.away_report.home_score} \u2013 ${row.away_report.away_score}`
        : "no report filed"
    },
    { value: "manual", label: "Enter the score manually", disabled: false, detail: "" }
  ];

  function submit() {
    const closenessField = closenessNumber ?? undefined;
    if (mode === "adopt_home" || mode === "adopt_away") {
      const report = mode === "adopt_home" ? row.home_report : row.away_report;
      // `adopt_report_team_id` rather than the score it happens to hold: the
      // audit records which side was believed, not just the number.
      onConfirm({ adopt_report_team_id: report?.team_id, closeness: closenessField });
      return;
    }
    onConfirm({ home_score: preview?.home, away_score: preview?.away, closeness: closenessField });
  }

  return (
    <>
      <fieldset className="space-y-2">
        <legend
          id={`${modeFieldId}-legend`}
          className={EYEBROW_CLASS}
        >
          Which score is right?
        </legend>
        {/* `aria-labelledby` rather than a repeated `aria-label`: the legend is
            already on screen, and duplicating it would announce it twice. */}
        <RadioGroup
          value={mode}
          onValueChange={(next) => setMode(next as Mode)}
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
                  <span className="font-mono text-xs text-muted-foreground">{option.detail}</span>
                ) : null}
              </Label>
            </div>
          ))}
        </RadioGroup>

        {mode === "manual" ? (
          <div className="flex flex-wrap items-end gap-2 pt-1">
            <div className="space-y-1">
              <Label htmlFor="resolve-home">Home</Label>
              <Input
                id="resolve-home"
                inputMode="numeric"
                className="h-8 w-20"
                value={homeScore}
                onChange={(event) => setHomeScore(event.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="resolve-away">Away</Label>
              <Input
                id="resolve-away"
                inputMode="numeric"
                className="h-8 w-20"
                value={awayScore}
                onChange={(event) => setAwayScore(event.target.value)}
              />
            </div>
          </div>
        ) : null}

        <div className="space-y-1 pt-1">
          <Label htmlFor="resolve-closeness">Closeness override (1&ndash;10, optional)</Label>
          <Input
            id="resolve-closeness"
            inputMode="numeric"
            className="h-8 w-20"
            value={closeness}
            onChange={(event) => setCloseness(event.target.value)}
            placeholder="auto"
            aria-invalid={closenessInvalid}
          />
          <p className="text-xs text-muted-foreground">
            Left blank, the encounter takes the average of the filed reports.
          </p>
        </div>
      </fieldset>

      <p className="text-sm" aria-live="polite">
        {preview ? (
          <>
            Will record{" "}
            <span className="font-mono font-semibold tabular-nums">
              {preview.home} &ndash; {preview.away}
            </span>
          </>
        ) : (
          <span className="text-muted-foreground">No score selected yet.</span>
        )}
        {drawBlocked ? (
          <span className="block text-danger">
            An elimination bracket needs a winner &mdash; a draw cannot be recorded here.
          </span>
        ) : null}
        {closenessInvalid ? (
          <span className="block text-danger">Closeness must be a whole number from 1 to 10.</span>
        ) : null}
      </p>

      <DialogFooter>
        <Button
          type="button"
          disabled={preview == null || drawBlocked || closenessInvalid || pending}
          onClick={submit}
        >
          {pending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
          Confirm result
        </Button>
      </DialogFooter>
    </>
  );
}
