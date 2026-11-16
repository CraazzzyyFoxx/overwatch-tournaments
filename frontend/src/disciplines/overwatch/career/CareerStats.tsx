"use client";

import type { CareerQueue } from "@/types/user.types";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { ProfileStat } from "@/components/profile/atoms";
import { Progress } from "@/components/ui/progress";
import type { DisciplineMetadata } from "@/types/discipline.types";
import { useFormatter } from "@/lib/datetime/client";
import { LOW_SAMPLE_GAMES, winrateColor } from "@/lib/colors";

import { useHeroClass } from "../character/classes";
import { formatStatValue } from "../character/utils";
import { queueOutputRate } from "./career-model";
import { useHeroFaces } from "./use-career";

const EMPTY = "—";
/** The most heroes a role row has room to show. */
const MAINS = 5;

/** The queue's headline figures. Meta tiles appear only when the server sent them. */
export function CareerKpis({ queue }: Readonly<{ queue: CareerQueue }>) {
  const t = useTranslations("users.career.kpi");
  const format = useFormatter();
  const percent = (value: number) => format.number(value, { style: "percent", maximumFractionDigits: 0 });
  const output = queueOutputRate(queue);
  const games = queue.games_played;
  const winrate = queue.winrate;

  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-4">
      <ProfileStat
        size="md"
        label={t("hours")}
        value={t("hoursValue", { hours: format.number(queue.seconds / 3600, { maximumFractionDigits: 1 }) })}
      />
      <ProfileStat size="md" label={t("games")} value={games == null ? EMPTY : format.number(games)} />
      <ProfileStat
        size="md"
        label={t("winrate")}
        value={winrate == null ? EMPTY : percent(winrate)}
        color={winrate == null ? undefined : winrateColor(winrate * 100, (games ?? 0) < LOW_SAMPLE_GAMES)}
        sub={games != null && queue.games_won != null && queue.games_lost != null ? t("record", { won: queue.games_won, lost: queue.games_lost }) : undefined}
      />
      <ProfileStat
        size="md"
        label={t("eliminations")}
        value={queue.rates.eliminations == null ? EMPTY : formatStatValue(format, "eliminations", queue.rates.eliminations)}
      />
      <ProfileStat
        size="md"
        label={t("deaths")}
        value={queue.rates.deaths == null ? EMPTY : formatStatValue(format, "deaths", queue.rates.deaths)}
      />
      <ProfileStat
        size="md"
        label={output === "healing_done" ? t("healing") : t("damage")}
        value={queue.rates[output] == null ? EMPTY : formatStatValue(format, "dmg", queue.rates[output])}
      />
      {queue.meta_fit != null ? (
        <ProfileStat size="md" label={t("metaFit")} value={percent(queue.meta_fit)} title={t("metaFitTitle")} />
      ) : null}
      {queue.ban_exposure != null ? (
        <ProfileStat size="md" label={t("banExposure")} value={percent(queue.ban_exposure)} title={t("banExposureTitle")} />
      ) : null}
    </div>
  );
}

/** Per role: its share of the time, the hero pool's size and the heroes the player mains. */
export function CareerRoles({
  queue,
  metadata
}: Readonly<{ queue: CareerQueue; metadata: DisciplineMetadata }>) {
  const t = useTranslations("users.career.roles");
  const format = useFormatter();
  const heroClass = useHeroClass(metadata);
  const faceOf = useHeroFaces(metadata.discipline.code);
  if (queue.roles.length === 0) return null;

  return (
    <ul className="flex flex-col divide-y divide-[color:var(--aqt-border)]">
      {queue.roles.map((role) => (
        <li key={role.role} className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-x-4 gap-y-1.5 py-2.5 first:pt-0 last:pb-0 sm:grid-cols-[9rem_minmax(0,1fr)_5.5rem_10rem]">
          <span className="flex items-center gap-1.5 text-caption font-semibold text-[color:var(--aqt-fg)]">
            {heroClass.icon(role.role, 16)}
            {heroClass.label(role.role)}
          </span>
          <span className="flex items-center gap-2">
            <Progress value={role.share * 100} size="sm" aria-label={heroClass.label(role.role)} />
            <span className="aqt-tnum w-10 shrink-0 text-right text-caption text-[color:var(--aqt-fg-muted)]">
              {format.number(role.share, { style: "percent", maximumFractionDigits: 0 })}
            </span>
          </span>
          <span className="aqt-tnum col-span-2 text-caption text-[color:var(--aqt-fg-dim)] sm:col-span-1">
            {t("pool", { size: format.number(role.pool_size, { maximumFractionDigits: 1 }) })}
          </span>
          <span className="col-span-2 flex items-center gap-1 sm:col-span-1 sm:justify-end" aria-label={t("mains")}>
            {role.mains.slice(0, MAINS).map((key) => (
              <CatalogEntityImage key={key} entity={faceOf(key)} size="sm" />
            ))}
          </span>
        </li>
      ))}
    </ul>
  );
}
