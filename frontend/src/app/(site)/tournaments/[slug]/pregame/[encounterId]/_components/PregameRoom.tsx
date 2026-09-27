"use client";

import { useSearchParams } from "next/navigation";
import { ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { RETURN_TO_PARAM, safeReturnPath } from "@/lib/auth/return-to";
import encounterService from "@/services/encounter.service";
import type { PickBanKind } from "@/types/tournament.types";

import { RoomChat } from "@/components/chat/RoomChat";
import { encounterChatRoom } from "@/lib/realtime/chat-rooms";
import {
  PICK_BAN_UNAVAILABLE_COPY,
  gameAtPosition,
  type PickBanSide
} from "@/components/pick-ban/pick-ban-model";
import { PickBanUndoControl } from "@/components/pick-ban/PickBanUndoControl";
import { FfaPregameRoom } from "./FfaPregameRoom";
import { PregameAdminControls } from "./PregameAdminControls";
import { PregameHeader } from "./PregameHeader";
import { PregameFinalReport } from "./PregameFinalReport";
import { PregameMapResult } from "./PregameMapResult";
import { PregameReadiness } from "./PregameReadiness";
import { EmptyRoomCard, UNAVAILABLE_ICON } from "./EmptyRoomCard";
import { PickBanPanel } from "./PickBanPanel";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { usePregameRoomData } from "./usePregameRoomData";
import {
  buildHeroRounds,
  buildSeriesMaps,
  derivePregameLoop,
  heroActionsForRound
} from "./pregameRoom.model";

interface PregameRoomProps {
  encounterId: number;
  /**
   * Whether the loop ends in the SERIES report (match codes, closeness, the
   * organizer's custom fields). False for a scrim room: it has no result to
   * publish and no organizer to read one, and the report form is built from a
   * per-tournament config a scrim container does not have. The per-map score is
   * unaffected — that one drives the progression, not the bookkeeping
   * (docs/plans/2026-08-12-scrim-rooms.md).
   */
  seriesReport?: boolean;
}

/**
 * The room plus its private back channel. The chat is a `Dock` over the page
 * rather than a panel inside one of the phases: every branch below returns a
 * different screen (readiness, a pick-ban board, a map report, the closing
 * report), and the captains need to talk across all of them — "ready?" is
 * asked precisely when the readiness gate is up. Docked, it also costs the
 * room no width, and `RoomChat` renders nothing at all for a viewer the room
 * will not let read.
 *
 * An FFA lobby takes a different room entirely (`FfaPregameRoom`): it has no
 * two sides to veto, ban or declare ready, so the whole phase machine below is
 * meaningless there. The encounter read that decides this shares its key with
 * the body's own, so the branch costs no extra request.
 */
export function PregameRoom(props: Readonly<PregameRoomProps>) {
  const { encounterId } = props;
  const encounterQuery = useQuery({
    queryKey: encounterQueryKeys.detail(encounterId),
    queryFn: () => encounterService.getEncounter(encounterId),
    enabled: Number.isFinite(encounterId) && encounterId > 0
  });

  // Until the format is known, neither room is the right one to show: rendering
  // the duel room first would flash a readiness gate at a lobby.
  if (encounterQuery.isPending) {
    return <RoomSkeleton />;
  }

  if (encounterQuery.data?.format === "ffa") {
    return <FfaPregameRoom encounter={encounterQuery.data} />;
  }

  return (
    <>
      <PregameRoomBody {...props} />
      <RoomChat room={encounterChatRoom(encounterId)} />
    </>
  );
}

function RoomSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(260px,1fr)_2fr]">
      <Skeleton className="h-72 w-full rounded-xl" />
      <Skeleton className="h-96 w-full rounded-xl" />
    </div>
  );
}

/**
 * Unified pre-game room: one screen for the whole pre-game loop, which runs
 * once per map of the series —
 *
 *   map veto (this round's map) -> hero bans (for that map) -> the map is
 *   played and both captains report it -> that result opens the next map
 *
 * — until the series is decided. Both pick-ban kinds run on the same generic
 * `PickBanSession` engine, so one room renders either with the same
 * `PickBanGrid`/`PickBanStepTimeline`, and the backend keeps the loop honest:
 * a map round is only appended once the previous map's result is confirmed
 * (`pick_ban_session.advance_to_next_round`), and a hero round only once its
 * map is picked (`pick_ban_session.sync_hero_rounds`).
 *
 * Gated by `EncounterReadiness`: neither kind's session is created (backend:
 * `pick_ban_session.ensure_pick_ban_session`) until both captains confirm
 * readiness, shown here as a waiting screen with an "I'm ready" button.
 *
 * Where the loop stands is derived in `pregameRoom.model`; this component is
 * the branch from that reading to the one screen it names.
 */
