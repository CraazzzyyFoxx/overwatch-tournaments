"use client";

import { useSyncExternalStore } from "react";
import { useTranslations } from "next-intl";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import { acceptedScore } from "@/components/pick-ban/pick-ban-model";
import TeamName from "@/components/TeamName";
import { Card } from "@/components/ui/card";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusDot } from "@/components/ui/status-dot";
import { GameMark } from "@/components/workspace/GameMark";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { UNKNOWN_ROUND_SHAPE } from "@/lib/bracket/round-name";
import { mapWithModeName } from "@/lib/catalog/mode";
import { useFormatter } from "@/lib/datetime/client";
import { buildSeriesSlots } from "@/lib/encounter/detail";
import { duelSeats, seatTeam, type DuelSlot } from "@/lib/encounter/seats";
import { getEncounterWinner, isEncounterCompleted, isEncounterLive } from "@/lib/encounter/status";
import { cn } from "@/lib/utils";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { Encounter, EncounterTeam } from "@/types/encounter.types";

const SKELETON_ROWS = 8;

// Stable no-op subscriber: hydration never "changes" once it has happened, so
// the store has nothing to notify. Module scope keeps its identity stable.
const subscribeNoop = () => () => {};

const FAINT = "text-[color:var(--aqt-fg-faint)]";

// The row's one link is stretched over the whole row/card from the matchup
// cell, so middle-click and "open in new tab" work like any other link.
const STRETCHED_LINK =
  "after:absolute after:inset-0 after:content-[''] focus-visible:outline-hidden " +
  "focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-[color:var(--aqt-teal)]";

/** One encounter as both the row and the card read it. */
interface RowView {
  one: EncounterTeam | null;
  two: EncounterTeam | null;
  scoreOne: number;
  scoreTwo: number;
  /** False before a map is decided: the score reads "vs", not 0–0. */
  hasScore: boolean;
  winner: DuelSlot | null;
  names: { one: string; two: string };
  /** The row link's accessible name: both teams and the score. */
  label: string;
  stage: string;
  round: string;
  bestOf: string;
  /** 0..1 closeness as the bar's width, null when the server has none. */
  closeness: number | null;
  /** The same as a locale percent ("60 %" in ru). */
  closenessText: string | null;
  when: { day: string; time: string; live: boolean };
}

/**
 * The `/encounters` list: a table from `md` up, a card list below it. Both
 * render from the same rows; CSS picks one, so there is no viewport read and
 * nothing to mismatch at hydration. Search, filters and pagination are the
 * page's.
 */
