"use client";

import dynamic from "next/dynamic";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { PickupGettingStarted } from "@/app/balancer/mix/PickupGettingStarted";
import { PickupLobbyCards } from "@/app/balancer/mix/PickupLobbyCards";
import { PickupLobbyPanel } from "@/app/balancer/mix/PickupLobbyPanel";
import { PickupMixHeader } from "@/app/balancer/mix/PickupMixHeader";
import { PickupMySeatPanel } from "@/app/balancer/mix/PickupMySeatPanel";
import { PickupTeamsPanel } from "@/app/balancer/mix/PickupTeamsPanel";
import { PickupVoicePanel } from "@/app/balancer/mix/PickupVoicePanel";
import { MatchHistoryList } from "@/app/balancer/mix/_components/MatchHistoryList";
import { useRoomAutoOpen } from "@/app/balancer/mix/_hooks/useRoomAutoOpen";
import { lobbyIndexFromLetter, lobbyLetter, mixRoomHref, playsInRoom } from "@/app/balancer/mix/pickup-chrome";
import { navigateRoom } from "@/app/balancer/mix/_room/room-navigation";
import {
  canWriteMix,
  buildMixOwner,
  myLobbyTeam,
  playerLabel,
  summarizeLineup,
} from "@/app/balancer/mix/pickup-lineup";
import { usePickupMix } from "@/app/balancer/mix/usePickupMix";
import { Card } from "@/components/ui/card";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useCatalogEntities } from "@/hooks/useCatalogEntities";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useEntityWorkspace } from "@/hooks/useEntityWorkspace";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { slotCodeOrder } from "@/lib/roster/ontology";
import { customGameKeys, customGameService, type CustomGame } from "@/services/custom-game.service";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { useWorkspaceStore } from "@/stores/workspace.store";

// Closed until the host or a row opens them: lazy chunks, not first-load JS.
const PickupAddPlayersDialog = dynamic(
  () => import("@/app/balancer/mix/PickupAddPlayersDialog").then((m) => m.PickupAddPlayersDialog),
  { ssr: false }
);
const PickupAccessDialog = dynamic(
  () => import("@/app/balancer/mix/PickupAccessDialog").then((m) => m.PickupAccessDialog),
  { ssr: false }
);
const PickupPlayerSheet = dynamic(
  () => import("@/app/balancer/mix/PickupPlayerSheet").then((m) => m.PickupPlayerSheet),
  { ssr: false }
);

/**
 * One mix's overview at `/balancer/mix/[gameId]`: the host's desk. The lineup column a host curates, the header and --
 * with several lobbies -- one card per lobby carrying its next action, the players no lobby seats, the history and the
 * leaderboard. A one-lobby mix shows its lobby's desk (its teams panel) right there; with several, `?lobby=<letter>`
 * puts the chosen lobby's desk under the cards. What plays out in a lobby's room (spec §7.5) -- the draft, the hero
 * bans and picks, the match chat -- lives on that room's own page (`mixRoomHref`): a seated player is taken there once
 * per phase, a host once their Draft goes through.
 *
 * Which balance option is on screen is the lobby's own `selected_variant_index`, not page state, and the mix itself
 * carries no solver or format settings: those belong to the host's account (`components/account-settings/
 * MixBalancerSection`).
 */
export function PickupMixScreen() {
  const params = useParams<{ gameId: string }>();
  const routeGameId = Number(params.gameId);
  const pickedGameId = Number.isSafeInteger(routeGameId) && routeGameId > 0 ? routeGameId : null;
  const hostWorkspaceId = useWorkspaceStore((state) => state.hostLockedWorkspaceId);
  const t = useTranslations("mixes");
  const entityQuery = useQuery({
    queryKey: customGameKeys.byId(pickedGameId ?? 0, hostWorkspaceId),
    queryFn: () => customGameService.getById(pickedGameId as number, hostWorkspaceId),
    enabled: pickedGameId != null,
  });
  if (entityQuery.isError || pickedGameId == null) {
    return (
      <PageStateCard
        state="error"
        headingLevel={1}
        title={t("list.errorTitle")}
        description={t("list.errorDescription")}
        actionLabel={t("retry")}
        onAction={() => void entityQuery.refetch()}
      />
    );
  }
  if (!entityQuery.data) {
    // Detail-shaped: the lineup column beside header, lobby cards and teams.
    return (
      <div role="status" className="flex flex-col gap-5 xl:flex-row xl:items-start">
        <span className="sr-only">{t("loading")}</span>
        <Skeleton aria-hidden className="h-96 w-full rounded-xl xl:w-[568px] xl:shrink-0" />
        <div aria-hidden className="mx-auto flex w-full min-w-0 max-w-[1180px] flex-1 flex-col gap-5">
          <Skeleton className="h-20 w-full rounded-xl" />
          <Skeleton className="h-9 w-64 rounded-lg" />
          <Skeleton className="h-64 w-full rounded-xl" />
        </div>
      </div>
    );
  }
  return <PickupMixDetail key={entityQuery.data.id} initialGame={entityQuery.data} />;
}

