"use client";

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { CalendarClock } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  AdminDetailTableShell,
  getAdminDetailTableStyles
} from "@/components/admin/AdminDetailTable";
import { ConfirmDialog, type ConfirmIntent } from "@/components/kit/ConfirmDialog";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { Button } from "@/components/ui/button";
import { DateTimePicker } from "@/components/ui/date-picker";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { stageBestOfRoundSections } from "@/lib/tournament/best-of";
import { notify } from "@/lib/notify";
import { utcToZonedInput, zonedInputToUtc } from "@/lib/workspace/timezone";
import adminService from "@/services/admin.service";
import type { Encounter } from "@/types/encounter.types";
import type { Stage } from "@/types/tournament.types";
import { Spinner } from "@/components/ui/spinner";

import { useHubEncountersQuery } from "../../hubQueries";

interface RoundScheduleSectionProps {
  stage: Stage;
  /**
   * The team count that fixes this bracket's depth — the same value the Best-of
   * section is given, so both sections name a round identically.
   */
  bracketTeamCount: number;
  onChanged: () => void;
}

/** One editable row: a round of this stage and the matches it holds. */
interface RoundRow {
  round: number;
  label: string;
  encounters: Encounter[];
  /**
   * The time this round was last applied at, as an ISO instant — the most
   * common `scheduled_at` among its matches, `""` when none carries one. This
   * is the baseline an individual override is measured against; nothing about
   * it is stored, it is re-derived from the matches on every render.
   */
  baseIso: string;
  /** Matches whose own time differs from `baseIso` — moved one by one, in the match editor. */
  overrides: Encounter[];
}

/**
 * The round's applied time: the instant most of its matches share. A round
 * scheduled in one click carries one instant on every match, so the mode IS
 * that applied time; ties resolve to the earliest so the answer is stable.
 */
function modeInstant(encounters: Encounter[]): string {
  const counts = new Map<number, number>();
  for (const encounter of encounters) {
    if (encounter.scheduled_at == null) continue;
    const ts = new Date(encounter.scheduled_at).getTime();
    if (Number.isNaN(ts)) continue;
    counts.set(ts, (counts.get(ts) ?? 0) + 1);
  }
  let best: { ts: number; count: number } | null = null;
  for (const [ts, count] of counts) {
    if (!best || count > best.count || (count === best.count && ts < best.ts)) {
      best = { ts, count };
    }
  }
  return best ? new Date(best.ts).toISOString() : "";
}

/**
 * Round schedule: one time per round, written to every match of that round.
 *
 * The alternative was typing a time into forty match editors. A round is the
 * unit organizers actually schedule, so it is the unit entered here — while a
 * single match that moved keeps its own time (§7 DATA: "1. by round" and
 * "2. per match"), which is why applying a round asks before overwriting those.
 *
 * `ponytail:` matches generated AFTER an apply carry no time — the organizer
 * presses Apply again. A hook on bracket generation belongs on the backend, and
 * only once pressing a button twice is what actually hurts.
 */
