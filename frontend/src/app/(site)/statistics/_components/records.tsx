import { Fragment, type ReactNode } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { HandleLabel } from "@/components/HandleLabel";
import { formatCloseness } from "@/lib/encounter/detail";
import type { Formatter } from "@/lib/datetime";
import { getPlayerSlug } from "@/lib/player";
import { tournamentHref } from "@/lib/tournament/url";
import { cn } from "@/lib/utils";
import type { StatRecord } from "@/types/statistics.types";

import { clock } from "./statistics.model";

// One record's presentation, shared by the almanac's records section and the
// landing (its leaders block and its hero's results feed), so a record reads
// the same wherever it shows.

const LINK_CLASS =
  "rounded-sm text-[color:var(--aqt-fg)] transition-colors hover:text-[color:var(--aqt-teal)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]";

/** A record's figure as text, and the dim words saying what it counts (or `null`). */
export function useRecordFigure(record: StatRecord, format: Formatter): { figure: string; unit: string | null } {
  const t = useTranslations("statistics.records");
  const { value } = record;
  const figure = format.number(value, { maximumFractionDigits: 0 });
  switch (record.code) {
    case "win_streak":
      return { figure, unit: t("unit.streak", { count: value }) };
    case "biggest_upset":
      return {
        figure: `−${figure} SR`,
        unit: record.relative === null ? null : t("unit.upset", { pct: format.number(record.relative, { style: "percent" }) })
      };
    case "underdog_champion":
      return { figure: t("ofTotal", { value, total: record.of_total ?? value }), unit: t("unit.underdog") };
    case "closest_final":
      return { figure: formatCloseness(value) ?? figure, unit: t("unit.closeness") };
    case "most_mvps":
      return { figure, unit: t("unit.mvps", { count: value }) };
    case "longest_map":
      return { figure: clock(value), unit: null };
    default:
      return { figure, unit: null };
  }
}

/** The figure, and the dim words saying what it counts. `lg` for a featured record, `md` for a log row. */
export function RecordFigure({ record, format, size }: Readonly<{ record: StatRecord; format: Formatter; size: "lg" | "md" }>) {
  const { figure, unit } = useRecordFigure(record, format);
  return size === "lg" ? (
    <p className="mt-3 flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span className="font-display text-headline font-semibold tabular-nums text-[color:var(--aqt-fg)]">{figure}</span>
      {unit ? <span className="text-caption text-[color:var(--aqt-fg-dim)]">{unit}</span> : null}
    </p>
  ) : (
    <p className="text-right">
      <span className="block font-display text-title font-semibold tabular-nums text-[color:var(--aqt-fg)]">
        {figure}
      </span>
      {unit ? <span className="text-label text-[color:var(--aqt-fg-dim)]">{unit}</span> : null}
    </p>
  );
}

/** Who holds it: a player (linked to the profile), else the team. */
export function RecordHolder({ record, className }: Readonly<{ record: StatRecord; className: string }>) {
  if (record.player) {
    return (
      <p className={className}>
        <Link
          href={`/users/${getPlayerSlug(record.player.name)}`}
          prefetch={false}
          title={record.player.name}
          className={LINK_CLASS}
        >
          <HandleLabel handle={record.player.name} />
        </Link>
      </p>
    );
  }
  return record.team ? (
    <p className={className} title={record.team.name}>
      {record.team.name}
    </p>
  ) : null;
}

/** Where it happened, one `·`-joined meta line: the matchup, the series score, the map, the tournament, the dates. */
export function RecordContext({ record, format, className }: Readonly<{ record: StatRecord; format: Formatter; className: string }>) {
  const t = useTranslations("statistics.records");
  const parts: ReactNode[] = [];
  if (record.opponent) {
    parts.push(
      record.player && record.team
        ? t("matchup", { team: record.team.name, opponent: record.opponent.name })
        : t("against", { opponent: record.opponent.name })
    );
  }
  if (record.score) {
    const score = `${record.score[0]}:${record.score[1]}`;
    parts.push(
      record.encounter_id === null ? (
        score
      ) : (
        <Link href={`/encounters/${record.encounter_id}`} prefetch={false} className={cn("aqt-tnum", LINK_CLASS)}>
          {score}
        </Link>
      )
    );
  }
  if (record.map) {
    parts.push(
      record.match_id === null ? (
        record.map.name
      ) : (
        <Link href={`/matches/${record.match_id}`} prefetch={false} className={LINK_CLASS}>
          {record.map.name}
        </Link>
      )
    );
  }
  if (record.tournament) {
    parts.push(
      <Link href={tournamentHref(record.tournament.id)} prefetch={false} className={LINK_CLASS}>
        {record.tournament.name}
      </Link>
    );
  }
  if (record.started_at && record.ended_at) {
    parts.push(
      format.dateTimeRange(new Date(record.started_at), new Date(record.ended_at), {
        day: "numeric",
        month: "short",
        year: "numeric"
      })
    );
  }
  if (parts.length === 0) return null;
  return (
    <p className={cn("text-caption text-[color:var(--aqt-fg-muted)]", className)}>
      {parts.map((part, index) => (
        <Fragment key={index}>
          {index > 0 ? <span className="text-[color:var(--aqt-fg-dim)]"> · </span> : null}
          {part}
        </Fragment>
      ))}
    </p>
  );
}
