import type { Metadata } from "next";
import Link from "next/link";
import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import { getTranslations } from "next-intl/server";
import { getFormatter } from "@/lib/datetime/server";
import { MessageSquare } from "lucide-react";

import { LinkTabs } from "@/components/kit/LinkTabs";
import { BackLink } from "@/components/site/BackLink";
import { HeroCoord, HeroStamp, PageHero } from "@/components/site/PageHero";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { StatusDot } from "@/components/ui/status-dot";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import { EntityWorkspace } from "@/components/workspace/EntityWorkspace";
import { SITE_NAME, SITE_URL } from "@/config/site";
import encounterService from "@/services/encounter.service";
import ffaService from "@/services/ffa.service";
import pickBanService from "@/services/pickBan.service";
import captainService from "@/services/captain.service";
import FfaLobbyTable from "@/components/ffa/FfaLobbyTable";
import type { Encounter } from "@/types/encounter.types";
import { duelSeats, isLobby } from "@/lib/encounter/seats";
import type { PickBanState } from "@/types/tournament.types";
import { getEncounterState } from "@/lib/encounter/status";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import EncounterHeader, { type EncounterHeaderFact } from "./components/EncounterHeader";
import EncounterMapRow from "./components/EncounterMapRow";
import EncounterHistory from "./components/EncounterHistory";
import EncounterWatch from "./components/EncounterWatch";
import EncounterRosterPanel from "@/components/match/EncounterRosterPanel";
import EncounterSeriesStats from "./components/EncounterSeriesStats";
import EncounterCaptainReports from "./components/EncounterCaptainReports";
import EncounterPregamePanel from "./components/EncounterPregamePanel";
import { PregameRoomLink } from "./components/PregameRoomLink";
import { Badge } from "@/components/ui/badge";
import { acceptedScore } from "@/components/pick-ban/pick-ban-model";
import {
  buildSeriesSlots,
  countMapWins,
  formatCloseness,
  formatSeriesClock,
  getSeriesSeconds
} from "@/lib/encounter/detail";
import { mapWithModeName } from "@/lib/catalog/mode";
import { SURFACE, SectionHead } from "@/components/match/EncounterAtoms";

/** A crumb that links: the crumb row's own colour, teal under the pointer. */
const CRUMB_LINK = "transition-colors hover:text-[color:var(--aqt-teal)]";
const CRUMB_SEP = "opacity-45";

