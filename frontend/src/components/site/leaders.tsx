import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import {
  Calendar,
  Clock,
  Crown,
  Globe,
  Layers,
  Scale,
  Swords,
  Trophy,
  Users,
  type LucideIcon
} from "lucide-react";

import { PlaceBadge } from "@/components/ui/place-badge";
import { getFormatter } from "@/lib/datetime/server";
import { getPlayerSlug } from "@/lib/player";
import type { PlayerStatistics } from "@/types/statistics.types";
import { Column, ColumnHead, EmptyNote, LoadError } from "./open-layout";

/**
 * Totals list + two leaderboards side by side (mock `.leaders`): the totals
 * column a little narrower, both stacking below 1100px with the totals full
 * width over them, one column below 768px.
 */
export function LeadersGrid({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="grid grid-cols-1 items-start gap-x-10 gap-y-8 md:grid-cols-2 min-[1100px]:grid-cols-[minmax(0,.9fr)_repeat(2,minmax(0,1fr))] [&>:first-child]:md:col-span-2 [&>:first-child]:min-[1100px]:col-span-1">
      {children}
    </div>
  );
}

export type KpiKey =
  | "communities"
  | "tournaments"
  | "teams"
  | "players"
  | "encounters"
  | "maps"
  | "days"
  | "hours"
  | "champions";

const KPI: Record<KpiKey, { icon: LucideIcon; color: string }> = {
  communities: { icon: Globe, color: "var(--aqt-rose)" },
  tournaments: { icon: Trophy, color: "var(--aqt-violet)" },
  teams: { icon: Scale, color: "var(--aqt-blue)" },
  players: { icon: Users, color: "var(--aqt-emerald)" },
  encounters: { icon: Swords, color: "var(--aqt-amber)" },
  maps: { icon: Layers, color: "var(--aqt-silver)" },
  days: { icon: Calendar, color: "var(--aqt-bronze)" },
  hours: { icon: Clock, color: "var(--aqt-teal)" },
  champions: { icon: Crown, color: "var(--aqt-gold)" }
};

/**
 * The totals column (mock `kpiList`). `totals: null` is a load error. A key
 * the response does not carry is skipped rather than drawn as a zero.
 */
export async function KpiList({
  title,
  totals,
  keys
}: Readonly<{
  title: ReactNode;
  totals: Partial<Record<KpiKey, number | null | undefined>> | null;
  keys: readonly KpiKey[];
}>) {
  const [t, format] = await Promise.all([getTranslations("site.kpi"), getFormatter()]);
  const rows = totals ? keys.filter((key) => typeof totals[key] === "number") : [];

  return (
    <Column>
      <ColumnHead title={title} />
      {totals === null ? (
        <LoadError />
      ) : (
        <dl className="gap-x-10 max-[1099px]:columns-2 max-[767px]:columns-1">
          {rows.map((key) => {
            const { icon: Icon, color } = KPI[key];
            return (
              <div
                key={key}
                className="flex min-h-11 break-inside-avoid items-center justify-between gap-3 border-b border-[color:var(--aqt-border)] last:border-b-0"
              >
                <dt className="flex min-w-0 items-center gap-2.5 font-[family-name:var(--aqt-data)] text-caption font-semibold uppercase leading-[1.25] tracking-label text-[color:var(--aqt-fg-muted)]">
                  <span
                    className="inline-flex size-[26px] shrink-0 items-center justify-center rounded-[7px] bg-[color:color-mix(in_srgb,var(--kpi-c)_14%,transparent)] text-[color:var(--kpi-c)]"
                    style={{ "--kpi-c": color } as CSSProperties}
                  >
                    <Icon className="size-3.5" aria-hidden />
                  </span>
                  {t(key)}
                </dt>
                <dd className="font-display text-heading font-bold leading-none tabular-nums text-[color:var(--aqt-fg)]">
                  {format.number(totals![key] as number)}
                </dd>
              </div>
            );
          })}
        </dl>
      )}
    </Column>
  );
}

/**
 * A leaderboard as an open column (mock `leaderboard`). `rows: null` is a
 * load error, `[]` is empty and `empty` says why.
 */
export async function LeaderboardColumn({
  title,
  sub,
  rows,
  value,
  empty
}: Readonly<{
  title: ReactNode;
  sub?: ReactNode;
  rows: PlayerStatistics[] | null;
  /** `wins` renders `3×` in amber, `winrate` a percentage in emerald. */
  value: "wins" | "winrate";
  empty?: ReactNode;
}>) {
  const format = await getFormatter();
  const accent = value === "wins" ? "var(--aqt-amber)" : "var(--aqt-emerald)";

  return (
    <Column>
      <ColumnHead title={title} sub={sub} />
      {rows === null ? (
        <LoadError />
      ) : rows.length === 0 ? (
        <EmptyNote>{empty}</EmptyNote>
      ) : (
        <ol>
          {rows.map((player, index) => (
            <li
              key={player.id}
              className="flex min-h-11 items-center gap-2.5 border-b border-[color:var(--aqt-border)] text-caption last:border-b-0"
            >
              {index < 3 ? (
                <PlaceBadge place={index + 1} className="size-[22px] min-w-[22px] px-0" />
              ) : (
                <span className="inline-flex size-[22px] shrink-0 items-center justify-center font-[family-name:var(--aqt-data)] text-label font-bold tabular-nums text-[color:var(--aqt-fg-dim)]">
                  #{index + 1}
                </span>
              )}
              <Link
                href={`/users/${getPlayerSlug(player.name)}`}
                prefetch={false}
                title={player.name}
                className="min-w-0 flex-1 truncate font-semibold text-[color:var(--aqt-fg)] hover:text-[color:var(--aqt-fg-muted)]"
              >
                {player.name}
              </Link>
              <span className="min-w-12 text-right font-bold tabular-nums" style={{ color: accent }}>
                {value === "wins"
                  ? `${format.number(player.value)}×`
                  : format.number(player.value, {
                      style: "percent",
                      minimumFractionDigits: 1,
                      maximumFractionDigits: 1
                    })}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Column>
  );
}
