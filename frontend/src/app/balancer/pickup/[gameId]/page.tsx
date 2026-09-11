"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { PickupAddPlayersDialog } from "@/app/balancer/pickup/PickupAddPlayersDialog";
import { PickupLobbyPanel } from "@/app/balancer/pickup/PickupLobbyPanel";
import { PickupMixConfigDialog } from "@/app/balancer/pickup/PickupMixConfigDialog";
import { PickupAccessDialog } from "@/app/balancer/pickup/PickupAccessDialog";
import { PickupMixHeader } from "@/app/balancer/pickup/PickupMixHeader";
import { PickupPlayerSheet } from "@/app/balancer/pickup/PickupPlayerSheet";
import { PickupTeamsPanel } from "@/app/balancer/pickup/PickupTeamsPanel";
import {
  PICKUP_TERMINAL_STATUSES,
  playerLabel,
  summarizeLineup,
} from "@/app/balancer/pickup/pickup-lineup";
import { usePickupMix } from "@/app/balancer/pickup/usePickupMix";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { customGameKeys, customGameService } from "@/services/custom-game.service";
import mapService from "@/services/map.service";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * One mix in two columns: the **lineup** a host curates, and the **matchup** the
 * solver produced from it.
 *
 * Those are the only two things on screen at once because they are the only two
 * a host reads together — "is this pool balanceable" and "is this balance fair".
 * The workspace roster is a third question asked twice a night, so it lives in
 * an overlay (`PickupAddPlayersDialog`) instead of a permanent column, and
 * detail lives in a sheet.
 *
 * Which mix this is comes from the route, not from state this screen owns —
 * switching to another one, or starting a new one, happens on the list at
 * `/balancer/pickup`. This screen only ever reads and edits the one the host
 * already picked.
 *
 * The open balance option is page state, not panel state: the fullscreen board
 * and the inline matchup must never disagree about which option is being read
 * out to a lobby.
 */
