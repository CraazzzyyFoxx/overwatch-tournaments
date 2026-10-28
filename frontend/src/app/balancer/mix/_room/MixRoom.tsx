"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown } from "lucide-react";

import { LobbyStage } from "@/app/balancer/mix/_components/LobbyStage";
import { LobbyCodeStrip } from "@/app/balancer/mix/_components/LobbyCodeStrip";
import { useMixBanRoom } from "@/app/balancer/mix/_hooks/useMixBanRoom";
import { lobbyCandidateCount, buildMixOwner, canWriteMix, parseVariants, teamNamesByIndex } from "@/app/balancer/mix/pickup-lineup";
import { lobbyLetter } from "@/app/balancer/mix/pickup-chrome";
import { usePickupMix } from "@/app/balancer/mix/usePickupMix";
import { RoomChat } from "@/components/chat/RoomChat";
import { memberChoice } from "@/components/pick-ban/pick-ban-model";
import { useSideLabel } from "@/components/pick-ban/useSideLabel";
import { BackLink } from "@/components/site/BackLink";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { triggerChevronClass } from "@/components/ui/chevron";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useCatalogEntities } from "@/hooks/useCatalogEntities";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useDraftBoardQuery, useDraftMutations, useDraftPickOptionsQuery, useDraftRealtime } from "@/hooks/useDraftData";
import { useEntityWorkspace } from "@/hooks/useEntityWorkspace";
import { usePermissions } from "@/hooks/usePermissions";
import { computeGating } from "@/lib/draft/logic";
import { draftChatRoom, encounterChatRoom } from "@/lib/realtime/chat-rooms";
import { slotCodeOrder } from "@/lib/roster/ontology";
import { OPEN_SLOT_CODE, slotCodesOf } from "@/lib/roster/shape";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { cn } from "@/lib/utils";
import type { CustomGame } from "@/services/custom-game.service";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import type { DraftBoard, DraftTeam } from "@/types/draft.types";

import { RoomBanStage } from "./RoomBanStage";
import { RoomDraftStage } from "./RoomDraftStage";
import { RoomHostMenu } from "./RoomHostMenu";
import { RoomMatchStage } from "./RoomMatchStage";
import { RoomTeamColumn } from "./RoomTeamColumn";
import { draftPlayerName, draftRoomTeams, lineupRoomTeams, roomPhase, withHeroRoom, type RoomTeam } from "./room-model";
import { useRoomLinkClick } from "./room-navigation";
import { useViewTransitionState } from "./useViewTransitionState";
import "./room-transitions.css";

const NONE = "none";

/**
 * One lobby's match room (spec §7.5, as the room was redrawn after П4): team A on the left, team B on the right and,
 * between them, whatever the lobby is doing -- waiting for teams, the captains' draft out of the pool, the formed
 * teams waiting for Start match, the hero bans and picks, the live match. Everything the server says moves through one
 * view transition, so a pick flies into its slot and the centre hands over from phase to phase. Everyone reads the
 * same room; a host's controls are inline (the phase's primary action) and in the header's menu. The chat docks while
 * a draft or a match is on.
 */