function PickupMixDetail({ initialGame }: Readonly<{ initialGame: CustomGame }>) {
  const tTeams = useTranslations("mixes.teams");
  const tVoice = useTranslations("mixes.voice");
  const workspaceId = initialGame.workspace_id;
  const pickedGameId = initialGame.id;
  useEntityWorkspace(workspaceId, initialGame.discipline);
  const currentUserId = useAuthProfileStore((state) => state.user?.id ?? null);
  // The board is public (`config/auth.ts`), so the seat read is the one thing here that needs a session.
  const isSignedIn = useAuthProfileStore((state) => state.status === "authenticated");
  const { canAccessPermission, isSuperuser, isWorkspaceAdmin } = usePermissions();
  const router = useRouter();
  const searchParams = useSearchParams();
  // The lobby whose desk a several-lobby overview shows under its cards; the mix's lobby count bounds it below.
  const requestedLobby = lobbyIndexFromLetter(searchParams.get("lobby") ?? undefined);
  // The mix-hosting grant: a workspace member can run a pickup game without admin rights over teams.
  const canEdit = workspaceId != null && canAccessPermission("custom_game.create", workspaceId);
  // Workspace admin, the gate for hard-deleting a mix (`_hard_delete` in balancer-service's `rpc/custom.py`).
  const isAdminHere = workspaceId != null && (isSuperuser || isWorkspaceAdmin(workspaceId));

  const [openPlayerId, setOpenPlayerId] = useState<number | null>(null);
  const [isPoolOpen, setIsPoolOpen] = useState(false);
  const [isAccessOpen, setIsAccessOpen] = useState(false);
  // Whether this viewer may write the mix, which decides the voice read below (see `canWrite`).
  const [voiceEnabled, setVoiceEnabled] = useState(false);

  const {
    selectedGameId,
    activeLobby,
    setActiveLobby,
    gamesQuery,
    gameQuery,
    matchesQuery,
    rotationQuery,
    mySeatQuery,
    myQueuePosition,
    setRoster,
    patchPlayer,
    applyRotationHints,
    balance,
    recordOutcome,
    startMatch,
    cancelMatch,
    setCaptain,
    undoMatch,
    setNextMap,
    setLobbyCode,
    setVariantIndex,
    setLobbyCount,
    closeMix,
    hardDeleteMix,
    setAuthorRanks,
    setTeamNames,
    renameMix,
    postToDiscord,
    transferHost,
    addCoHost,
    removeCoHost,
    swapSeats,
    joinMix,
    leaveMix,
    updateMySeat,
    setMyAway,
    setSelfService,
    setBanPreset,
    setDraftSettings,
    seedDraft,
    splitPool,
    postSignup,
    deleteDiscordPost,
    voiceOptionsQuery,
    setVoiceChannels,
    voiceMove,
    voiceReturn,
  } = usePickupMix(workspaceId, pickedGameId, {
    seatEnabled: isSignedIn,
    voiceEnabled,
    initialGame,
    // The rotation hints are the shown desk's lobby's; the hook falls back to A for a letter the mix does not run.
    initialLobby: requestedLobby ?? 0,
  });

  const game = gameQuery.data;
  // The owner game's roles, names, tints and grid; empty until its metadata loads, never another game's vocabulary.
  const discipline = game?.discipline ?? initialGame.discipline;
  const metadataQuery = useDisciplineMetadata(workspaceId, discipline);
  const workspaceGrid = useDivisionGrid(discipline);
  const owner = useMemo(
    () => buildMixOwner(metadataQuery.data, game?.roster_shape, workspaceGrid),
    [metadataQuery.data, game?.roster_shape, workspaceGrid],
  );
  // The mix's own game's maps: the roll pool and the picker. The chosen map is the lobby's own `next_map_id`.
  const mapsQuery = useCatalogEntities(game?.discipline, "map");
  const statsQuery = useQuery({
    queryKey: customGameKeys.stats(workspaceId ?? 0, null, game?.discipline),
    queryFn: ({ signal }) => customGameService.stats(workspaceId as number, null, game?.discipline, { signal }),
    enabled: workspaceId != null && game != null,
    staleTime: 60_000,
  });
  const rows = game?.players ?? [];
  const lobbies = game?.lobbies ?? [];
  const lobbyCount = game?.lobby_count ?? initialGame.lobby_count;
  // The lobby whose teams are on screen: a one-lobby mix's only one, else the one `?lobby=` picks (none: cards only).
  const selectedLobby = lobbyCount > 1 && requestedLobby != null && requestedLobby < lobbyCount ? requestedLobby : null;
  const shownLobby = lobbyCount < 2 ? 0 : selectedLobby;
  const lobby = shownLobby == null ? undefined : lobbies.find((row) => row.lobby_index === shownLobby);
  // Picking another desk moves the lineup's rotation hints with it (state reset during render).
  if (activeLobby !== (shownLobby ?? 0)) {
    setActiveLobby(shownLobby ?? 0);
  }
  const rosterIds = rows.map((row) => row.workspace_member_id);
  const isHost = game != null && currentUserId != null && game.host_user_id === currentUserId;
  const canWrite = canWriteMix(game, currentUserId, isSuperuser);
  // State reset during render: the voice read is a writer's, and that is only knowable once the mix has loaded.
  if (voiceEnabled !== canWrite) {
    setVoiceEnabled(canWrite);
  }
  // Ranks are the host's book (`author_user_id = game.host_user_id`); a closed mix's host can still correct one.
  const canEditRanks = canEdit && isHost;
  const openRow = rows.find((row) => row.workspace_member_id === openPlayerId) ?? null;
  const savingPlayerId = patchPlayer.isPending ? (patchPlayer.variables?.workspaceMemberId ?? null) : null;
  // The sheet's Save can fire both mutations at once, so its saving state watches both.
  const sheetSaving =
    openRow != null &&
    ((patchPlayer.isPending && patchPlayer.variables?.workspaceMemberId === openRow.workspace_member_id) ||
      (setAuthorRanks.isPending && setAuthorRanks.variables?.workspaceMemberId === openRow.workspace_member_id));
  const matches = matchesQuery.data ?? [];
  const mySeat = mySeatQuery.data;
  const myMemberId = mySeat?.seat?.workspace_member_id ?? null;
  // The lobby the viewer's seat names: its seats or, while it drafts, its draft pool (balancer-service
  // `current_lobbies`).
  const myLobby = lobbies.find((row) => row.lobby_index === mySeat?.seat?.current_lobby);
  useRoomAutoOpen(pickedGameId, myLobby, canWrite);
  // The phone view of the player's own lobby: their team, its captain and the map (spec §7.5, G1).
  const myTeam = myLobbyTeam(game, myMemberId, slotCodeOrder(owner.ontology), (team) =>
    tVoice("team", { n: team + 1 }),
  );
  const nextMapName =
    myTeam?.nextMapId == null
      ? null
      : ((mapsQuery.data ?? []).find((map) => map.id === myTeam.nextMapId)?.name ?? null);
  const selectLobby = (index: number | null) => {
    const params = new URLSearchParams(searchParams.toString());
    if (index == null) params.delete("lobby");
    else params.set("lobby", lobbyLetter(index));
    const rest = params.toString();
    router.replace(rest ? `/balancer/mix/${pickedGameId}?${rest}` : `/balancer/mix/${pickedGameId}`, {
      scroll: false,
    });
  };
  // A host's Draft opens the lobby's room, where the captains pick.
  const draft = (lobbyIndex: number) =>
    seedDraft.mutate(lobbyIndex, {
      onSuccess: () => navigateRoom("enter", lobbyIndex, () => router.push(mixRoomHref(pickedGameId, lobbyIndex)))
    });

  const togglePoolMember = (memberId: number) => {
    if (selectedGameId == null) return;
    setRoster.mutate(
      rosterIds.includes(memberId) ? rosterIds.filter((id) => id !== memberId) : [...rosterIds, memberId],
    );
  };

  const copyHandles = () => {
    const handles = rows
      .filter((row) => row.participation !== "benched")
      .map((row) => row.identity?.handle ?? playerLabel(row));
    if (handles.length === 0) {
      notify.error(tTeams("copyEmpty"));
      return;
    }
    void navigator.clipboard
      .writeText(handles.join("\n"))
      .then(() => notify.success(tTeams("copied", { count: handles.length })))
      .catch(() => notify.error(tTeams("clipboardError")));
  };

  const teamsPanel =
    shownLobby == null ? null : (
      <PickupTeamsPanel
        canWrite={canWrite}
        gamesLoading={gamesQuery.isLoading || gameQuery.isLoading}
        gamesError={gamesQuery.isError || gameQuery.isError}
        onRetryGames={() => {
          void gamesQuery.refetch();
          void gameQuery.refetch();
        }}
        game={game}
        lobby={lobby}
        lobbyIndex={shownLobby}
        owner={owner}
        gameLoading={gameQuery.isLoading}
        hasMix={selectedGameId != null}
        balancing={balance.isPending}
        activeCount={summarizeLineup(rows, owner.roles).active}
        onBalance={() => balance.mutate({ scope: "lobby", lobbyIndex: shownLobby })}
        drafting={seedDraft.isPending}
        onDraft={() => draft(shownLobby)}
        roomHref={mixRoomHref(pickedGameId, shownLobby)}
        variantIndex={lobby?.selected_variant_index ?? 0}
        onVariantIndexChange={(index) => setVariantIndex.mutate({ lobbyIndex: shownLobby, variantIndex: index })}
        startingMatch={startMatch.isPending}
        onStartMatch={(flipOpener) => startMatch.mutate({ lobbyIndex: shownLobby, flipOpener })}
        cancellingMatch={cancelMatch.isPending}
        onCancelMatch={() => cancelMatch.mutate(shownLobby)}
        onMakeCaptain={(workspaceMemberId) => setCaptain.mutate({ lobbyIndex: shownLobby, workspaceMemberId })}
        recordingOutcome={recordOutcome.isPending}
        onRecordOutcome={(input) => recordOutcome.mutate(input)}
        maps={mapsQuery.data ?? []}
        // A several-lobby overview lists every lobby's history in its own card, under the desk.
        matches={lobbyCount < 2 ? matches : []}
        mixMatches={matches}
        undoingMatchId={undoMatch.isPending ? (undoMatch.variables ?? null) : null}
        onUndoMatch={(matchId) => undoMatch.mutate(matchId)}
        settingNextMap={setNextMap.isPending}
        onNextMapChange={(mapId) => setNextMap.mutate({ lobbyIndex: shownLobby, mapId })}
        settingLobbyCode={setLobbyCode.isPending}
        onLobbyCodeChange={(lobbyCode) => setLobbyCode.mutate({ lobbyIndex: shownLobby, lobbyCode })}
        closingMix={closeMix.isPending}
        onCloseMix={() => closeMix.mutate()}
        onRenameTeam={(teamIndex, name) => setTeamNames.mutateAsync({ teamIndex, name })}
        onSwapSeats={(idx, firstUuid, secondUuid) =>
          swapSeats.mutateAsync({ lobbyIndex: shownLobby, variantIndex: idx, firstUuid, secondUuid })
        }
        onCopyHandles={copyHandles}
        postingToDiscord={postToDiscord.isPending}
        onPostToDiscord={(idx) => postToDiscord.mutate({ lobbyIndex: shownLobby, variantIndex: idx })}
        emptyState={
          canWrite && game != null && game.matches_count === 0
            ? (balanceAction) => (
                <PickupGettingStarted
                  game={game}
                  onOpenPool={() => setIsPoolOpen(true)}
                  onPostSignup={(selfSignup) => postSignup.mutate(selfSignup)}
                  posting={postSignup.isPending}
                  balanceAction={balanceAction}
                />
              )
            : undefined
        }
      />
    );

  // Only a writer picks voices or moves anyone: the endpoints 403 everyone else.
  const voicePanel =
    canWrite && game != null ? (
      <PickupVoicePanel
        game={game}
        games={gamesQuery.data ?? []}
        options={voiceOptionsQuery.data}
        optionsLoading={voiceOptionsQuery.isLoading}
        saving={setVoiceChannels.isPending}
        moving={voiceMove.isPending}
        returning={voiceReturn.isPending}
        report={voiceMove.data ?? voiceReturn.data}
        reportLobby={voiceMove.data ? voiceMove.variables : voiceReturn.variables}
        onSave={(patch) => setVoiceChannels.mutate(patch)}
        onMove={(lobbyIndex) => {
          // One report on screen at a time: the stale one is about a move that already happened.
          voiceReturn.reset();
          voiceMove.mutate(lobbyIndex);
        }}
        onReturn={(lobbyIndex) => {
          voiceMove.reset();
          voiceReturn.mutate(lobbyIndex);
        }}
      />
    ) : null;

  // Visible when the mix invites signups or this viewer is already in it; the board stays as public as it was.
  const mySeatPanel =
    mySeat != null && (mySeat.self_signup !== "closed" || mySeat.seat != null) ? (
      <PickupMySeatPanel
        state={mySeat}
        owner={owner}
        saving={joinMix.isPending || leaveMix.isPending || updateMySeat.isPending || setMyAway.isPending}
        onJoin={() => joinMix.mutate()}
        onLeave={() => leaveMix.mutate()}
        onSave={(patch) => updateMySeat.mutate(patch)}
        myTeam={myTeam}
        nextMapName={nextMapName}
        queuePosition={myQueuePosition}
        lobbies={lobbies.map((row) => ({ lobbyIndex: row.lobby_index, state: row.state ?? "idle" }))}
        onSetAway={(away) => setMyAway.mutate(away)}
        roomHref={
          myLobby != null && (playsInRoom(myLobby.state) || myLobby.state === "live")
            ? mixRoomHref(pickedGameId, myLobby.lobby_index)
            : null
        }
      />
    ) : null;

  // The host's pool, with the rotation hints of the lobby whose desk is on screen (lobby A while none is).
  const lineupPanel = (
    <PickupLobbyPanel
      canWrite={canWrite}
      hasMix={selectedGameId != null}
      rows={rows}
      lobbyCount={lobbyCount}
      owner={owner}
      rotation={rotationQuery.data ?? []}
      savingPlayerId={savingPlayerId}
      clearing={setRoster.isPending}
      onPatchPlayer={(workspaceMemberId, patch) => patchPlayer.mutate({ workspaceMemberId, patch })}
      onClear={() => setRoster.mutate([])}
      onRemovePlayer={togglePoolMember}
      onOpenPlayer={setOpenPlayerId}
      onApplyRotationHints={() => applyRotationHints.mutate()}
      applyingHints={applyRotationHints.isPending}
    />
  );

  const dialogs = (
    <>
      {game ? (
        <PickupAddPlayersDialog
          open={isPoolOpen}
          onOpenChange={setIsPoolOpen}
          workspaceId={workspaceId}
          discipline={game.discipline}
          owner={owner}
          canEdit={canEdit}
          canEditRanks={canEditRanks}
          canWrite={canWrite}
          hostUserId={game.host_user_id ?? null}
          rows={rows}
          onTogglePlayer={togglePoolMember}
        />
      ) : null}

      <PickupAccessDialog
        open={isAccessOpen}
        onOpenChange={setIsAccessOpen}
        workspaceId={workspaceId}
        game={game}
        addingCoHost={addCoHost.isPending}
        removingCoHostId={removeCoHost.isPending ? (removeCoHost.variables ?? null) : null}
        transferring={transferHost.isPending}
        onAddCoHost={(userId) => addCoHost.mutate(userId)}
        onRemoveCoHost={(userId) => removeCoHost.mutate(userId)}
        onTransfer={(newHostUserId) => transferHost.mutate(newHostUserId)}
      />

      <PickupPlayerSheet
        row={openRow}
        discipline={game?.discipline ?? ""}
        owner={owner}
        lobbyCount={lobbyCount}
        mixStats={
          statsQuery.data?.members.find((member) => member.workspace_member_id === openRow?.workspace_member_id) ??
          null
        }
        canEdit={canWrite}
        saving={sheetSaving}
        onOpenChange={(open) => {
          if (!open) setOpenPlayerId(null);
        }}
        onSave={(patch, rankChange) => {
          if (!openRow) return;
          patchPlayer.mutate({ workspaceMemberId: openRow.workspace_member_id, patch });
          if (rankChange) {
            setAuthorRanks.mutate({
              workspaceMemberId: openRow.workspace_member_id,
              discipline: game!.discipline,
              ...rankChange,
            });
          }
        }}
        onRemove={() => {
          if (openRow) {
            togglePoolMember(openRow.workspace_member_id);
            setOpenPlayerId(null);
          }
        }}
      />
    </>
  );

  return (
    <>
      <div className="flex flex-1 flex-col gap-5">
        {/* Fixed-width lineup, fluid matchup: the lineup stops improving past ~570px, the matchup absorbs the rest
            up to its own cap. */}
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start">
          <div className="xl:w-[568px] xl:shrink-0">{lineupPanel}</div>

          <div className="mx-auto flex w-full min-w-0 max-w-[1180px] flex-1 flex-col gap-5">
            <PickupMixHeader
              canWrite={canWrite}
              game={game}
              gameLoading={gameQuery.isLoading}
              onOpenPool={() => setIsPoolOpen(true)}
              showsRoles={owner.showsRoles}
              onOpenAccess={() => setIsAccessOpen(true)}
              canDelete={isAdminHere}
              deleting={hardDeleteMix.isPending}
              onDeleteMix={() => hardDeleteMix.mutate(undefined, { onSuccess: () => router.push("/balancer/mix") })}
              onRename={(name) => renameMix.mutateAsync(name)}
              onSetSelfService={(patch) => setSelfService.mutate(patch)}
              savingSelfService={setSelfService.isPending}
              onSetBanPreset={(preset) => setBanPreset.mutate({ hero_ban_preset: preset })}
              onSetFearless={(fearless) => {
                if (game != null) setBanPreset.mutate({ hero_ban_preset: game.hero_ban_preset, hero_fearless: fearless });
              }}
              onSetHeroClocks={(clocks) => {
                if (game != null) setBanPreset.mutate({ hero_ban_preset: game.hero_ban_preset, ...clocks });
              }}
              onSetHeroPickers={(pickers) => {
                if (game != null) setBanPreset.mutate({ hero_ban_preset: game.hero_ban_preset, ...pickers });
              }}
              savingBanPreset={setBanPreset.isPending}
              onSetDraftSettings={(settings) => setDraftSettings.mutate(settings)}
              savingDraftSettings={setDraftSettings.isPending}
              onPostSignup={(selfSignup) => postSignup.mutate(selfSignup)}
              postingSignup={postSignup.isPending}
              onDeleteDiscordPost={(postId) => deleteDiscordPost.mutate(postId)}
              deletingDiscordPost={deleteDiscordPost.isPending}
              settingLobbyCount={setLobbyCount.isPending}
              onLobbyCountChange={(count) => setLobbyCount.mutate(count)}
            />
            {lobbyCount < 2 ? (
              teamsPanel
            ) : game != null ? (
              <>
                <PickupLobbyCards
                  game={game}
                  rows={rows}
                  owner={owner}
                  canWrite={canWrite}
                  balancingLobby={
                    balance.isPending && balance.variables?.scope === "lobby" ? balance.variables.lobbyIndex : null
                  }
                  startingLobby={startMatch.isPending ? (startMatch.variables?.lobbyIndex ?? null) : null}
                  recordingLobby={recordOutcome.isPending ? (recordOutcome.variables?.lobbyIndex ?? null) : null}
                  shufflingAll={balance.isPending && balance.variables?.scope === "all"}
                  onBalance={(lobbyIndex) => balance.mutate({ scope: "lobby", lobbyIndex })}
                  onStartMatch={(lobbyIndex, flipOpener) => startMatch.mutate({ lobbyIndex, flipOpener })}
                  onRecordOutcome={(input) => recordOutcome.mutate(input)}
                  onShuffleAll={() => balance.mutate({ scope: "all" })}
                  drafting={seedDraft.isPending ? (seedDraft.variables ?? null) : null}
                  onDraft={draft}
                  splitting={splitPool.isPending}
                  onSplitPool={() => splitPool.mutate()}
                  selectedLobby={selectedLobby}
                  onSelectLobby={selectLobby}
                />
                {teamsPanel}
                {matches.length > 0 ? (
                  <Card className="px-4 py-3.5">
                    <MatchHistoryList
                      matches={matches}
                      lobbyCount={lobbyCount}
                      canWrite={canWrite}
                      undoingMatchId={undoMatch.isPending ? (undoMatch.variables ?? null) : null}
                      onUndoMatch={(matchId) => undoMatch.mutate(matchId)}
                      discipline={discipline}
                      standalone
                    />
                  </Card>
                ) : null}
              </>
            ) : null}
            {voicePanel}
            {mySeatPanel}
          </div>
        </div>
      </div>
      {dialogs}
    </>
  );
}