export function EncountersDataTable({
  rows,
  loading = false,
  games,
  className
}: Readonly<{
  rows: Encounter[];
  /** Renders placeholder rows instead of collapsing the list to nothing. */
  loading?: boolean;
  /** Installed games by code, passed only when the list spans several games: each row shows its game's mark (§6.1). */
  games?: Map<string, DisciplineDescriptor>;
  className?: string;
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const roundLabel = useBracketRoundLabel();
  // Relative time ("3h ago") must only be produced after hydration: the server
  // renders at one instant and the client at another, which is a hydration
  // mismatch. `useSyncExternalStore` reads "am I hydrated" as the external fact
  // it is, instead of cascading a render with setState inside an effect.
  const isHydrated = useSyncExternalStore(subscribeNoop, () => true, () => false);
  const now = isHydrated ? new Date() : null;

  const whenParts = (encounter: Encounter): RowView["when"] => {
    if (isEncounterLive(encounter)) {
      return { day: t("common.now"), time: t("encounters.state.live"), live: true };
    }
    const toDate = (value: Date | string | null | undefined) => {
      const date = value == null ? null : new Date(value);
      return date && !Number.isNaN(date.getTime()) ? date : null;
    };
    const completed = isEncounterCompleted(encounter);
    const at = toDate(completed ? encounter.played_at : encounter.scheduled_at);
    if (at) {
      return {
        day: format.dateTime(at, { month: "short", day: "numeric" }),
        time:
          completed && now
            ? format.relativeTime(at, now)
            : format.dateTime(at, { timeStyle: "short" }),
        live: false
      };
    }
    if (!completed) return { day: t("encounters.state.upcoming"), time: "", live: false };
    // No trusted `played_at` (imported history): the tournament's dates, as a
    // day with its year, since these run years back.
    const held = toDate(encounter.tournament?.end_date ?? encounter.tournament?.start_date);
    return {
      day: held
        ? format.dateTime(held, { day: "numeric", month: "short", year: "numeric" })
        : t("common.tbd"),
      time: "",
      live: false
    };
  };

  const view = (encounter: Encounter): RowView => {
    const [one, two] = duelSeats(encounter.teams);
    const scoreOne = one?.score ?? 0;
    const scoreTwo = two?.score ?? 0;
    const names = {
      one: seatTeam(one)?.name ?? t("common.tbd"),
      two: seatTeam(two)?.name ?? t("common.tbd")
    };
    const hasScore = isEncounterCompleted(encounter) || scoreOne !== 0 || scoreTwo !== 0;
    const closeness =
      encounter.closeness != null && Number.isFinite(encounter.closeness) ? encounter.closeness : null;
    return {
      one,
      two,
      scoreOne,
      scoreTwo,
      hasScore,
      winner: getEncounterWinner(encounter),
      label: hasScore
        ? t("encounters.table.linkScore", { ...names, scoreOne, scoreTwo })
        : t("encounters.table.linkVs", names),
      names,
      stage: encounter.stage_item?.name ?? encounter.stage?.name ?? t("common.unassignedStage"),
      round: encounter.is_final ? t("bracket.final") : roundLabel(encounter.round, UNKNOWN_ROUND_SHAPE),
      bestOf: t("encounters.bestOfShort", { count: encounter.best_of }),
      closeness,
      closenessText:
        closeness == null ? null : format.number(closeness, { style: "percent", maximumFractionDigits: 0 }),
      when: whenParts(encounter)
    };
  };

  const gameMark = (encounter: Encounter) => {
    if (!games) return null;
    // An uninstalled game's history is named by its code.
    const game = games.get(encounter.discipline) ?? {
      code: encounter.discipline,
      name: encounter.discipline,
      short_name: encounter.discipline.slice(0, 2).toUpperCase(),
      icon: null
    };
    return <GameMark discipline={game} size={20} />;
  };

  const matchupLink = (encounter: Encounter, row: RowView, linkClassName?: string) => (
    <HoverPrefetchLink
      href={`/encounters/${encounter.id}`}
      aria-label={row.label}
      className={cn("flex min-w-0 flex-col gap-1", STRETCHED_LINK, linkClassName)}
    >
      {([1, 2] as const).map((slot) => (
        <TeamName
          key={slot}
          team={seatTeam(slot === 1 ? row.one : row.two)}
          fallback={t("common.tbd")}
          size="xs"
          nameClassName={cn(
            "text-caption font-semibold",
            row.winner === slot
              ? "font-bold text-[color:var(--aqt-fg)]"
              : row.winner
                ? "text-[color:var(--aqt-fg-dim)]"
                : "text-[color:var(--aqt-fg-muted)]"
          )}
        />
      ))}
    </HoverPrefetchLink>
  );

  const score = (row: RowView) => {
    if (!row.hasScore) {
      return <span className={cn("text-label uppercase", FAINT)}>{t("common.vs")}</span>;
    }
    const tone = (slot: DuelSlot) =>
      row.winner === slot
        ? "text-[color:var(--aqt-teal)]"
        : row.winner
          ? FAINT
          : "text-[color:var(--aqt-fg-muted)]";
    return (
      <span className="inline-flex items-baseline gap-1 font-display text-title font-bold leading-none tabular-nums">
        <span className={tone(1)}>{row.scoreOne}</span>
        <span className={cn("font-medium", FAINT)}>–</span>
        <span className={tone(2)}>{row.scoreTwo}</span>
      </span>
    );
  };

  // One pip per played map: teal when the left seat took it, neutral when the
  // right did, hollow while no result decides it. Read off the same series
  // slots as the encounter page's pips, so the two never disagree.
  const pips = (encounter: Encounter, row: RowView) => {
    const played = buildSeriesSlots(encounter).filter(
      (slot) => slot.match != null || acceptedScore(slot.game, encounter.teams) != null
    );
    if (!played.length) return null;
    const summary = played
      .map((slot) =>
        slot.winner === 1 ? row.names.one : slot.winner === 2 ? row.names.two : t("encounters.detail.tie")
      )
      .join(", ");
    return (
      <span
        role="img"
        aria-label={t("encounters.detail.pipsAria", { summary })}
        className="inline-flex items-center gap-[3px]"
      >
        {played.map((slot) => (
          <span
            key={slot.index}
            aria-hidden
            className={cn(
              "size-[7px] shrink-0 rounded-[2px]",
              slot.winner === 1
                ? "bg-[color:var(--aqt-teal)]"
                : slot.winner === 2
                  ? "bg-[color:var(--aqt-fg-dim)]"
                  : "border border-[color:var(--aqt-fg-faint)]"
            )}
          />
        ))}
      </span>
    );
  };

  const liveDot = (
    <StatusDot className="size-[7px] text-[color:var(--aqt-status-live)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--aqt-status-live)_18%,transparent)] [animation:aqtPulse_2s_ease-in-out_infinite] motion-reduce:animate-none" />
  );

  const logs = (encounter: Encounter, className?: string) => (
    // Lifted above the stretched row link so the download stays its own target.
    <span className="relative z-10 inline-flex">
      <MatchLogIndicator
        hasLogs={encounter.has_logs}
        className={className}
        logs={
          encounter.has_logs
            ? (encounter.matches ?? []).map((match) => ({
                matchId: match.id,
                rawAvailable: match.raw_available,
                label: `${mapWithModeName(match.map, match.mode) ?? t("encounters.match.mapAlt")} · #${match.id}`
              }))
            : undefined
        }
      />
    </span>
  );

  const header: Array<{ label: string; className?: string }> = [
    { label: t("encounters.col.matchup") },
    { label: t("encounters.col.result"), className: "w-32" },
    { label: t("common.tournament") },
    { label: t("encounters.col.closeness"), className: "w-20 lg:w-36" },
    // Fits "6 нояб. 2026 г." and "11 месяцев назад" on one line from 1280px.
    { label: t("encounters.col.when"), className: "w-36 text-right" },
    { label: t("encounters.col.logs"), className: "w-16 text-center" }
  ];
  const cell = "border-b border-[color:var(--aqt-border)] px-3 py-3 align-middle";

  const tableRow = (encounter: Encounter) => {
    const row = view(encounter);
    return (
      <tr
        key={encounter.id}
        className={cn(
          // Safari does not make a `<tr>` the containing block of the stretched
          // link (WebKit 240961): the transform does, the clip keeps it in the row.
          "relative [clip-path:inset(0)] [transform:translate(0)] transition-colors hover:bg-[color:var(--aqt-overlay-2)]",
          isEncounterLive(encounter) &&
            "bg-[color:color-mix(in_srgb,var(--aqt-status-live)_5%,transparent)]"
        )}
      >
        <td className={cell}>
          <div className="flex min-w-0 items-center gap-2.5">
            {gameMark(encounter)}
            {matchupLink(encounter, row)}
          </div>
        </td>
        <td className={cell}>
          <div className="flex flex-col gap-1.5">
            {score(row)}
            <span className="flex items-center gap-2">
              <span className={cn("aqt-tnum text-label tabular-nums", FAINT)}>{row.bestOf}</span>
              {pips(encounter, row)}
            </span>
          </div>
        </td>
        <td className={cell}>
          <span className="block truncate text-caption font-medium text-[color:var(--aqt-fg-muted)]">
            {encounter.tournament?.name ?? "—"}
          </span>
          <span className="block truncate text-label text-[color:var(--aqt-fg-dim)]">
            {row.stage} · {row.round}
          </span>
        </td>
        <td className={cell}>
          {row.closeness == null ? (
            <span className={FAINT}>—</span>
          ) : (
            <span className="flex min-w-0 items-center gap-2">
              <span className="hidden h-1.5 flex-1 overflow-hidden rounded-full bg-[color:var(--aqt-overlay-3)] lg:block">
                {/* `block`: an inline span ignores its width and the bar renders 0x0. */}
                <span
                  data-closeness-fill
                  className="block h-full rounded-full bg-[color:var(--aqt-teal)]"
                  style={{ width: `${Math.round(row.closeness * 100)}%` }}
                />
              </span>
              <span className="aqt-tnum whitespace-nowrap text-label font-semibold tabular-nums text-[color:var(--aqt-fg-muted)]">
                {row.closenessText}
              </span>
            </span>
          )}
        </td>
        <td className={cn(cell, "text-right")}>
          {/* Sentence case: an uppercase, tracked date shouted and wrapped. */}
          <span className="flex flex-col items-end gap-0.5 whitespace-nowrap leading-tight">
            <span className="text-caption font-medium tabular-nums text-[color:var(--aqt-fg-muted)]">
              {row.when.day}
            </span>
            {row.when.time ? (
              <span
                className={cn(
                  "inline-flex items-center gap-1 text-label tabular-nums",
                  row.when.live
                    ? "font-semibold text-[color:var(--aqt-status-live)]"
                    : "text-[color:var(--aqt-fg-dim)]"
                )}
              >
                {row.when.live ? liveDot : null}
                {row.when.time}
              </span>
            ) : null}
          </span>
        </td>
        <td className={cn(cell, "text-center")}>{logs(encounter)}</td>
      </tr>
    );
  };

  const card = (encounter: Encounter) => {
    const row = view(encounter);
    const when = [row.when.day, row.when.time].filter(Boolean).join(" · ");
    return (
      <Card
        asChild
        key={encounter.id}
        className={cn(
          "relative flex flex-col gap-2 p-3 transition-colors hover:bg-[color:var(--aqt-overlay-2)]",
          isEncounterLive(encounter) && "border-[color:color-mix(in_srgb,var(--aqt-status-live)_45%,transparent)]"
        )}
      >
        <li>
          <div className="flex items-center gap-3">
            {gameMark(encounter)}
            {matchupLink(encounter, row, "flex-1 after:rounded-xl")}
            {score(row)}
          </div>
          <p className="truncate text-label text-[color:var(--aqt-fg-dim)]">
            {[encounter.tournament?.name, row.stage, row.round, row.bestOf].filter(Boolean).join(" · ")}
          </p>
          <div className="flex items-center gap-3 text-label">
            <span
              className={cn(
                "inline-flex min-w-0 items-center gap-1.5 font-medium tabular-nums",
                row.when.live ? "text-[color:var(--aqt-status-live)]" : "text-[color:var(--aqt-fg-muted)]"
              )}
            >
              {row.when.live ? liveDot : null}
              <span className="truncate">{when}</span>
            </span>
            {/* Labelled: on a card there is no column head to name the number. */}
            {row.closenessText ? (
              <span className="whitespace-nowrap tabular-nums text-[color:var(--aqt-fg-dim)]">
                {t("encounters.table.closenessValue", { value: row.closenessText })}
              </span>
            ) : null}
            {/* 40px on a phone: the card is a link, the badge is the one other target. */}
            <span className="ml-auto">{logs(encounter, "size-10")}</span>
          </div>
        </li>
      </Card>
    );
  };

  const skeletonRows = Array.from({ length: SKELETON_ROWS }, (_, index) => index);

  return (
    <div className={cn("min-w-0", className)}>
      <ul aria-label={t("encounters.table.label")} aria-busy={loading || undefined} className="flex flex-col gap-2 md:hidden">
        {loading
          ? skeletonRows.map((index) => (
              <Card asChild key={index} className="flex flex-col gap-2 p-3">
                <li>
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-3 w-3/4" />
                  <Skeleton className="h-3 w-1/2" />
                </li>
              </Card>
            ))
          : rows.map(card)}
      </ul>

      <Card className="hidden overflow-hidden md:block">
        <table
          aria-busy={loading || undefined}
          className="w-full table-fixed border-separate border-spacing-0 [&>tbody>tr:last-child>td]:border-b-0"
        >
          <caption className="sr-only">{t("encounters.table.label")}</caption>
          <thead className="bg-[color:var(--aqt-overlay-1)]">
            <tr>
              {header.map((column) => (
                <th
                  key={column.label}
                  scope="col"
                  className={cn(
                    eyebrowClass(),
                    "border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-left font-bold whitespace-nowrap",
                    column.className
                  )}
                >
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading
              ? skeletonRows.map((index) => (
                  <tr key={index}>
                    {header.map((column) => (
                      <td key={column.label} className={cell}>
                        <Skeleton className="h-8 w-full" />
                      </td>
                    ))}
                  </tr>
                ))
              : rows.map(tableRow)}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
