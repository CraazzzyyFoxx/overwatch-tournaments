"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock } from "lucide-react";
import { useTranslations } from "next-intl";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";

import {
  AdminDetailTableShell,
  adminDetailTableStyles as styles
} from "@/components/admin/AdminDetailTable";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { SettingGroup } from "@/components/kit/SettingRow";
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
import { FFA_STAGE_TYPES } from "@/lib/bracket/projection";
import { stageBestOfRoundSections } from "@/lib/tournament/best-of";
import { notify } from "@/lib/notify";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { utcToZonedInput, zonedInputToUtc } from "@/lib/workspace/timezone";
import adminService from "@/services/admin.service";
import ffaService from "@/services/ffa.service";
import type { Stage } from "@/types/tournament.types";

import { useHubEncountersQuery } from "../../hubQueries";

interface RoundScheduleOptions {
  stage: Stage;
  /**
   * The team count that fixes this bracket's depth — the same value the Best-of
   * section is given, so both sections name a round identically.
   */
  bracketTeamCount: number;
  /** Teams seeded straight into the lower bracket, from the same projection. */
  lowerBracketTeamCount: number;
  /** The engine's own rounds, from the editor's `planned-rounds` query. */
  plannedRounds?: readonly number[];
  onChanged: () => void;
}

/**
 * All the schedule editor reads off one played thing: its id, to PATCH, and the
 * time it currently carries. A duel encounter and an FFA lobby both answer that
 * pair, so one row model covers both rather than a second copy of this section.
 */
interface ScheduledEncounter {
  id: number;
  /** `Encounter` types this as `string | Date | null`; `new Date` takes either. */
  scheduled_at: string | Date | null;
}

/** One editable row: a round of this stage and the matches it holds. */
interface RoundRow {
  round: number;
  label: string;
  encounters: ScheduledEncounter[];
  /**
   * The time this round was last applied at, as an ISO instant — the most
   * common `scheduled_at` among its matches, `""` when none carries one. This
   * is the baseline an individual override is measured against; nothing about
   * it is stored, it is re-derived from the matches on every render.
   */
  baseIso: string;
  /** Matches whose own time differs from `baseIso` — moved one by one, in the match editor. */
  overrides: ScheduledEncounter[];
}

/** One PATCH a save would send: a match that does not carry its round's new time yet. */
interface ScheduleWrite {
  encounterId: number;
  iso: string | null;
  round: string;
  /** The match was moved on its own: overwriting it needs the organizer's yes. */
  moved: boolean;
}

function instantOf(value: string | Date | null): number | null {
  if (value == null) return null;
  const ts = new Date(value).getTime();
  return Number.isNaN(ts) ? null : ts;
}

/**
 * The round's applied time: the instant most of its matches share. A round
 * scheduled in one go carries one instant on every match, so the mode IS
 * that applied time; ties resolve to the earliest so the answer is stable.
 */
