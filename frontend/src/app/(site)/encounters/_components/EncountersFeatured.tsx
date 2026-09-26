"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import TeamName, { type TeamNameInput } from "@/components/TeamName";
import { StatusDot } from "@/components/ui/status-dot";
import { getEncounterState, getEncounterWinner } from "@/lib/encounter/status";
import { cn } from "@/lib/utils";
import type { Encounter, EncounterOverview } from "@/types/encounter.types";

import { formatDuration, getSeriesDuration } from "./encounters.helpers";
import styles from "./Encounters.module.css";

/** The two highlight panels: the closest finishes and what is on right now. */
export function EncountersFeatured({ overview }: Readonly<{ overview: EncounterOverview }>) {
  const t = useTranslations();
  const liveOrUpcoming = overview.featured.live.length
    ? overview.featured.live
    : overview.featured.upcoming;

  return (
    <section aria-label={t("encounters.featured.title")}>
      <div className={styles.sectionHead}>
        <h2 className={styles.sectionTitle}>{t("encounters.featured.title")}</h2>
        <span className={styles.sectionMeta}>{t("encounters.featured.meta")}</span>
      </div>
      <div className={styles.grid2}>
        <FeaturedPanel
          title={t("encounters.featured.closestTitle")}
          subtitle={t("encounters.featured.closestSub")}
          encounters={overview.featured.closest}
          variant="closest"
        />
        <FeaturedPanel
          title={t("encounters.featured.liveTitle")}
          subtitle={t("encounters.featured.liveSub")}
          encounters={liveOrUpcoming}
          variant="live"
        />
      </div>
    </section>
  );
}

function FeaturedPanel({
  title,
  subtitle,
  encounters,
  variant
}: Readonly<{
  title: string;
  subtitle: string;
  encounters: Encounter[];
  variant: "closest" | "live";
}>) {
  const t = useTranslations();
  const format = useFormatter();
  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        <div>
          <div className={styles.cardTitle}>{title}</div>
          <div className={styles.cardSub}>{subtitle}</div>
        </div>
      </div>
      <div>
        {encounters.length ? (
          encounters.slice(0, 4).map((encounter) => {
            const winner = getEncounterWinner(encounter);
            const state = getEncounterState(encounter);
            const isLive = variant === "live" && state === "Live";
            const isUpcoming = variant === "live" && state === "Upcoming";
            const closenessPct =
              encounter.closeness != null ? Math.round(encounter.closeness * 100) : null;
            const scheduledAt = encounter.scheduled_at ? new Date(encounter.scheduled_at) : null;
            return (
              <Link key={encounter.id} href={`/encounters/${encounter.id}`} className={styles.feat}>
                <div>
                  <div className={styles.matchup}>
                    {isLive ? (
                      <span className={cn(styles.statusTag, styles.statusLive)}>
                        <StatusDot className="shadow-[0_0_0_3px_color-mix(in_srgb,currentColor_20%,transparent)]" />
                        {t("encounters.state.live")}
                      </span>
                    ) : null}
                    {isUpcoming ? (
                      <span className={cn(styles.statusTag, styles.statusUpcoming)}>
                        <StatusDot />
                        {t("encounters.state.soon")}
                      </span>
                    ) : null}
                    <TeamChip team={encounter.home_team} />
                    <span className={styles.vs}>{t("common.vs")}</span>
                    <TeamChip team={encounter.away_team} />
                  </div>
                  <div className={styles.featMeta}>
                    {[
                      encounter.tournament?.name ?? t("common.tournament"),
                      encounter.stage_item?.name ??
                        encounter.stage?.name ??
                        t("common.unassignedStage"),
                      t("encounters.roundNum", { round: encounter.round }),
                      t("encounters.mapsCount", { count: encounter.matches?.length ?? 0 }),
                      formatDuration(getSeriesDuration(encounter))
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                </div>
                <div className={styles.featSide}>
                  {variant === "live" && isUpcoming ? (
                    <span className={styles.featTime}>
                      {scheduledAt
                        ? format.dateTime(scheduledAt, { month: "short", day: "numeric" })
                        : "—"}
                    </span>
                  ) : (
                    <span className={cn(styles.featScore, "tabular-nums")}>
                      <span
                        className={
                          winner === "home" ? styles.featScoreWinner : styles.featScoreLoser
                        }
                      >
                        {encounter.score.home}
                      </span>
                      <span className={styles.scoreSep}>–</span>
                      <span
                        className={
                          winner === "away" ? styles.featScoreWinner : styles.featScoreLoser
                        }
                      >
                        {encounter.score.away}
                      </span>
                    </span>
                  )}
                  {variant === "closest" && closenessPct != null ? (
                    <span className={cn(styles.badgeCloseness, "tabular-nums")}>
                      ⚡ {closenessPct}%
                    </span>
                  ) : null}
                  {isLive ? (
                    <span className={styles.featTime}>{t("encounters.state.live")}</span>
                  ) : null}
                </div>
              </Link>
            );
          })
        ) : (
          <div className={styles.empty}>{t("encounters.featured.empty")}</div>
        )}
      </div>
    </div>
  );
}

function TeamChip({ team }: Readonly<{ team?: TeamNameInput | null }>) {
  const t = useTranslations();
  return (
    <span className={styles.teamChip}>
      <TeamName team={team} fallback={t("common.tbd")} size="xs" />
    </span>
  );
}