function PregameRoomBody({ encounterId, seriesReport = true }: Readonly<PregameRoomProps>) {
  const t = useTranslations("pickBan.room");
  const { isSuperuser, isWorkspaceAdmin, hasWorkspacePermission } = usePermissions();
  const searchParams = useSearchParams();
  const returnTo = safeReturnPath(searchParams?.get(RETURN_TO_PARAM), `/encounters/${encounterId}`);
  const room = usePregameRoomData(encounterId);

  if (room.isPending) {
    return <RoomSkeleton />;
  }

  const { encounter, mapState, heroState } = room;
  if (room.isError || encounter === null || mapState === null || heroState === null) {
    return (
      <EmptyRoomCard
        icon={<ShieldAlert className="h-6 w-6 text-[color:var(--aqt-amber)]" aria-hidden />}
        title={t("loadError")}
        action={<Button onClick={room.refetchAll}>{t("retry")}</Button>}
        returnTo={returnTo}
      />
    );
  }

  const loop = derivePregameLoop(encounter, mapState, heroState);

  if (loop.unconfigured) {
    return (
      <EmptyRoomCard
        icon={UNAVAILABLE_ICON.unconfigured}
        title={t("notConfiguredTitle")}
        hint={t("notConfiguredHint")}
        returnTo={returnTo}
      />
    );
  }

  const workspaceId = encounter.tournament?.workspace_id ?? null;
  const isAdmin =
    workspaceId != null &&
    (isSuperuser ||
      isWorkspaceAdmin(workspaceId) ||
      hasWorkspacePermission(workspaceId, "match.update"));

  const series = buildSeriesMaps(loop, room.mapsById, (id) => t("map.itemNumber", { id }));
  const heroName = (id: number) => t("hero.itemNumber", { id });
  const sideNameOf = (side: PickBanSide) =>
    side === "home"
      ? (encounter.home_team?.name ?? t("side.home"))
      : (encounter.away_team?.name ?? t("side.away"));
  const seriesSummary = mapState.series ?? null;
  const header = (
    <PregameHeader
      encounter={encounter}
      session={
        loop.statesByKind[loop.phase === "hero" || !loop.mapApplies ? "hero" : "map"].session
      }
      activePhase={loop.phase}
      phases={loop.phases}
      round={loop.round}
      series={series}
      seriesScore={
        seriesSummary != null
          ? { home: seriesSummary.home_wins, away: seriesSummary.away_wins }
          : null
      }
      official={seriesSummary?.official ?? null}
      returnTo={returnTo}
    />
  );

  if (loop.waitingOnReadiness) {
    // One real card, header and all — no skeleton column beside it. Neither
    // session exists yet, so there is no pool and no step sequence to render,
    // and a shimmer that can only resolve when a human clicks "I'm ready" in
    // another browser reads as a page stuck loading.
    return (
      <Card>
        <CardContent className="flex flex-col gap-5 p-5">
          {header}
          <PregameReadiness
            encounter={encounter}
            readiness={mapState.readiness}
            viewerSide={room.viewerSide}
            pending={room.readyPending}
            onReady={room.markReady}
          />
        </CardContent>
      </Card>
    );
  }

  if (loop.phase === "report" && loop.reportRound != null) {
    const reportGame = gameAtPosition(loop.games, loop.reportRound);
    const reportMapId = loop.pendingMap?.item_id ?? reportGame?.map_id ?? null;
    const reportMapItem = reportMapId != null ? room.mapsById[reportMapId] : undefined;
    return (
      <div className="flex flex-col gap-4">
        <PregameMapResult
          encounterId={encounterId}
          mapName={
            reportMapItem?.name ??
            (reportMapId != null ? t("map.itemNumber", { id: reportMapId }) : t("mapResult.pickMap"))
          }
          mapImagePath={reportMapItem?.image_path ?? null}
          round={loop.reportRound}
          viewerSide={mapState.viewer_side ?? room.viewerSide}
          homeName={sideNameOf("home")}
          awayName={sideNameOf("away")}
          homeTeam={encounter.home_team ?? null}
          awayTeam={encounter.away_team ?? null}
          game={reportGame}
          heroActions={heroActionsForRound(
            heroState.pool,
            loop.reportRound,
            room.heroesById,
            heroName
          )}
          heroUndo={
            <PickBanUndoControl
              kind="hero"
              encounterId={encounterId}
              undo={heroState.undo}
              viewerSide={heroState.viewer_side}
              itemsById={room.heroesById}
              sideName={sideNameOf}
              invalidateKeys={[room.mapKey, room.heroKey]}
            />
          }
          header={header}
          invalidateKeys={[room.mapKey, room.heroKey, ["encounter-detail", encounterId]]}
          mapChoices={
            loop.pendingMap == null
              ? room.mapChoices.map((map) => ({ id: map.id, name: map.name }))
              : undefined
          }
        />
        {/* A dispute parks the room on this screen until an organizer rules on
            it, and the pick-ban board — where these controls otherwise live —
            is not on screen here. */}
        {isAdmin ? (
          <PregameAdminControls
            kind="map"
            encounterId={encounterId}
            state={mapState}
            allowProtect={false}
            selectedItemId={null}
            selectedItemName={null}
            onMutated={room.invalidateRoom}
          />
        ) : null}
      </div>
    );
  }

  if (loop.phase === "done") {
    return (
      <div className="flex flex-col gap-4">
        <PregameFinalReport
          encounter={encounter}
          viewerSide={mapState.viewer_side ?? room.viewerSide}
          reportable={seriesReport}
          heroRounds={buildHeroRounds(heroState.pool, series, room.heroesById, heroName)}
          homeName={sideNameOf("home")}
          awayName={sideNameOf("away")}
          header={header}
          returnTo={returnTo}
        />
      </div>
    );
  }

  const activeKind: PickBanKind = loop.phase === "hero" ? "hero" : "map";
  const activeState = loop.statesByKind[activeKind];

  if (activeState.session == null) {
    const copy = PICK_BAN_UNAVAILABLE_COPY[activeState.reason ?? "not_configured"];
    return (
      <EmptyRoomCard
        icon={UNAVAILABLE_ICON[copy.icon]}
        title={t(copy.titleKey)}
        hint={t(copy.hintKey)}
        returnTo={returnTo}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4 pb-32 sm:pb-28">
      <PickBanPanel
        key={activeKind}
        kind={activeKind}
        encounterId={encounterId}
        encounter={encounter}
        state={activeState}
        session={activeState.session}
        queryKey={activeKind === "map" ? room.mapKey : room.heroKey}
        itemsById={room.itemsByKind[activeKind]}
        isAdmin={isAdmin}
        header={header}
      />
    </div>
  );
}