export default function BalancerPickupMixPage() {
  const params = useParams<{ gameId: string }>();
  const routeGameId = Number(params.gameId);
  const pickedGameId = Number.isFinite(routeGameId) ? routeGameId : null;

  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const currentUserId = useAuthProfileStore((state) => state.user?.id ?? null);
  const { canAccessPermission, isSuperuser, isWorkspaceAdmin } = usePermissions();
  const router = useRouter();
  // The mix-hosting grant, not a tournament permission: a workspace member can
  // run a pickup game without holding admin rights over teams.
  const canEdit = workspaceId != null && canAccessPermission("custom_game.create", workspaceId);
  // Irreversible, so it needs more than the host-or-co-host grant every other
  // write here checks -- see `_hard_delete` in balancer-service's `rpc/custom.py`.
  const canDeleteMix = workspaceId != null && (isSuperuser || isWorkspaceAdmin(workspaceId));

  const [openPlayerId, setOpenPlayerId] = useState<number | null>(null);
  const [isPoolOpen, setIsPoolOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isAccessOpen, setIsAccessOpen] = useState(false);
  const [variantIndex, setVariantIndex] = useState(0);
  // The OW catalogue with its gamemodes: the roll pool for the next map and
  // the manual picker. Which map is *chosen* is the mix's own `next_map_id`,
  // so a co-host in another tab sees the same roll.
  const mapsQuery = useQuery({
    queryKey: ["maps", "gamemode"],
    queryFn: () => mapService.getAll({ entities: ["gamemode"] }).then((page) => page.results),
    staleTime: 5 * 60 * 1000,
  });
  // All-time only: the sheet reports a player's standing, and a window would
  // make that read differently depending on what the list page was last set to.
  const statsQuery = useQuery({
    queryKey: customGameKeys.stats(workspaceId ?? 0, null),
    queryFn: () => customGameService.stats(workspaceId as number, null),
    enabled: workspaceId != null,
    staleTime: 60_000,
  });

  const {
    selectedGameId,
    gamesQuery,
    gameQuery,
    matchesQuery,
    rotationQuery,
    setRoster,
    patchPlayer,
    applyRotationHints,
    balance,
    recordOutcome,
    undoMatch,
    setNextMap,
    closeMix,
    hardDeleteMix,
    setAuthorRanks,
    setTeamNames,
    setRoleMask,
    setPointsPerWin,
    setDiscordChannel,
    postToDiscord,
    transferHost,
    addCoHost,
    removeCoHost,
    swapSeats,
  } = usePickupMix(workspaceId ?? 0, pickedGameId);

  const game = gameQuery.data;
  const rows = game?.players ?? [];
  const rosterIds = rows.map((row) => row.workspace_member_id);
  // Everything that writes a mix -- roster, player patch, balance, outcome --
  // goes through `_writable`, which 403s anyone but the host or a co-host.
  // That per-game grant is the actual write gate: `custom_game.create` only
  // decides who may start a *new* mix (see `canEdit` above), so a co-host
  // added to somebody else's mix writes it regardless of their own role.
  const isHost = game != null && currentUserId != null && game.host_user_id === currentUserId;
  const isCoHost =
    game != null && currentUserId != null && game.co_hosts.some((coHost) => coHost.user_id === currentUserId);
  // A completed or cancelled mix is read-only server-side; hide its controls
  // rather than let a click 409.
  const canWrite = (isHost || isCoHost) && game != null && !PICKUP_TERMINAL_STATUSES[game.status];
  // Ranks are the host's book -- `author_user_id = game.host_user_id` is the
  // layer this mix resolves against. Anyone else who typed here wrote their own
  // book, got a 200, and watched the number stay put. Not gated on `canWrite`:
  // a rank outlives the game it was typed in, so a closed mix can still be
  // corrected by its host.
  const canEditRanks = canEdit && isHost;
  const openRow = rows.find((row) => row.workspace_member_id === openPlayerId) ?? null;
  const savingPlayerId = patchPlayer.isPending
    ? (patchPlayer.variables?.workspaceMemberId ?? null)
    : null;
  // The sheet's Save can fire both mutations at once, so its own saving state
  // watches both rather than reusing the lobby row's patch-only indicator.
  const sheetSaving =
    openRow != null &&
    ((patchPlayer.isPending && patchPlayer.variables?.workspaceMemberId === openRow.workspace_member_id) ||
      (setAuthorRanks.isPending &&
        setAuthorRanks.variables?.workspaceMemberId === openRow.workspace_member_id));

  if (workspaceId == null) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        Pick a workspace in the top bar to open mixes.
      </div>
    );
  }

  const togglePoolMember = (memberId: number) => {
    if (selectedGameId == null) return;
    setRoster.mutate(
      rosterIds.includes(memberId)
        ? rosterIds.filter((id) => id !== memberId)
        : [...rosterIds, memberId],
    );
  };

  const copyBattleTags = () => {
    const tags = rows
      .filter((row) => row.participation !== "benched")
      .map((row) => row.battle_tag ?? playerLabel(row));
    if (tags.length === 0) {
      notify.error("Nobody is in the balance yet");
      return;
    }
    void navigator.clipboard
      .writeText(tags.join("\n"))
      .then(() => notify.success(`Copied ${tags.length} battletags`))
      .catch(() => notify.error("Could not reach the clipboard"));
  };

  return (
    <>
      <div className="flex flex-1 flex-col gap-5">
        {/* Fixed-width lineup, fluid matchup: the lineup's content is a known
            set of columns (switch, name, three role glyphs, rank) that stops
            improving past ~570px, while the matchup absorbs the width it is
            given up to its own cap. The mix header sits only above the teams
            block now, not over the whole space -- the lineup needs no
            identity row of its own, it already lives under it (Pregame
            Room's pick-ban grid takes the same header, merged above the grid
            it belongs to rather than spanning the timeline beside it too). */}
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start">
          <div className="xl:w-[568px] xl:shrink-0">
            <PickupLobbyPanel
              canWrite={canWrite}
              hasMix={selectedGameId != null}
              rows={rows}
              rotation={rotationQuery.data ?? []}
              savingPlayerId={savingPlayerId}
              clearing={setRoster.isPending}
              onPatchPlayer={(workspaceMemberId, patch) =>
                patchPlayer.mutate({ workspaceMemberId, patch })
              }
              onClear={() => setRoster.mutate([])}
              onRemovePlayer={togglePoolMember}
              onOpenPlayer={setOpenPlayerId}
              onOpenPool={() => setIsPoolOpen(true)}
              onApplyRotationHints={() => applyRotationHints.mutate()}
              applyingHints={applyRotationHints.isPending}
            />
          </div>

          <div className="mx-auto flex w-full min-w-0 max-w-[1180px] flex-1 flex-col gap-5">
            <PickupMixHeader
              canWrite={canWrite}
              game={game}
              gameLoading={gameQuery.isLoading}
              onOpenPool={() => setIsPoolOpen(true)}
              onOpenSettings={() => setIsSettingsOpen(true)}
              onOpenAccess={() => setIsAccessOpen(true)}
              canDelete={canDeleteMix}
              deleting={hardDeleteMix.isPending}
              onDeleteMix={() =>
                hardDeleteMix.mutate(undefined, {
                  onSuccess: () => router.push("/balancer/pickup"),
                })
              }
            />
            <PickupTeamsPanel
              canWrite={canWrite}
              gamesLoading={gamesQuery.isLoading}
              gamesError={gamesQuery.isError}
              onRetryGames={() => void gamesQuery.refetch()}
              game={game}
              gameLoading={gameQuery.isLoading}
              hasMix={selectedGameId != null}
              balancing={balance.isPending}
              activeCount={summarizeLineup(rows).active}
              onBalance={() => balance.mutate()}
              variantIndex={variantIndex}
              onVariantIndexChange={setVariantIndex}
              recordingOutcome={recordOutcome.isPending}
              onRecordOutcome={(input) => recordOutcome.mutate(input)}
              maps={mapsQuery.data ?? []}
              matches={matchesQuery.data ?? []}
              undoingMatchId={undoMatch.isPending ? (undoMatch.variables ?? null) : null}
              onUndoMatch={(matchId) => undoMatch.mutate(matchId)}
              settingNextMap={setNextMap.isPending}
              onNextMapChange={(mapId) => setNextMap.mutate(mapId)}
              closingMix={closeMix.isPending}
              onCloseMix={() => closeMix.mutate()}
              onRenameTeam={(teamIndex, name) => setTeamNames.mutateAsync({ teamIndex, name })}
              onSwapSeats={(idx, firstUuid, secondUuid) =>
                swapSeats.mutateAsync({ variantIndex: idx, firstUuid, secondUuid })
              }
              onCopyBattleTags={copyBattleTags}
              postingToDiscord={postToDiscord.isPending}
              onPostToDiscord={(idx) => postToDiscord.mutate(idx)}
            />
          </div>
        </div>
      </div>

      <PickupAddPlayersDialog
        open={isPoolOpen}
        onOpenChange={setIsPoolOpen}
        workspaceId={workspaceId}
        canEdit={canEdit}
        canEditRanks={canEditRanks}
        canWrite={canWrite}
        hostUserId={game?.host_user_id ?? null}
        rows={rows}
        onTogglePlayer={togglePoolMember}
      />

      <PickupMixConfigDialog
        open={isSettingsOpen}
        onOpenChange={setIsSettingsOpen}
        game={game}
        workspaceId={workspaceId}
        canWrite={canWrite}
        saving={setRoleMask.isPending || setPointsPerWin.isPending || setDiscordChannel.isPending}
        onSave={(input) => {
          setRoleMask.mutate(input.roleMask, { onSuccess: () => setIsSettingsOpen(false) });
          if (input.pointsPerWin !== (game?.settings.points_per_win ?? null)) {
            setPointsPerWin.mutate(input.pointsPerWin);
          }
          if (input.discordChannelId !== (game?.settings.discord_channel_id ?? null)) {
            setDiscordChannel.mutate(input.discordChannelId);
          }
        }}
      />

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
        mixStats={
          statsQuery.data?.members.find(
            (member) => member.workspace_member_id === openRow?.workspace_member_id,
          ) ?? null
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
            setAuthorRanks.mutate({ workspaceMemberId: openRow.workspace_member_id, ...rankChange });
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
}
