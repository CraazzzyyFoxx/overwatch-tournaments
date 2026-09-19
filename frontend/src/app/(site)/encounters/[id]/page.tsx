import type { Metadata } from "next";
import Link from "next/link";
import { getFormatter, getTranslations } from "next-intl/server";
import { ArrowLeft } from "lucide-react";

import { cn } from "@/lib/utils";
import { HeroCoord, HeroStamp, HeroStat, PageHero } from "@/components/site/PageHero";
import { StagePill } from "@/components/match/cells";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import { SITE_NAME, SITE_URL } from "@/config/site";
import encounterService from "@/services/encounter.service";
import { getEncounterState } from "@/lib/encounter-status";
import EncounterScoreboard from "./components/EncounterScoreboard";
import EncounterMapRow from "./components/EncounterMapRow";
import EncounterRosterPanel from "@/components/match/EncounterRosterPanel";
import EncounterSeriesStats from "./components/EncounterSeriesStats";
import EncounterCaptainReports from "./components/EncounterCaptainReports";
import EncounterPregamePanel from "./components/EncounterPregamePanel";
import { PregameRoomLink } from "./components/PregameRoomLink";
import { Pill } from "@/components/match/EncounterAtoms";
import {
  buildSeriesSlots,
  countMapWins,
  formatCloseness,
  formatSeriesClock,
  getSeriesSeconds,
  getSeriesVerdict,
  getStageKind
} from "@/lib/encounter-detail";
import styles from "@/components/match/EncounterDetail.module.css";

export const dynamic = "force-dynamic";

export async function generateMetadata(props: {
  params: Promise<{ id: number }>;
}): Promise<Metadata> {
  const params = await props.params;
  const encounter = await encounterService.getEncounter(params.id);
  const t = await getTranslations();

  // Both sides are nullable until the bracket resolves them, so never reach
  // straight into `.name` here — this route is crawled.
  const home = encounter.home_team?.name ?? t("common.tbd");
  const away = encounter.away_team?.name ?? t("common.tbd");
  const metaTitle = t("encounters.detail.metaTitle", { home, away });
  const title = `${metaTitle} | ${SITE_NAME}`;
  const description = t("encounters.detail.metaDescription", {
    home,
    away,
    siteName: SITE_NAME
  });

  return {
    title,
    description,
    alternates: { canonical: `${SITE_URL}/encounters/${encounter.id}` },
    openGraph: {
      title,
      description,
      url: `${SITE_URL}/encounters/${encounter.id}`,
      siteName: SITE_NAME,
      type: "website"
    },
    twitter: { card: "summary_large_image", title, description }
  };
}