function modeInstant(encounters: ScheduledEncounter[]): string {
  const counts = new Map<number, number>();
  for (const encounter of encounters) {
    const ts = instantOf(encounter.scheduled_at);
    if (ts === null) continue;
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

/** One row from the matches it covers: the applied time, and what differs from it. */
function scheduleRow(round: number, label: string, encounters: ScheduledEncounter[]): RoundRow {
  const baseIso = modeInstant(encounters);
  const baseTs = baseIso ? new Date(baseIso).getTime() : null;
  return {
    round,
    label,
    encounters,
    baseIso,
    overrides: encounters.filter((encounter) => {
      const ts = instantOf(encounter.scheduled_at);
      return ts !== null && ts !== baseTs;
    })
  };
}

/**
 * Round schedule: one time per round, written to every match of that round.
 *
 * The alternative was typing a time into forty match editors. A round is the
 * unit organizers actually schedule, so it is the unit entered here — while a
 * single match that moved keeps its own time (§7 DATA: "1. by round" and
 * "2. per match"), which is why saving asks before overwriting those.
 *
 * The round times are drafts of the stage editor's one `SaveBar`, like every
 * other field on the settings page, so the editor owns this state and the
 * section below only draws it. A save writes only the matches that do not
 * carry their round's new time yet.
 *
 * `ponytail:` matches generated AFTER a save carry no time — the organizer
 * picks the round time again and saves. A hook on bracket generation belongs
 * on the backend, and only once doing that twice is what actually hurts.
 */
export function useRoundSchedule({
  stage,
  bracketTeamCount,
  lowerBracketTeamCount,
  plannedRounds,
  onChanged
}: Readonly<RoundScheduleOptions>) {
  const t = useTranslations("adminBracket.roundSchedule");
  const formatRound = useBracketRoundLabel();
  const encountersQuery = useHubEncountersQuery(stage.tournament_id);
  // An FFA stage's lobbies are NOT in that list — `encounterService.getAll`
  // answers duels — so the section read an empty stage and offered no row at
  // all. They come from the stage's own FFA endpoint instead, the same one the
  // public panel reads, so both screens share one cache entry.
  const isFfa = FFA_STAGE_TYPES.includes(stage.stage_type);
  const lobbiesQuery = useQuery({
    queryKey: tournamentQueryKeys.ffaStage(stage.tournament_id, stage.id),
    queryFn: () => ffaService.getStage(stage.tournament_id, stage.id),
    enabled: isFfa
  });
  const queryClient = useQueryClient();

  // The viewer's own wall clock: the picker's value carries no zone, and the
  // organizer schedules by the time they read on their own clock.
  const timeZone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);

  /** Edited values, keyed by round. Absent = show what the matches carry. */
  const [drafts, setDrafts] = useState<Record<number, string>>({});

  const stageEncounters = useMemo(
    () => (encountersQuery.data?.results ?? []).filter((row) => row.stage_id === stage.id),
    [encountersQuery.data, stage.id]
  );

  const rows = useMemo<RoundRow[]>(() => {
    // An FFA stage plays exactly one round: every lobby of it is round 1 and
    // they all start together, so the section offers a single row covering all
    // of them rather than a row per group.
    if (isFfa) {
      const lobbies = lobbiesQuery.data ?? [];
      if (lobbies.length === 0) return [];
      return [
        scheduleRow(
          1,
          t("lobbies"),
          lobbies.map((lobby) => ({ id: lobby.encounter_id, scheduled_at: lobby.scheduled_at }))
        )
      ];
    }

    const byRound = new Map<number, ScheduledEncounter[]>();
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
      lowerBracketTeamCount,
      plannedRounds,
      configuredRounds: [...byRound.keys()],
      formatRound
    }).flatMap((section) => section.rounds);

    return offered
      .filter((option) => byRound.has(option.round))
      .map((option) => scheduleRow(option.round, option.label, byRound.get(option.round)!));
  }, [
    isFfa,
    lobbiesQuery.data,
    stageEncounters,
    stage.stage_type,
    stage.max_rounds,
    lowerBracketTeamCount,
    bracketTeamCount,
    plannedRounds,
    formatRound,
    t
  ]);

  const writes = useMemo<ScheduleWrite[]>(
    () =>
      rows.flatMap((row) => {
        const value = drafts[row.round];
        if (value === undefined) return [];
        const iso = value === "" ? null : zonedInputToUtc(value, timeZone);
        // Not an instant: writing it would clear the round instead of setting it.
        if (value !== "" && iso === null) return [];
        const target = iso === null ? null : new Date(iso).getTime();
        const moved = new Set(row.overrides.map((encounter) => encounter.id));
        return row.encounters
          .filter((encounter) => instantOf(encounter.scheduled_at) !== target)
          .map((encounter) => ({
            encounterId: encounter.id,
            iso,
            round: row.label,
            moved: moved.has(encounter.id)
          }));
      }),
    [rows, drafts, timeZone]
  );
  const moved = writes.filter((write) => write.moved);

  const saveMutation = useMutation({
    mutationFn: (batch: ScheduleWrite[]) =>
      Promise.all(
        batch.map((write) =>
          adminService.updateEncounter(write.encounterId, { scheduled_at: write.iso })
        )
      ),
    onSuccess: (_result, batch) => {
      setDrafts({});
      if (batch.length === 0) return;
      notify.success(t("applied", { count: batch.length }));
      // Refreshes the hub's encounters query along with the public bracket and
      // matches views — those times are what they now render.
      onChanged();
      // The lobby reads sit outside that workspace bundle, so the FFA panel and
      // the lobby page would keep printing the old kickoff without this.
      if (isFfa) {
        void queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.ffaAll(stage.tournament_id)
        });
      }
    },
    onError: (error) => notify.apiError(error, { title: t("applyError") })
  });

  // Whichever read actually feeds this stage. The other one is disabled, and a
  // disabled query reports `isPending` forever.
  const source = isFfa
    ? { isPending: lobbiesQuery.isPending, isError: lobbiesQuery.isError }
    : { isPending: encountersQuery.isPending, isError: encountersQuery.isError };

  return {
    isFfa,
    source,
    rows,
    valueOf: (row: RoundRow) => drafts[row.round] ?? utcToZonedInput(row.baseIso, timeZone),
    setDraft: (round: number, value: string) =>
      setDrafts((current) => ({ ...current, [round]: value })),
    discard: () => setDrafts({}),
    dirty: writes.length > 0,
    /** The individually moved matches a save would overwrite, for the question before it. */
    moved,
    /** `overwriteMoved: false` keeps the moved matches and still schedules the rest. */
    save: (overwriteMoved: boolean) =>
      saveMutation.mutateAsync(overwriteMoved ? writes : writes.filter((write) => !write.moved)),
    saving: saveMutation.isPending
  };
}

export type RoundSchedule = ReturnType<typeof useRoundSchedule>;

export function RoundScheduleSection({ schedule }: Readonly<{ schedule: RoundSchedule }>) {
  const t = useTranslations("adminBracket.roundSchedule");
  const tEditor = useTranslations("adminBracket.editor");
  const { isFfa, source, rows } = schedule;

  return (
    <SettingGroup id="stage-round-schedule" title={tEditor("schedule")} description={t("description")}>
      {source.isPending ? (
        <Skeleton className="h-40 w-full rounded-lg" />
      ) : source.isError ? (
        <EmptyNote tone="danger" title={t("errorTitle")} icon={CalendarClock}>
          {t("errorBody")}
        </EmptyNote>
      ) : rows.length === 0 ? (
        <EmptyNote
          title={isFfa ? t("emptyTitleLobbies") : t("emptyTitle")}
          icon={CalendarClock}
        >
          {isFfa ? t("emptyBodyLobbies") : t("emptyBody")}
        </EmptyNote>
      ) : (
        <AdminDetailTableShell>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className={styles.head}>{t("roundColumn")}</TableHead>
                <TableHead className={styles.head}>{t("timeColumn")}</TableHead>
                <TableHead className={styles.head}>
                  {isFfa ? t("lobbies") : t("matchesColumn")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
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
                        value={schedule.valueOf(row)}
                        onChange={(next) => schedule.setDraft(row.round, next)}
                      />
                    </div>
                  </TableCell>
                  <TableCell className={styles.numericCell}>
                    {row.encounters.length}
                    {row.overrides.length > 0 ? (
                      <span className="ml-2 text-label text-warning">
                        {t("overrides", { count: row.overrides.length })}
                      </span>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </AdminDetailTableShell>
      )}
    </SettingGroup>
  );
}