export function MixRoom({ initialGame, lobbyIndex }: Readonly<{ initialGame: CustomGame; lobbyIndex: number }>) {
  const t = useTranslations("mixes.arena");
  const tRoom = useTranslations("mixes.room");
  const tLobbies = useTranslations("mixes.lobbies");
  const tVoice = useTranslations("mixes.voice");
  const tDraft = useTranslations("mixes.draft");
  const tMixes = useTranslations("mixes");
  const workspaceId = initialGame.workspace_id;
  useEntityWorkspace(workspaceId, initialGame.discipline);
  const currentUserId = useAuthProfileStore((state) => state.user?.id ?? null);
  const isSignedIn = useAuthProfileStore((state) => state.status === "authenticated");
  const { user } = useAuthProfile();
  const { isSuperuser } = usePermissions();
  const sideLabelOf = useSideLabel();
  const mixHref = `/balancer/mix/${initialGame.id}`;
  const leaveRoom = useRoomLinkClick("leave", lobbyIndex, mixHref);

  const mix = usePickupMix(workspaceId, initialGame.id, {
    seatEnabled: isSignedIn,
    voiceEnabled: false,
    initialGame,
    initialLobby: lobbyIndex
  });
  const game = mix.gameQuery.data ?? initialGame;
  const canWrite = canWriteMix(game, currentUserId, isSuperuser);
  const discipline = game.discipline;
  const metadataQuery = useDisciplineMetadata(workspaceId, discipline);
  const workspaceGrid = useDivisionGrid(discipline);
  const owner = useMemo(
    () => buildMixOwner(metadataQuery.data, game.roster_shape, workspaceGrid),
    [metadataQuery.data, game.roster_shape, workspaceGrid]
  );
  const mapsQuery = useCatalogEntities(discipline, "map");
  const lobby = game.lobbies.find((row) => row.lobby_index === lobbyIndex);
  const phase = roomPhase(lobby?.state ?? "idle");
  const mySeat = mix.mySeatQuery.data?.seat ?? null;
  const myMemberId = mySeat?.workspace_member_id ?? null;

  // The draft board, while the lobby drafts: its own query, realtime and writes (the mix cache does not carry it).
  const draftSessionId = phase === "draft" ? (lobby?.draft_session_id ?? null) : null;
  const boardKey = tournamentQueryKeys.draftSessionBoard(draftSessionId ?? 0);
  const boardQuery = useDraftBoardQuery(draftSessionId);
  const liveBoard = draftSessionId == null ? null : (boardQuery.data ?? null);
  const { presence, connectionState } = useDraftRealtime(boardKey, liveBoard);
  const draftMutations = useDraftMutations(boardKey);
  const myPlayerIds = useMemo(() => (user?.linkedPlayers ?? []).map((player) => player.playerId), [user]);
  const gating = useMemo(
    () => (liveBoard != null ? computeGating(liveBoard, myPlayerIds, user?.id ?? null, false) : null),
    [liveBoard, myPlayerIds, user?.id]
  );
  const optionsQuery = useDraftPickOptionsQuery(liveBoard?.current_pick?.id ?? null, gating?.isMyPick === true);

  // The hero room, from the match's start while it has one: its bans and picks stay up through Live.
  const heroEncounterId =
    lobby?.live_encounter_id != null && (phase === "pregame" || (phase === "live" && lobby.live_ban_preset != null))
      ? lobby.live_encounter_id
      : null;
  const heroRoom = useMixBanRoom(heroEncounterId, discipline);

  // The lobby's own stage moves on the server: the last pick makes it Ready (a finished hero room makes it Live, which
  // the ban stage reports). A viewer outside the workspace hears no mix echo, so the room re-reads the lobby itself.
  const draftSettled =
    liveBoard != null && (liveBoard.session.status === "completed" || liveBoard.session.status === "cancelled");
  const refetchGame = mix.gameQuery.refetch;
  useEffect(() => {
    if (draftSettled) void refetchGame();
  }, [draftSettled, refetchGame]);

  const shown = useViewTransitionState(
    useMemo(
      () => ({ phase, lobby, board: liveBoard, heroState: heroRoom.state }),
      [phase, lobby, liveBoard, heroRoom.state]
    )
  );

  const [adminOpen, setAdminOpen] = useState(false);
  const [rostersOpen, setRostersOpen] = useState(true);
  // The player a member pick is for (`PickBanMember.id`), chosen on the rosters; the ban stage picks for them.
  const [chosenMember, setChosenMember] = useState<number | null>(null);

  if (lobby == null || shown.lobby == null) {
    return <PageStateCard state="not-found" headingLevel={1} description={tRoom("notFound")} />;
  }
  const shownLobby = shown.lobby;

  const lobbyTeamNames = teamNamesByIndex(game.settings, lobbyIndex);
  const defaultName = (index: number) => tVoice("team", { n: index + 1 });
  const teamNames: [string, string] = [lobbyTeamNames[0] ?? defaultName(0), lobbyTeamNames[1] ?? defaultName(1)];
  const variant =
    parseVariants(shownLobby.balance_result, lobbyTeamNames, slotCodeOrder(owner.ontology), defaultName)[
      shownLobby.selected_variant_index
    ] ?? null;
  const baseTeams: RoomTeam[] =
    shown.phase === "draft"
      ? shown.board != null
        ? draftRoomTeams(shown.board, teamNames)
        : emptyTeams(game, teamNames)
      : variant != null
        ? lineupRoomTeams(variant)
        : emptyTeams(game, teamNames);
  const teams = withHeroRoom(baseTeams, shown.heroState, shownLobby.live_seats ?? []);
  const heroesById = heroRoom.heroesById;
  // Only while the ban stage is up: its bar is what confirms the pick.
  const pickFor =
    shown.phase === "pregame" && shown.heroState != null ? memberChoice(shown.heroState, canWrite, chosenMember) : null;
  const awayIds = new Set((game.players ?? []).filter((row) => row.away).map((row) => row.workspace_member_id));
  const awayNames = teams
    .flatMap((team) => team.slots)
    .flatMap((slot) => (slot.seat != null && slot.seat.memberId != null && awayIds.has(slot.seat.memberId) ? [slot.seat.name] : []));

  // Who is on the clock: the drafting team, or the teams a ban/pick step waits for.
  const board = shown.board;
  const draftOrder = board != null ? [...board.teams].sort((left, right) => left.draft_position - right.draft_position) : [];
  const liveOrder = [...(shownLobby.live_seats ?? [])].sort((left, right) => left.slot - right.slot).map((seat) => seat.id);
  const active = teams.map((_, index) => {
    if (shown.phase === "draft" && board?.session.status === "live") {
      return draftOrder[index]?.id === board.current_pick?.draft_team_id;
    }
    if (shown.phase === "pregame" && shown.heroState != null && !shown.heroState.is_complete) {
      return shown.heroState.acting_team_ids.includes(liveOrder[index] ?? -1);
    }
    return false;
  });
  // Presence is only known while the live signal is up: without it every captain would read as gone.
  const captainOffline = draftOrder.map(
    (team) =>
      connectionState === "connected" &&
      team.captain_auth_user_id != null &&
      presence.users[team.captain_auth_user_id] == null &&
      board?.session.status !== "completed"
  );
  const waiting = (game.players ?? []).filter(
    (row) => row.participation !== "benched" && !row.away && row.current_lobby == null
  );
  const need = owner.lobbySize;
  const candidates = lobbyCandidateCount(game.players ?? [], lobbyIndex);
  const shortSeats = need != null && candidates < need ? tRoom("shortSeats", { count: candidates, need }) : null;
  const heroQueryKey = heroRoom.queryKey;
  const chatRoom =
    shown.phase === "draft" && board != null
      ? draftChatRoom(board.session.id)
      : shownLobby.live_encounter_id != null
        ? encounterChatRoom(shownLobby.live_encounter_id)
        : null;
  const filled = teams.map((team) => team.slots.filter((slot) => slot.seat != null).length);

  const captainControl = (team: DraftTeam, index: number) =>
    canWrite && board != null && board.session.status !== "completed" && board.session.status !== "cancelled" ? (
      <CaptainPicker
        board={board}
        team={team}
        label={tDraft("captainOf", { team: teamNames[index] ?? team.name })}
        disabled={mix.replaceDraftCaptain.isPending}
        onChange={(playerId) => mix.replaceDraftCaptain.mutate({ lobbyIndex, teamId: team.id, playerId })}
      />
    ) : null;

  const center =
    shown.phase === "draft" ? (
      board != null && gating != null ? (
        <RoomDraftStage
          board={board}
          teamNames={teamNames}
          owner={owner}
          gating={gating}
          options={gating.isMyPick ? (optionsQuery.data ?? null) : null}
          connectionState={connectionState}
          mutations={draftMutations}
          canHost={canWrite}
          myMemberId={myMemberId}
          waiting={waiting}
          adding={mix.addDraftPlayer.isPending}
          onAddPlayer={(workspaceMemberId) => mix.addDraftPlayer.mutate({ lobbyIndex, workspaceMemberId })}
        />
      ) : boardQuery.isError ? (
        <PageStateCard
          state="error"
          title={t("draftErrorTitle")}
          description={t("draftErrorHint")}
          actionLabel={tMixes("retry")}
          onAction={() => void boardQuery.refetch()}
        />
      ) : (
        <StageSkeleton />
      )
    ) : shown.phase === "pregame" ? (
      heroEncounterId != null && shown.heroState?.session != null ? (
        <RoomBanStage
          encounterId={heroEncounterId}
          workspaceId={workspaceId}
          discipline={discipline}
          seats={shownLobby.live_seats ?? []}
          state={{ ...shown.heroState, session: shown.heroState.session }}
          queryKey={heroQueryKey}
          heroesById={heroesById}
          canHost={canWrite}
          showAdmin={adminOpen}
          chosenMember={chosenMember}
          onComplete={() => void refetchGame()}
        />
      ) : (
        <StageSkeleton />
      )
    ) : (
      <RoomMatchStage
        phase={shown.phase}
        game={game}
        lobby={shownLobby}
        canWrite={canWrite}
        teamNames={[teams[0]?.name ?? teamNames[0], teams[1]?.name ?? teamNames[1]]}
        awayNames={awayNames}
        shortSeats={shortSeats}
        maps={mapsQuery.data ?? []}
        mixMatches={mix.matchesQuery.data ?? []}
        voiceUrl={mySeat != null && !mySeat.away && mySeat.current_lobby === lobbyIndex ? (mySeat.voice_url ?? null) : null}
        actions={{
          onBalance: () => mix.balance.mutate({ scope: "lobby", lobbyIndex }),
          balancing: mix.balance.isPending,
          onDraft: () => mix.seedDraft.mutate(lobbyIndex),
          drafting: mix.seedDraft.isPending,
          onStartMatch: (flipOpener) => mix.startMatch.mutate({ lobbyIndex, flipOpener }),
          starting: mix.startMatch.isPending,
          onRecord: (outcome) => mix.recordOutcome.mutate({ outcome, lobbyIndex }),
          recording: mix.recordOutcome.isPending,
          onNextMapChange: (mapId) => mix.setNextMap.mutate({ lobbyIndex, mapId }),
          settingNextMap: mix.setNextMap.isPending
        }}
      />
    );

  return (
    <div data-mix-room className="mx-auto flex w-full min-w-0 max-w-[1440px] flex-col gap-4">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <BackLink href={mixHref} onClick={leaveRoom}>
          {t("back")}
        </BackLink>
        <h1 className="min-w-0 truncate font-display text-heading font-bold text-[color:var(--aqt-fg)]">
          {`${game.name} · ${tLobbies("tab", { letter: lobbyLetter(lobbyIndex) })}`}
        </h1>
        <LobbyStage state={lobby.state ?? "idle"} startedAt={lobby.live_started_at} />
        {canWrite ? (
          <div className="ml-auto">
            <RoomHostMenu
              phase={phase}
              board={liveBoard}
              draftMutations={draftMutations}
              heroEncounterId={heroEncounterId}
              heroState={heroRoom.state}
              heroQueryKey={heroQueryKey}
              adminOpen={adminOpen}
              onAdminOpenChange={setAdminOpen}
              cancellingMatch={mix.cancelMatch.isPending}
              onCancelMatch={() => mix.cancelMatch.mutate(lobbyIndex)}
            />
          </div>
        ) : null}
      </header>

      {/* A phone stacks the two rosters side by side over the centre; they fold into one line when the centre needs
          the room (the hero grid). */}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-expanded={rostersOpen}
        className="group/trigger justify-between lg:hidden"
        onClick={() => setRostersOpen((open) => !open)}
      >
        <span className="truncate">
          {t("rostersSummary", {
            first: teams[0]?.name ?? teamNames[0],
            firstCount: `${filled[0] ?? 0}/${teams[0]?.slots.length ?? 0}`,
            second: teams[1]?.name ?? teamNames[1],
            secondCount: `${filled[1] ?? 0}/${teams[1]?.slots.length ?? 0}`
          })}
        </span>
        <ChevronDown aria-hidden className={triggerChevronClass} />
      </Button>

      <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-[minmax(260px,360px)_minmax(0,1fr)_minmax(260px,360px)] lg:items-start lg:gap-5">
        {teams.slice(0, 2).map((team, index) => (
          <RoomTeamColumn
            key={index}
            team={team}
            index={index}
            owner={owner}
            active={active[index] ?? false}
            myMemberId={myMemberId}
            awayIds={awayIds}
            heroesById={heroesById}
            sideLabel={(code) => sideLabelOf(discipline, code)}
            captainOffline={shown.phase === "draft" && (captainOffline[index] ?? false)}
            captainControl={draftOrder[index] != null ? captainControl(draftOrder[index], index) : null}
            pickFor={pickFor != null ? { ...pickFor, onChoose: setChosenMember } : undefined}
            className={cn(
              "row-start-1",
              index === 0 ? "col-start-1" : "col-start-2 lg:col-start-3",
              !rostersOpen && "hidden lg:flex"
            )}
          />
        ))}
        <section
          aria-label={t(`stage.${shown.phase}`)}
          style={{ viewTransitionName: `mix-stage-${shown.phase}` }}
          className={cn(
            "col-span-2 row-start-2 flex min-w-0 flex-col gap-3 lg:col-span-1 lg:col-start-2 lg:row-start-1",
            // The scoreboard reaches the rosters' foot; the other stages keep their own height.
            (shown.phase === "ready" || shown.phase === "live") && "lg:self-stretch"
          )}
        >
          {/* Every phase: players join the game's lobby during the draft or the bans as often as before the start. */}
          {canWrite || lobby?.lobby_code != null ? (
            <Card className="overflow-hidden">
              <LobbyCodeStrip
                lobbyCode={lobby?.lobby_code ?? null}
                canWrite={canWrite}
                saving={mix.setLobbyCode.isPending}
                className="border-b-0"
                onLobbyCodeChange={(lobbyCode) => mix.setLobbyCode.mutate({ lobbyIndex, lobbyCode })}
              />
            </Card>
          ) : null}
          {center}
        </section>
      </div>

      {chatRoom != null ? <RoomChat key={chatRoom.topic} room={chatRoom} defaultOpen={false} /> : null}
    </div>
  );
}