const EncounterPage = async (props: { params: Promise<{ id: number }> }) => {
  const params = await props.params;
  const encounter = await encounterService.getEncounter(params.id);
  const t = await getTranslations();
  const format = await getFormatter();

  const homeName = encounter.home_team?.name ?? t("common.tbd");
  const awayName = encounter.away_team?.name ?? t("common.tbd");
  const tournamentGrid = encounter.tournament?.division_grid_version ?? null;
  const stageLabel =
    encounter.stage_item?.name ?? encounter.stage?.name ?? t("common.unassignedStage");

  const slots = buildSeriesSlots(encounter);
  const playedSlots = slots.filter((slot) => slot.match != null);
  const verdict = getSeriesVerdict(encounter);
  const mapWins = countMapWins(encounter);
  const state = getEncounterState(encounter);
  const clockUnits = {
    h: t("common.duration.h"),
    m: t("common.duration.m"),
    s: t("common.duration.s")
  };
  const seriesSeconds = getSeriesSeconds(encounter);
  const seriesClock = formatSeriesClock(seriesSeconds, clockUnits);
  const averageClock =
    seriesSeconds != null && playedSlots.length > 0
      ? formatSeriesClock(seriesSeconds / playedSlots.length, clockUnits)
      : null;
  const closeness = formatCloseness(encounter.closeness);
  const logs = playedSlots
    .filter((slot) => slot.match?.log_name)
    .map((slot) => ({
      matchId: slot.match!.id,
      label: slot.match!.map?.name ?? undefined
    }));

  const lede =
    verdict.outcome === "win"
      ? t("encounters.detail.ledeWin", {
          winner: verdict.winner === "home" ? homeName : awayName,
          loser: verdict.winner === "home" ? awayName : homeName,
          winnerScore: Math.max(encounter.score.home, encounter.score.away),
          loserScore: Math.min(encounter.score.home, encounter.score.away),
          maps: playedSlots.length
        })
      : verdict.outcome === "draw"
        ? t("encounters.detail.ledeDraw", { maps: playedSlots.length })
        : t("encounters.detail.ledePending", { format: encounter.best_of });

  return (
    <div className={styles.surface}>
      <PageHero
        align="start"
        titleClassName="text-[clamp(1.35rem,2.4vw,2rem)]"
        eyebrow={
          <>
            {/* The new design's back affordance is a mono coordinate link in the
                eyebrow, not a standalone outline button above the page. */}
            <Link
              href="/encounters"
              className="inline-flex items-center gap-1.5 text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)] transition-colors hover:text-[color:var(--aqt-teal)]"
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
              {t("encounters.detail.back")}
            </Link>
            <HeroCoord className="inline-flex flex-wrap items-center gap-2">
              <Link href={`/tournaments/${encounter.tournament_id}`} className={styles.crumbLink}>
                {encounter.tournament?.name ?? t("common.tournament")}
              </Link>
              <span aria-hidden className={styles.crumbSep}>
                /
              </span>
              <span>{stageLabel}</span>
              <span aria-hidden className={styles.crumbSep}>
                /
              </span>
              <span>{t("encounters.roundNum", { round: encounter.round })}</span>
            </HeroCoord>
          </>
        }
        title={t.rich("encounters.detail.heroTitle", {
          home: homeName,
          away: awayName,
          em: (chunks) => <em>{chunks}</em>
        })}
        meta={
          <>
            <Pill
              tone={
                state === "Live"
                  ? "danger"
                  : state === "Final"
                    ? "good"
                    : state === "Upcoming"
                      ? "warn"
                      : "neutral"
              }
              live={state === "Live"}
            >
              {t(`encounters.state.${STATE_KEY[state]}` as never)}
            </Pill>
            <Pill>{t("encounters.bestOfShort", { count: encounter.best_of })}</Pill>
            <StagePill kind={getStageKind(encounter)}>{stageLabel}</StagePill>
            {encounter.result_status !== "none" ? (
              <Pill
                tone={
                  encounter.result_status === "confirmed"
                    ? "good"
                    : encounter.result_status === "disputed"
                      ? "danger"
                      : "warn"
                }
              >
                {t(`encounters.result.${RESULT_KEY[encounter.result_status]}` as never)}
              </Pill>
            ) : null}
            {encounter.challonge_id != null ? (
              <Pill>
                <span className={styles.label}>{t("encounters.detail.challonge")}</span>
                <span className={styles.mono}>#{encounter.challonge_id}</span>
              </Pill>
            ) : null}
          </>
        }
        lede={lede}
        actions={
          <div className={styles.heroActions}>
            {/* Both controls share the module's button geometry. The pre-game
                link used to be a shadcn <Button variant="outline"> (shadcn theme
                vars) sitting beside a labelled pill wrapping the log icon, so
                the pair had different heights, radii, borders and weights. */}
            <PregameRoomLink
              encounterId={encounter.id}
              tournamentId={encounter.tournament_id}
              className={styles.button}
            />
            {logs.length > 0 ? (
              <MatchLogIndicator hasLogs logs={logs} className={styles.iconButton} />
            ) : null}
          </div>
        }
        aside={
          <div className={styles.heroStats}>
            <HeroStat
              label={t("encounters.detail.statMaps")}
              value={playedSlots.length}
              sub={t("encounters.detail.statMapsSub", {
                format: t("encounters.bestOfShort", { count: encounter.best_of }),
                home: mapWins.home,
                away: mapWins.away
              })}
            />
            <HeroStat
              label={t("encounters.detail.statDuration")}
              value={seriesClock ?? "—"}
              sub={
                averageClock
                  ? t("encounters.detail.statDurationSub", { value: averageClock })
                  : t("encounters.detail.statNoTiming")
              }
            />
            <HeroStat
              label={t("encounters.col.closeness")}
              value={closeness ?? "—"}
              sub={
                closeness
                  ? t("encounters.detail.statClosenessSub")
                  : t("encounters.detail.statNoCloseness")
              }
            />
            <HeroStat
              label={t("encounters.col.logs")}
              value={`${logs.length}/${playedSlots.length}`}
              sub={
                encounter.has_logs
                  ? t("encounters.media.logsAvailable")
                  : t("encounters.media.noLogs")
              }
            />
          </div>
        }
        stamp={
          <>
            {encounter.scheduled_at ? (
              <HeroStamp
                label={t("encounters.detail.scheduledAt")}
                value={format.dateTime(new Date(encounter.scheduled_at), DATE_TIME)}
              />
            ) : null}
            {encounter.started_at ? (
              <HeroStamp
                label={t("encounters.detail.startedAt")}
                value={format.dateTime(new Date(encounter.started_at), DATE_TIME)}
              />
            ) : null}
            {encounter.ended_at ? (
              <HeroStamp
                label={t("encounters.detail.endedAt")}
                value={format.dateTime(new Date(encounter.ended_at), DATE_TIME)}
              />
            ) : null}
            {encounter.confirmed_at ? (
              <HeroStamp
                label={t("encounters.detail.confirmedAt")}
                value={format.dateTime(new Date(encounter.confirmed_at), DATE_TIME)}
              />
            ) : null}
          </>
        }
      />

      <section aria-label={t("encounters.detail.scoreboard")}>
        <EncounterScoreboard encounter={encounter} />
      </section>

      {/* Owns its own <section>: renders nothing unless the tournament has
          pre-game rules configured for this encounter. */}
      <EncounterPregamePanel encounterId={encounter.id} homeName={homeName} awayName={awayName} />

      <section aria-label={t("common.maps")}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>{t("common.maps")}</h2>
          <span className={styles.sectionMeta}>
            {t("encounters.detail.mapsMeta", {
              played: playedSlots.length,
              slots: slots.length
            })}
          </span>
        </div>
        <div className={cn(styles.card, styles.mapList)}>
          {slots.map((slot) => (
            <EncounterMapRow
              key={slot.match?.id ?? `empty-${slot.index}`}
              slot={slot}
              homeName={homeName}
              awayName={awayName}
              seriesCompleted={verdict.outcome !== "unplayed"}
              tournamentGrid={tournamentGrid}
              clockUnits={clockUnits}
            />
          ))}
        </div>
      </section>

      <section aria-label={t("encounters.detail.rosters")}>
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>{t("encounters.detail.rosters")}</h2>
          <span className={styles.sectionMeta}>{t("encounters.detail.rostersMeta")}</span>
        </div>
        <div className={styles.rosterGrid}>
          <EncounterRosterPanel
            team={encounter.home_team}
            side="home"
            tournamentGrid={tournamentGrid}
          />
          <EncounterRosterPanel
            team={encounter.away_team}
            side="away"
            tournamentGrid={tournamentGrid}
          />
        </div>
      </section>

      {playedSlots.length > 0 ? (
        <section aria-label={t("encounters.detail.seriesStats")}>
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>{t("encounters.detail.seriesStats")}</h2>
            <span className={styles.sectionMeta}>
              {t("encounters.detail.seriesStatsMeta", { maps: playedSlots.length })}
            </span>
          </div>
          {encounter.has_logs ? (
            <EncounterSeriesStats
              matchIds={playedSlots.map((slot) => slot.match!.id)}
              homeTeamId={encounter.home_team_id}
              awayTeamId={encounter.away_team_id}
              tournamentGrid={tournamentGrid}
            />
          ) : (
            <div className={styles.card}>
              <p className={cn(styles.cardBody, styles.statsNotice)}>
                {t("encounters.detail.seriesStatsNoLogs")}
              </p>
            </div>
          )}
        </section>
      ) : null}

      <EncounterCaptainReports
        encounterId={encounter.id}
        homeTeamId={encounter.home_team_id}
        awayTeamId={encounter.away_team_id}
        homeName={homeName}
        awayName={awayName}
      />
    </div>
  );
};

const DATE_TIME = {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit"
} as const;

/** `EncounterState` sentinels are English words; the catalog keys are camelCase. */
const STATE_KEY: Record<string, string> = {
  Live: "live",
  Upcoming: "upcoming",
  Final: "final",
  Pending: "pending",
  Open: "open"
};

/** `result_status` is snake_case on the wire; the catalog group is camelCase. */
const RESULT_KEY: Record<string, string> = {
  none: "none",
  pending_confirmation: "pendingConfirmation",
  confirmed: "confirmed",
  disputed: "disputed"
};

export default EncounterPage;