export async function generateMetadata(props: {
  params: Promise<{ id: number }>;
}): Promise<Metadata> {
  const params = await props.params;
  const [encounter, t] = await Promise.all([encounterService.getEncounter(params.id), getTranslations()]);

  // Both seats are empty until the bracket resolves them, so never reach
  // straight into `.name` here — this route is crawled. A lobby has no two
  // seats to name at all: its own name is the title.
  const [seatOne, seatTwo] = duelSeats(encounter.teams);
  const first = seatOne?.name ?? t("common.tbd");
  const second = seatTwo?.name ?? t("common.tbd");
  const lobby = isLobby(encounter);
  const metaTitle = lobby ? encounter.name : t("encounters.detail.metaTitle", { first, second });
  const title = `${metaTitle} | ${SITE_NAME}`;
  const description = lobby
    ? t("ffa.metaDescription", { lobby: encounter.name, siteName: SITE_NAME })
    : t("encounters.detail.metaDescription", { first, second, siteName: SITE_NAME });

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

/** The tabs, in order. The first one a match has content for is the default. */
const TABS = ["overview", "players", "pregame"] as const;
type EncounterTab = (typeof TABS)[number];

/**
 * Whether this encounter has pre-game data or captain reports — what decides
 * the Pre-game tab. Read on the server under the client panels' own keys, so
 * the panels hydrate from this instead of fetching again. A failed read hides
 * the tab rather than the page.
 */
async function prefetchPregame(queryClient: QueryClient, encounterId: number) {
  const applies = (state: PickBanState | null | undefined) =>
    state != null && (state.reason !== "not_configured" || state.session != null);
  const [map, hero, reports] = await Promise.all([
    queryClient
      .fetchQuery({
        queryKey: encounterQueryKeys.pregameState(encounterId, "map"),
        queryFn: () => pickBanService.getPickBanState("map", encounterId)
      })
      .catch(() => null),
    queryClient
      .fetchQuery({
        queryKey: encounterQueryKeys.pregameState(encounterId, "hero"),
        queryFn: () => pickBanService.getPickBanState("hero", encounterId)
      })
      .catch(() => null),
    queryClient
      .fetchQuery({
        queryKey: encounterQueryKeys.reports(encounterId),
        queryFn: () => captainService.getReports(encounterId)
      })
      .catch(() => null)
  ]);
  return applies(map) || applies(hero) || (reports?.reports.length ?? 0) > 0;
}

const EncounterPage = async (props: {
  params: Promise<{ id: number }>;
  searchParams: Promise<{ tab?: string | string[] }>;
}) => {
  const [params, searchParams] = await Promise.all([props.params, props.searchParams]);
  const queryClient = new QueryClient();
  // The pre-game prefetch needs only the id, so it runs alongside the
  // encounter read rather than after it; a lobby page discards it.
  const [encounter, t, format, hasPregame] = await Promise.all([
    encounterService.getEncounter(params.id),
    getTranslations(),
    getFormatter(),
    prefetchPregame(queryClient, Number(params.id))
  ]);

  // A lobby is not a duel with more teams: it has no per-map scoreboard, no
  // rosters to compare side by side and no captain reports. Its whole result
  // is the lobby table, so the FFA format gets its own page rather than a
  // duel page with most of its sections rendering nothing.
  if (isLobby(encounter)) {
    return <FfaLobbyPage encounter={encounter} />;
  }

  const [seatOne, seatTwo] = duelSeats(encounter.teams);
  const names = {
    one: seatOne?.name ?? t("common.tbd"),
    two: seatTwo?.name ?? t("common.tbd")
  };
  const tournamentGrid = encounter.tournament?.division_grid_version ?? null;
  const stageLabel =
    encounter.stage_item?.name ?? encounter.stage?.name ?? t("common.unassignedStage");

  const observations = encounter.matches ?? [];
  const hasUnboundHistory = observations.some((match) => match.map_index == null);
  const slots = buildSeriesSlots(encounter);
  // A position counts as played once it has a RESULT or a parsed log: a scrim
  // writes no `Match` rows at all, and a log can land before the captains
  // confirm.
  const playedSlots = slots.filter(
    (slot) => slot.match != null || acceptedScore(slot.game, encounter.teams) != null
  );
  // The map on air gets its row even before anything is recorded on it; every
  // other empty position is one line under the list, not a ghost row each.
  const listedSlots = slots.filter((slot) => playedSlots.includes(slot) || slot.isLive);
  const unplayedCount = slots.length - listedSlots.length;
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
    seriesSeconds != null && observations.length > 0
      ? formatSeriesClock(seriesSeconds / observations.length, clockUnits)
      : null;
  const closeness = formatCloseness(encounter.closeness);
  const logs = observations.map((match) => ({
    matchId: match.id,
    label: `${mapWithModeName(match.map, match.mode) ?? t("encounters.match.mapAlt")} · #${match.id}`,
    rawAvailable: match.raw_available
  }));
  const withStats = observations.length > 0;

  const visible: Record<EncounterTab, boolean> = {
    overview: listedSlots.length > 0 || hasUnboundHistory,
    players: withStats || seatOne?.team != null || seatTwo?.team != null,
    pregame: hasPregame
  };
  const tabs = TABS.filter((tab) => visible[tab]);
  const requested = Array.isArray(searchParams.tab) ? searchParams.tab[0] : searchParams.tab;
  const active: EncounterTab | undefined = tabs.find((tab) => tab === requested) ?? tabs[0];
  const tabHref = (tab: EncounterTab) =>
    tab === tabs[0] ? `/encounters/${encounter.id}` : `/encounters/${encounter.id}?tab=${tab}`;

  const dateFacts = (
    [
      ["scheduledAt", encounter.scheduled_at],
      ["startedAt", encounter.started_at],
      ["endedAt", encounter.ended_at],
      ["confirmedAt", encounter.confirmed_at]
    ] as const
  ).flatMap(([key, value]) =>
    value
      ? [
          {
            label: t(`encounters.detail.${key}`),
            value: format.dateTime(new Date(value), DATE_TIME)
          }
        ]
      : []
  );
  // A stat with nothing to say is left out rather than printed as a dash.
  const facts: EncounterHeaderFact[] = [
    ...(playedSlots.length > 0 || withStats
      ? [
          {
            label: t(hasUnboundHistory ? "encounters.detail.statObservations" : "encounters.detail.statMaps"),
            value: String(hasUnboundHistory ? observations.length : playedSlots.length),
            sub: t("encounters.detail.statMapsSub", {
              format: t("encounters.bestOfShort", { count: encounter.best_of }),
              one: mapWins.one,
              two: mapWins.two
            })
          }
        ]
      : []),
    ...(seriesClock
      ? [
          {
            label: t("encounters.detail.statDuration"),
            value: seriesClock,
            sub: averageClock
              ? t("encounters.detail.statDurationSub", { value: averageClock })
              : undefined
          }
        ]
      : []),
    ...(closeness ? [{ label: t("encounters.col.closeness"), value: closeness }] : []),
    ...dateFacts,
    ...(encounter.challonge_id != null
      ? [{ label: t("encounters.detail.challonge"), value: `#${encounter.challonge_id}` }]
      : [])
  ];
  // Stage, format, "final" and "confirmed" are already said by the crumbs, the
  // pips and the facts; a chip is left only for a state that wants attention.
  const openResult = encounter.result_status !== "none" && encounter.result_status !== "confirmed";

  return (
    <div className={SURFACE}>
      <EntityWorkspace workspaceId={encounter.tournament?.workspace_id} discipline={encounter.discipline} />
      <HydrationBoundary state={dehydrate(queryClient)}>
        <EncounterHeader
          encounter={encounter}
          crumbs={
            <>
              <BackLink href="/encounters">{t("encounters.detail.back")}</BackLink>
              <span className="inline-flex flex-wrap items-center gap-2">
                <Link href={`/tournaments/${encounter.tournament_id}`} className={CRUMB_LINK}>
                  {encounter.tournament?.name ?? t("common.tournament")}
                </Link>
                <span aria-hidden className={CRUMB_SEP}>
                  /
                </span>
                <span>{stageLabel}</span>
                <span aria-hidden className={CRUMB_SEP}>
                  /
                </span>
                <span>{t("encounters.roundNum", { round: encounter.round })}</span>
                <span aria-hidden className={CRUMB_SEP}>
                  /
                </span>
                <span>{t("encounters.bestOfShort", { count: encounter.best_of })}</span>
              </span>
            </>
          }
          actions={
            <>
              <PregameRoomLink
                encounterId={encounter.id}
                tournamentId={encounter.tournament_id}
                workspaceId={encounter.workspace_id}
                discipline={encounter.discipline}
                liveGames={(encounter.games ?? []).filter((game) => game.state !== "cancelled").length}
              />
              {logs.length > 0 ? (
                <MatchLogIndicator hasLogs logs={logs} className="size-8 rounded-lg" />
              ) : null}
            </>
          }
          pills={
            state === "Live" || openResult ? (
              <>
                {state === "Live" ? (
                  <Badge shape="pill" tone="danger">
                    <StatusDot pulse />
                    {t(`encounters.state.${STATE_KEY[state]}` as never)}
                  </Badge>
                ) : null}
                {openResult ? (
                  <Badge shape="pill" tone={encounter.result_status === "disputed" ? "danger" : "warning"}>
                    {t(`encounters.result.${RESULT_KEY[encounter.result_status]}` as never)}
                  </Badge>
                ) : null}
              </>
            ) : null
          }
          facts={facts}
        />

        {/* `LinkTabs` draws nothing for one tab: its content simply follows. */}
        <LinkTabs
          ariaLabel={t("encounters.detail.tabsLabel")}
          activeKey={active ?? ""}
          scroll={false}
          items={tabs.map((tab) => ({
            key: tab,
            label: t(`encounters.detail.tabs.${tab}`),
            href: tabHref(tab)
          }))}
        />

        {active === "overview" ? (
          <>
            <section aria-label={t("common.maps")}>
              <SectionHead
                title={t("common.maps")}
                meta={t("encounters.detail.mapsMeta", {
                  played: playedSlots.length,
                  slots: slots.length
                })}
              />
              <Card className="flex flex-col divide-y divide-[color:var(--aqt-overlay-border)] overflow-hidden">
                {listedSlots.map((slot) => (
                  <EncounterMapRow
                    key={slot.index}
                    slot={slot}
                    names={names}
                    teams={encounter.teams}
                    clockUnits={clockUnits}
                  />
                ))}
                {unplayedCount > 0 ? (
                  <p className="px-4.5 py-3 font-[family-name:var(--aqt-data)] text-label text-[color:var(--aqt-fg-faint)]">
                    {t(hasUnboundHistory ? "encounters.history.slotsWithoutBinding" : "encounters.detail.mapsUnplayed", { count: unplayedCount })}
                  </p>
                ) : null}
              </Card>
            </section>

            <EncounterWatch encounterId={encounter.id} />

            <EncounterHistory matches={observations} />

            {playedSlots.length > 0 || withStats ? (
              <section aria-label={t("encounters.detail.seriesStats")}>
                <SectionHead title={t("encounters.detail.seriesStats")} />
                {withStats ? (
                  <EncounterSeriesStats
                    view="overview"
                    matchIds={observations.map((match) => match.id)}
                  />
                ) : (
                  <Card>
                    <p className="p-4.5 text-label leading-normal text-[color:var(--aqt-fg-dim)]">
                      {t("encounters.detail.seriesStatsNoLogs")}
                    </p>
                  </Card>
                )}
              </section>
            ) : null}
          </>
        ) : null}

        {active === "players" ? (
          withStats ? (
            <section aria-label={t("encounters.detail.tabs.players")}>
              <EncounterSeriesStats
                view="players"
                matchIds={observations.map((match) => match.id)}
              />
            </section>
          ) : (
            <section aria-label={t("encounters.detail.rosters")}>
              <div className="grid grid-cols-1 items-start gap-3.5 lg:grid-cols-2">
                <EncounterRosterPanel
                  team={seatOne?.team ?? null}
                  slot={1}
                  workspaceId={encounter.workspace_id}
                  discipline={encounter.tournament.discipline}
                  tournamentGrid={tournamentGrid}
                />
                <EncounterRosterPanel
                  team={seatTwo?.team ?? null}
                  slot={2}
                  workspaceId={encounter.workspace_id}
                  discipline={encounter.tournament.discipline}
                  tournamentGrid={tournamentGrid}
                />
              </div>
            </section>
          )
        ) : null}

        {active === "pregame" ? (
          <>
            <EncounterPregamePanel encounterId={encounter.id} teams={encounter.teams} />
            <EncounterCaptainReports encounterId={encounter.id} teams={encounter.teams} />
          </>
        ) : null}
      </HydrationBoundary>
    </div>
  );
};

/**
 * The public page of one FFA lobby.
 *
 * Reads `GET /api/v1/encounters/{id}/ffa`, which answers the same `FfaLobby`
 * the stage read answers, so this page and the bracket panel render the very
 * same table. Nothing duel-shaped is offered: no veto, no readiness, no
 * captain reports — an organizer enters the games, and the room next door is
 * only the chat.
 */
const FfaLobbyPage = async ({ encounter }: Readonly<{ encounter: Encounter }>) => {
  const lobby = await ffaService.getLobby(encounter.id);
  const t = await getTranslations();
  const format = await getFormatter();

  const stageLabel =
    encounter.stage_item?.name ?? encounter.stage?.name ?? t("common.unassignedStage");
  const state = getEncounterState(encounter);

  return (
    <div className={SURFACE}>
      <EntityWorkspace workspaceId={encounter.tournament?.workspace_id} discipline={encounter.discipline} />
      <PageHero
        align="start"
        titleClassName="text-[clamp(1.35rem,2.4vw,2rem)]"
        eyebrow={
          <>
            <BackLink href="/encounters">{t("encounters.detail.back")}</BackLink>
            <HeroCoord className="inline-flex flex-wrap items-center gap-2">
              <Link href={`/tournaments/${encounter.tournament_id}`} className={CRUMB_LINK}>
                {encounter.tournament?.name ?? t("common.tournament")}
              </Link>
              <span aria-hidden className={CRUMB_SEP}>
                /
              </span>
              <span>{stageLabel}</span>
            </HeroCoord>
          </>
        }
        title={lobby.name}
        meta={
          <>
            <Badge
              shape="pill"
              tone={
                state === "Live"
                  ? "danger"
                  : state === "Final"
                    ? "success"
                    : state === "Upcoming"
                      ? "warning"
                      : "neutral"
              }
            >
              {state === "Live" ? <StatusDot pulse /> : null}
              {/* "Final" is a duel's word and reads as the bracket's final here. */}
              {state === "Final"
                ? t("ffa.lobbyCompleted")
                : t(`encounters.state.${STATE_KEY[state]}` as never)}
            </Badge>
            <Badge shape="pill" tone="neutral">
              <Eyebrow>{t("ffa.gamesPerLobby")}</Eyebrow>
              <span className="aqt-tnum">{lobby.best_of}</span>
            </Badge>
            {encounter.result_status !== "none" ? (
              <Badge shape="pill" tone={encounter.result_status === "confirmed" ? "success" : "warning"}>
                {t(`encounters.result.${RESULT_KEY[encounter.result_status]}` as never)}
              </Badge>
            ) : null}
          </>
        }
        lede={t("ffa.lobbyLede", {
          teams: t("ffa.participants", { count: lobby.rows.length }),
          games: lobby.best_of
        })}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link href={`/tournaments/${encounter.tournament_id}/pregame/${encounter.id}`}>
                <MessageSquare aria-hidden />
                {t("ffa.openRoom")}
              </Link>
            </Button>
          </div>
        }
        stamp={
          encounter.scheduled_at ? (
            <HeroStamp
              label={t("encounters.detail.scheduledAt")}
              value={format.dateTime(new Date(encounter.scheduled_at), DATE_TIME)}
            />
          ) : null
        }
      />

      <section aria-label={t("ffa.tableLabel", { lobby: lobby.name })}>
        <SectionHead
          title={t("common.standings")}
          meta={t("ffa.participants", { count: lobby.rows.length })}
        />
        <Card className="overflow-hidden">
          {lobby.rows.length === 0 ? (
            <p className="p-4.5">{t("ffa.lobbyEmpty")}</p>
          ) : (
            <FfaLobbyTable lobby={lobby} />
          )}
        </Card>
      </section>
      <EncounterHistory matches={encounter.matches ?? []} />
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