export function RoundScheduleSection({
  stage,
  bracketTeamCount,
  onChanged
}: Readonly<RoundScheduleSectionProps>) {
  const t = useTranslations("admin.roundSchedule");
  const styles = getAdminDetailTableStyles("compact");
  const encountersQuery = useHubEncountersQuery(stage.tournament_id);

  // The viewer's own wall clock: the picker's value carries no zone, and the
  // organizer schedules by the time they read on their own clock.
  const timeZone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);

  /** Edited values, keyed by round. Absent = show what the matches carry. */
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [pending, setPending] = useState<{ row: RoundRow; iso: string | null } | null>(null);

  const stageEncounters = useMemo(
    () => (encountersQuery.data?.results ?? []).filter((row) => row.stage_id === stage.id),
    [encountersQuery.data, stage.id]
  );

  const rows = useMemo<RoundRow[]>(() => {
    const byRound = new Map<number, Encounter[]>();
    for (const encounter of stageEncounters) {
      const list = byRound.get(encounter.round);
      if (list) list.push(encounter);
      else byRound.set(encounter.round, [encounter]);
    }
    if (byRound.size === 0) return [];

    // Labels and order come from the bracket's own round naming, so a lower
    // bracket round reads "LB Round 2" rather than "-2". Passing the rounds the
    // matches actually carry as `configuredRounds` guarantees every one of them
    // gets a row, even in a bracket shaped differently than the depth implies.
    const offered = stageBestOfRoundSections({
      stageType: stage.stage_type,
      maxRounds: stage.max_rounds ?? 5,
      bracketTeamCount,
      splitLowerBracket: stage.split_lower_bracket ?? false,
      configuredRounds: [...byRound.keys()]
    }).flatMap((section) => section.rounds);

    return offered
      .filter((option) => byRound.has(option.round))
      .map((option) => {
        const encounters = byRound.get(option.round)!;
        const baseIso = modeInstant(encounters);
        const baseTs = baseIso ? new Date(baseIso).getTime() : null;
        return {
          round: option.round,
          label: option.label,
          encounters,
          baseIso,
          overrides: encounters.filter((encounter) => {
            if (encounter.scheduled_at == null) return false;
            const ts = new Date(encounter.scheduled_at).getTime();
            return !Number.isNaN(ts) && ts !== baseTs;
          })
        };
      });
  }, [
    stageEncounters,
    stage.stage_type,
    stage.max_rounds,
    stage.split_lower_bracket,
    bracketTeamCount
  ]);

  const applyMutation = useMutation({
    mutationFn: ({ encounters, iso }: { encounters: Encounter[]; iso: string | null }) =>
      Promise.all(
        encounters.map((encounter) =>
          adminService.updateEncounter(encounter.id, { scheduled_at: iso })
        )
      ),
    onSuccess: (_result, variables) => {
      setPending(null);
      notify.success(t("applied", { count: variables.encounters.length }));
      // Refreshes the hub's encounters query along with the public bracket and
      // matches views — those times are what they now render.
      onChanged();
    },
    onError: (error) => notify.apiError(error, { title: t("applyError") })
  });

  const apply = (encounters: Encounter[], iso: string | null) => {
    setPending(null);
    if (encounters.length === 0) return;
    applyMutation.mutate({ encounters, iso });
  };

  const intent: ConfirmIntent = pending
    ? {
        title: t("confirmTitle", { count: pending.row.overrides.length }),
        description: t("confirmDescription", {
          count: pending.row.overrides.length,
          round: pending.row.label
        }),
        confirmLabel: t("confirmLabel"),
        tone: "warning"
      }
    : { title: "", description: "", confirmLabel: t("confirmLabel"), tone: "neutral" };

  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold text-foreground">{t("title")}</h3>
      <p className="text-xs text-muted-foreground">{t("description")}</p>

      {encountersQuery.isPending ? (
        <Skeleton className="h-40 w-full rounded-lg" />
      ) : encountersQuery.isError ? (
        <EmptyNote tone="danger" title={t("errorTitle")} icon={CalendarClock}>
          {t("errorBody")}
        </EmptyNote>
      ) : rows.length === 0 ? (
        <EmptyNote title={t("emptyTitle")} icon={CalendarClock}>
          {t("emptyBody")}
        </EmptyNote>
      ) : (
        <AdminDetailTableShell variant="compact">
          <Table>
            <TableHeader>
              <TableRow className={styles.headerRow}>
                <TableHead className={styles.head}>{t("roundColumn")}</TableHead>
                <TableHead className={styles.head}>{t("timeColumn")}</TableHead>
                <TableHead className={styles.head}>{t("matchesColumn")}</TableHead>
                <TableHead className={styles.head}>
                  <span className="sr-only">{t("actionsColumn")}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => {
                const value = drafts[row.round] ?? utcToZonedInput(row.baseIso, timeZone);
                const iso = value ? zonedInputToUtc(value, timeZone) : null;
                // A picker value with no date part would otherwise clear the
                // round's times instead of setting them.
                const unparseable = value !== "" && iso === null;
                return (
                  <TableRow key={row.round} className={styles.row}>
                    <TableCell className={styles.cell}>
                      <span className="font-medium text-foreground">{row.label}</span>
                    </TableCell>
                    <TableCell className={styles.cell}>
                      <div className="w-[22rem]">
                        <DateTimePicker
                          id={`round-schedule-${row.round}`}
                          timeId={`round-schedule-${row.round}-time`}
                          dateLabel={t("timeInputLabel", { round: row.label })}
                          timeLabel={t("timeFieldLabel", { round: row.label })}
                          clearLabel={t("clearTime")}
                          placeholder={t("timePlaceholder")}
                          labelClassName="sr-only"
                          value={value}
                          onChange={(next) =>
                            setDrafts((current) => ({ ...current, [row.round]: next }))
                          }
                        />
                      </div>
                    </TableCell>
                    <TableCell className={styles.numericCell}>
                      {row.encounters.length}
                      {row.overrides.length > 0 ? (
                        <span className="ml-2 text-xs text-warning">
                          {t("overrides", { count: row.overrides.length })}
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell className={styles.cell}>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={applyMutation.isPending || unparseable}
                        onClick={() => {
                          if (row.overrides.length > 0) setPending({ row, iso });
                          else apply(row.encounters, iso);
                        }}
                      >
                        {applyMutation.isPending ? (
                          <Spinner />
                        ) : null}
                        {t("apply")}
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </AdminDetailTableShell>
      )}

      {/*
        The screen's one domain-specific dialog (the kit budget allows exactly
        one beside the shared `ConfirmDialog` in `StageEditor`, which answers
        destructive stage operations). It is mounted here because what it
        confirms — this round's matches — is derived here; routing it through the
        editor's `PendingOp` union would smear one feature across two files.

        Cancelling is NOT "do nothing": the question is only about the
        individually-moved matches, so cancelling still writes the round time to
        the rest and leaves those alone. The description says exactly that.
      */}
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (open || applyMutation.isPending || !pending) return;
          const kept: Record<number, true> = {};
          for (const encounter of pending.row.overrides) kept[encounter.id] = true;
          apply(
            pending.row.encounters.filter((encounter) => !kept[encounter.id]),
            pending.iso
          );
        }}
        intent={intent}
        onConfirm={() => {
          if (pending) {
            applyMutation.mutate({ encounters: pending.row.encounters, iso: pending.iso });
          }
        }}
        pending={applyMutation.isPending}
      />
    </div>
  );
}