/** A lobby with no lineup yet: each team's seats, empty, in the shape's order. */
function emptyTeams(game: CustomGame, teamNames: readonly string[]): RoomTeam[] {
  const shape = game.roster_shape;
  const codes = shape != null ? slotCodesOf(shape.slots).flatMap((code) => Array.from({ length: shape.slots[code] ?? 0 }, () => code)) : [];
  return teamNames.map((name, index) => ({
    name,
    averageRank: null,
    slots: codes.map((code, position) => ({
      key: `${index}:${position}`,
      role: code === OPEN_SLOT_CODE ? null : code,
      seat: null
    })),
    bans: [],
    unassignedPicks: [],
    side: null
  }));
}

/** A team's captain: before the start any pool player, during the draft a player already on the team. */
function CaptainPicker({
  board,
  team,
  label,
  disabled,
  onChange
}: Readonly<{
  board: DraftBoard;
  team: DraftTeam;
  label: string;
  disabled: boolean;
  onChange: (playerId: number) => void;
}>) {
  const setup = board.session.status === "setup" || board.session.status === "ready";
  const current = board.players.find((player) => player.is_captain && player.drafted_by_team_id === team.id);
  const options = setup
    ? board.players.filter((player) => player.status !== "removed")
    : board.players.filter((player) => player.drafted_by_team_id === team.id);
  return (
    <Select
      value={current ? String(current.id) : NONE}
      disabled={disabled}
      onValueChange={(value) => value !== NONE && onChange(Number(value))}
    >
      <SelectTrigger aria-label={label} title={label} size="sm" className="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {current ? null : <SelectItem value={NONE}>{label}</SelectItem>}
        {options.map((player) => (
          <SelectItem key={player.id} value={String(player.id)}>
            {draftPlayerName(player)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** The centre's shape while its data loads: a header strip and a block of cards. */
function StageSkeleton() {
  const t = useTranslations("mixes");
  return (
    <div role="status" className="flex flex-col gap-3">
      <span className="sr-only">{t("loading")}</span>
      <Skeleton aria-hidden className="h-24 w-full rounded-xl" />
      <Skeleton aria-hidden className="h-64 w-full rounded-xl" />
    </div>
  );
}
