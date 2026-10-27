"use client";

import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, ChevronDown, FileUp, ShieldAlert, ShieldCheck, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";

import { EmptyNote } from "@/components/kit/EmptyNote";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { triggerChevronClass } from "@/components/ui/chevron";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { EncounterRostersModal } from "@/components/EncounterRostersModal";
import { MatchImport } from "@/components/pick-ban/MatchImport";
import { TournamentLogUploadDialog } from "@/components/logs/TournamentLogUploadDialog";
import { usePermissions } from "@/hooks/usePermissions";
import { RETURN_TO_PARAM, safeReturnPath } from "@/lib/auth/return-to";
import encounterService from "@/services/encounter.service";
import type { PickBanKind } from "@/types/tournament.types";

import { RoomChat } from "@/components/chat/RoomChat";
import { encounterChatRoom } from "@/lib/realtime/chat-rooms";
import {
  PICK_BAN_UNAVAILABLE_COPY,
  gameAtPosition,
  pickBanSeats
} from "@/components/pick-ban/pick-ban-model";
import { isLobby } from "@/lib/encounter/seats";
import { buildSeriesSlots } from "@/lib/encounter/detail";
import { modeBeyondMap } from "@/lib/catalog/mode";
import { PickBanUndoControl } from "@/components/pick-ban/PickBanUndoControl";
import { PickBanSideAssignment } from "@/components/pick-ban/PickBanSideChoice";
import { useSideLabel } from "@/components/pick-ban/useSideLabel";
import { FfaPregameRoom } from "./FfaPregameRoom";
import { PregameAdminPanel } from "./PregameAdminPanel";
import { PregameHeader } from "./PregameHeader";
import { PregameFinalReport } from "./PregameFinalReport";
import { PregameMapResult } from "./PregameMapResult";
import { PregameReadiness } from "./PregameReadiness";
import { EmptyRoomCard, UNAVAILABLE_ICON } from "./EmptyRoomCard";
import { PickBanPanel } from "@/components/pick-ban/PickBanPanel";
import type { PickBanAdminSlot } from "@/components/pick-ban/usePickBanController";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { usePregameRoomData } from "./usePregameRoomData";
import {
  buildHeroRounds,
  buildSeriesMaps,
  derivePregameLoop,
  heroBoardForRound
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

  // Until the seat count is known, neither room is the right one to show: rendering
  // the duel room first would flash a readiness gate at a lobby.
  if (encounterQuery.isPending) {
    return <RoomSkeleton />;
  }

  if (encounterQuery.data != null && isLobby(encounterQuery.data)) {
    return <FfaPregameRoom encounter={encounterQuery.data} />;
  }

  return (
    <>
      <PregameRoomBody key={encounterId} {...props} />
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
  const logT = useTranslations("accountSettings.logDirectory");
  const { isSuperuser, isWorkspaceAdmin, hasWorkspacePermission } = usePermissions();
  const searchParams = useSearchParams();
  const returnTo = safeReturnPath(searchParams?.get(RETURN_TO_PARAM), `/encounters/${encounterId}`);
  const room = usePregameRoomData(encounterId);
  const [adminOpen, setAdminOpen] = useState(false);
  const sideLabelOf = useSideLabel();

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

  // The owner's workspace: an encounter carries it whoever owns it (spec §8.2).
  const workspaceId = encounter.workspace_id;
  const isAdmin =
    isSuperuser || isWorkspaceAdmin(workspaceId) || hasWorkspacePermission(workspaceId, "match.result");
  const viewerTeamId = mapState.viewer_team_id ?? room.viewerTeamId;
  // A tournament game of a discipline that declares a match fetcher can be filed by its match id (a scrim room
  // publishes no result). Filing needs no pick-ban session: the positions are the encounter's own live games.
  const matchImport =
    seriesReport && room.metadata.status === "ready" && room.metadata.metadata.discipline.capabilities.match_fetch;
  const matchImportGames = matchImport
    ? (encounter.games ?? []).filter((game) => game.state !== "cancelled")
    : [];
  // The organizer import routes are gated on `match.result` (any other management grant is not enough); everyone
  // else files as a captain of the encounter.
  const importsAsOrganizer = hasWorkspacePermission(workspaceId, "match.result");

  if (loop.unconfigured) {
    // Without a pick-ban the room only exists to file the series' matches by id; until the game's metadata says
    // whether it can, neither screen is the right one.
    if (seriesReport && room.metadata.status === "pending") return <RoomSkeleton />;
    if (matchImportGames.length > 0 && (importsAsOrganizer || viewerTeamId != null)) {
      return (
        <Card>
          <CardContent className="flex flex-col gap-4 p-6">
            <div className="flex flex-col gap-1">
              <Eyebrow>{t("matchImport.title")}</Eyebrow>
              <h1 className="font-display text-title font-semibold">{encounter.name}</h1>
            </div>
            {/* An organizer files through the organizer route, whose rows carry the warnings. */}
            <MatchImport encounterId={encounterId} games={matchImportGames} admin={importsAsOrganizer} />
            <div>
              <Button variant="outline" asChild>
                <Link href={returnTo}>
                  <ArrowLeft aria-hidden />
                  {t("back")}
                </Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      );
    }
    return (
      <EmptyRoomCard
        icon={UNAVAILABLE_ICON.unconfigured}
        title={t("notConfiguredTitle")}
        hint={t("notConfiguredHint")}
        returnTo={returnTo}
      />
    );
  }

  const series = buildSeriesMaps(loop, room.mapsById, (id) => t("map.itemNumber", { id }));
  const heroName = (id: number) => t("hero.itemNumber", { id });
  const seats = pickBanSeats(encounter.teams);
  const seatNameAt = (index: number) => seats[index]?.name ?? t("tbd");
  const seriesSummary = mapState.series ?? null;
  // Sides are the game's, not a kind's: a hero-only room has no map session, whose state then lists none.
  const roomSides = heroState.sides.length > 0 ? heroState.sides : mapState.sides;
  const sideLabel = (code: string) => sideLabelOf(encounter.discipline, code);
  const sideLabels = roomSides.map(sideLabel);
  // The readiness gate already shows both rosters inline; every later screen
  // has its pool or report there, so the rosters sit one click away instead.
  const showRostersButton = !loop.waitingOnReadiness;
  const canUploadLog = encounter.tournament_id != null && hasWorkspacePermission(workspaceId, "log.create");
  const header = (
    <>
      <PregameHeader
        encounter={encounter}
        state={loop.statesByKind[loop.phase === "hero" || !loop.mapApplies ? "hero" : "map"]}
        activePhase={loop.phase}
        phases={loop.phases}
        round={loop.round}
        series={series}
        seriesScore={
          seriesSummary != null
            ? {
                one: seriesSummary.wins[String(seats[0]?.id)] ?? 0,
                two: seriesSummary.wins[String(seats[1]?.id)] ?? 0
              }
            : null
        }
        returnTo={returnTo}
      />
      {showRostersButton || canUploadLog ? (
        <div className="flex flex-wrap gap-2">
          {showRostersButton ? (
            <EncounterRostersModal
              encounterId={encounterId}
              teamNames={[seatNameAt(0), seatNameAt(1)]}
              trigger={
                <Button type="button" variant="outline" size="sm">
                  <Users className="h-4 w-4" aria-hidden />
                  {t("rosters")}
                </Button>
              }
            />
          ) : null}
          {canUploadLog ? (
            <TournamentLogUploadDialog
              tournamentId={encounter.tournament_id}
              encounters={[encounter]}
              initialEncounterId={encounterId}
              autoUpload
              onUploaded={room.invalidateRoom}
              trigger={
                <Button type="button" variant="outline" size="sm">
                  <FileUp className="h-4 w-4" aria-hidden />
                  {logT("uploadAction")}
                </Button>
              }
            />
          ) : null}
        </div>
      ) : null}
      {/* A cancelled kind leaves no phase behind, so without this line the
          room simply looks like one that never had a veto — and the captains
          naming their own map have no idea why. */}
      {loop.cancelledKinds.map((kind) => (
        <EmptyNote key={kind} size="sm" tone="warning">
          {t("cancelledNotice", { phase: t(`phase.${kind}`) })}
        </EmptyNote>
      ))}
    </>
  );

  // One organizer surface per screen, on every phase — the readiness gate, the
  // board, the map report and the closing screen all need overrides, and the
  // panel picks what to offer from the sessions that exist. `grid` is only
  // non-null where a pool is actually on screen to select from.
  const activeKind: PickBanKind = loop.phase === "hero" ? "hero" : "map";
  const adminPanel = (grid: PickBanAdminSlot | null = null) =>
    isAdmin ? (
      <Collapsible open={adminOpen} onOpenChange={setAdminOpen}>
        <CollapsibleTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="group/trigger h-auto min-h-11 max-w-full whitespace-normal text-left"
          >
            <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden />
            {t(adminOpen ? "admin.hideUi" : "admin.showUi")}
            <ChevronDown className={triggerChevronClass} aria-hidden />
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-3">
          <PregameAdminPanel
            encounterId={encounterId}
            statesByKind={loop.statesByKind}
            activeKind={activeKind}
            seats={seats}
            itemsByKind={room.itemsByKind}
            sideLabels={sideLabels}
            bestOf={encounter.best_of ?? 0}
            seriesWins={seriesSummary?.wins ?? null}
            onMutated={room.invalidateRoom}
            grid={grid}
            // The panel opens for any management grant; its import section files through the organizer route.
            matchImportGames={importsAsOrganizer ? matchImportGames : []}
          />
        </CollapsibleContent>
      </Collapsible>
    ) : null;

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
            viewerTeamId={room.viewerTeamId}
            pending={room.readyPending}
            onReady={room.markReady}
          />
          {adminPanel()}
        </CardContent>
      </Card>
    );
  }

  if (loop.phase === "report" && loop.reportRound != null) {
    const reportGame = gameAtPosition(loop.games, loop.reportRound);
    const reportMapId = loop.pendingMap?.item_id ?? reportGame?.map_id ?? null;
    const reportSides = heroState.starting_sides ?? mapState.starting_sides;
    const reportMapItem = reportMapId != null ? room.mapsById[reportMapId] : undefined;
    const reportMapName =
      reportMapItem?.name ??
      (reportMapId != null ? t("map.itemNumber", { id: reportMapId }) : t("mapResult.pickMap"));
    // Once a log names the game's mode, a map several modes share (Midtown) says which one was played.
    const reportEncounterGame = encounter.games?.find((game) => game.position === loop.reportRound);
    const reportMode = modeBeyondMap(reportEncounterGame?.map, reportEncounterGame?.mode);
    return (
      <div className="flex flex-col gap-4">
        <PregameMapResult
          encounterId={encounterId}
          mapName={reportMode == null ? reportMapName : `${reportMapName} · ${reportMode.name}`}
          mapImagePath={reportMapItem?.image_path ?? null}
          round={loop.reportRound}
          viewerTeamId={viewerTeamId}
          teams={loop.teams}
          game={reportGame}
          metadata={room.metadata}
          heroBoard={heroBoardForRound(
            heroState,
            loop.reportRound,
            room.heroesById,
            heroName,
            room.characterClasses
          )}
          sides={
            reportSides?.some((entry) => entry.position === loop.reportRound) ? (
              <PickBanSideAssignment
                startingSides={reportSides}
                position={loop.reportRound}
                seats={seats}
                sideLabel={sideLabel}
              />
            ) : null
          }
          heroUndo={
            <PickBanUndoControl
              kind="hero"
              encounterId={encounterId}
              undo={heroState.undo}
              viewerTeamId={heroState.viewer_team_id}
              itemsById={room.heroesById}
              sideLabels={sideLabels}
              seats={seats}
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
          matchImport={matchImport}
        />
        {/* A dispute parks the room on this screen until an organizer rules on
            it, and ruling means correcting the game's result — which is in
            this panel, with no pool on screen to select from. */}
        {adminPanel()}
      </div>
    );
  }

  if (loop.phase === "done") {
    return (
      <div className="flex flex-col gap-4">
        <PregameFinalReport
          encounter={encounter}
          viewerTeamId={viewerTeamId}
          reportable={seriesReport}
          heroRounds={buildHeroRounds(heroState, series, room.heroesById, heroName, room.characterClasses)}
          metadata={room.metadata}
          header={header}
          returnTo={returnTo}
        />
        {adminPanel()}
      </div>
    );
  }

  const activeState = loop.statesByKind[activeKind];

  if (activeState.session == null) {
    const copy = PICK_BAN_UNAVAILABLE_COPY[activeState.reason ?? "not_configured"];
    return (
      <div className="flex flex-col gap-4">
        <EmptyRoomCard
          icon={UNAVAILABLE_ICON[copy.icon]}
          title={t(copy.titleKey)}
          hint={t(copy.hintKey)}
          returnTo={returnTo}
        />
        {adminPanel()}
      </div>
    );
  }

  // A per-player ban looks back at the previous map's parsed match; only the tournament room has one to read.
  const previousRound = (activeState.current_round ?? activeState.current_step?.round ?? 1) - 1;
  const previousMatchId = encounter.games?.length
    ? (buildSeriesSlots(encounter).find((slot) => slot.index === previousRound)?.match?.id ?? null)
    : ((encounter.matches ?? []).find((match) => match.map_index === previousRound)?.id ?? null);

  return (
    <div className="flex flex-col gap-4">
      <PickBanPanel
        key={activeKind}
        kind={activeKind}
        encounterId={encounterId}
        encounter={encounter}
        state={activeState}
        session={activeState.session}
        queryKey={activeKind === "map" ? room.mapKey : room.heroKey}
        itemsById={room.itemsByKind[activeKind]}
        isAdmin={isAdmin && adminOpen}
        adminPanel={adminPanel}
        header={header}
        previousMatchId={previousMatchId}
      />
    </div>
  );
}
