"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useInvalidation } from "@/hooks/useInvalidation";
import { notify } from "@/lib/notify";
import {
  customGameKeys,
  customGameService,
  type CustomGame,
  type CustomGamePlayerPatch,
} from "@/services/custom-game.service";
import type { RosterSlotMap } from "@/lib/roster-shape";

import {
  computeRotationHintPatches,
  participationEntries,
  type PickupRecordOutcomeInput,
} from "@/app/balancer/pickup/pickup-lineup";
import {
  workspacePlayerKeys,
  workspacePlayerService,
} from "@/services/workspace-player.service";

export type PickupPlayerPatchInput = {
  workspaceMemberId: number;
  patch: CustomGamePlayerPatch;
};

export type PickupAuthorRanksInput = {
  workspaceMemberId: number;
  /** Roles to write into this host's own book. */
  ranks: Record<string, number>;
  /** Roles to drop from it, falling back to the workspace rank. */
  clear?: string[];
};

export type PickupTeamNameInput = {
  /** 0-based, the same position `TeamColumn` renders by. */
  teamIndex: number;
  name: string;
};

export type PickupSwapSeatsInput = {
  variantIndex: number;
  firstUuid: string;
  secondUuid: string;
};

/**
 * Every read and write for one workspace's mixes, in one place.
 *
 * The mix detail query is the single source of truth for the lineup — every
 * write returns the whole game, so the cache is seeded from the response
 * instead of a refetch, and no panel keeps a private copy of the roster.
 *
 * `pickedGameId` is what the host explicitly chose. The resolved
 * `selectedGameId` is derived rather than synced through an effect: an explicit
 * pick wins while that mix still exists, otherwise the newest mix (the list is
 * id-descending) is shown, which is also how the view recovers when another
 * host cancels the mix being watched.
 */
export function usePickupMix(workspaceId: number, pickedGameId: number | null) {
  const queryClient = useQueryClient();

  const gamesQuery = useQuery({
    queryKey: customGameKeys.list(workspaceId),
    queryFn: () => customGameService.list(workspaceId),
  });

  const games = gamesQuery.data ?? [];
  const selectedGameId =
    pickedGameId != null && games.some((item) => item.id === pickedGameId)
      ? pickedGameId
      : (games[0]?.id ?? null);

  const gameQuery = useQuery({
    queryKey: customGameKeys.one(workspaceId, selectedGameId ?? 0),
    queryFn: () => customGameService.get(workspaceId, selectedGameId as number),
    enabled: selectedGameId != null,
  });

  /** The permanent match history for the selected mix, newest first. */
  const matchesQuery = useQuery({
    queryKey: customGameKeys.matches(workspaceId, selectedGameId ?? 0),
    queryFn: () => customGameService.listMatches(workspaceId, selectedGameId as number),
    enabled: selectedGameId != null,
  });

  /**
   * Who is owed the next seat and who should rest, from this mix's own map
   * history -- feeds a hint into the lineup panel, ahead of `balance` rather
   * than as a separate screen (see `mix_rotation.recommend_rotation`).
   */
  const rotationQuery = useQuery({
    queryKey: customGameKeys.rotation(workspaceId, selectedGameId ?? 0),
    queryFn: () => customGameService.rotation(workspaceId, selectedGameId as number),
    enabled: selectedGameId != null,
  });

  // Another host editing this workspace's mixes (roster, ranks, bench, role
  // order) in a different tab/session: `workspace.pickup_mix` is the only way
  // that becomes visible here without a manual reload.
  useInvalidation({ scopeKind: "workspace", scopeId: workspaceId });

  const applyGame = (game: CustomGame) => {
    queryClient.setQueryData(customGameKeys.one(workspaceId, game.id), game);
    // The list carries name and status, both of which a write can change.
    void queryClient.invalidateQueries({ queryKey: customGameKeys.list(workspaceId) });
    // Roster, participation and match history all feed the rotation verdict --
    // any write here can flip it, so it is invalidated alongside the game
    // itself rather than only on the writes that look rotation-specific.
    void queryClient.invalidateQueries({ queryKey: customGameKeys.rotation(workspaceId, game.id) });
  };

  const createGame = useMutation({
    mutationFn: (name: string) => customGameService.create(workspaceId, name),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  const setRoster = useMutation({
    mutationFn: (playerIds: number[]) =>
      customGameService.updateRoster(workspaceId, selectedGameId as number, playerIds),
    onSuccess: async (game) => {
      applyGame(game);
      // Adding somebody new seeds their effective rank into this host's own
      // book (server-side `_seed_host_ranks`), so the add-players dialog's
      // "My ranks" list and chip count go stale without this.
      await queryClient.invalidateQueries({ queryKey: workspacePlayerKeys.all(workspaceId) });
    },
    onError: (error) => notify.apiError(error),
  });

  const patchPlayer = useMutation({
    mutationFn: (input: PickupPlayerPatchInput) =>
      customGameService.updatePlayer(workspaceId, selectedGameId as number, input.workspaceMemberId, input.patch),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  /**
   * Applies every actionable rotation-fairness hint at once (see
   * `mix_rotation.recommend_rotation`): seats whoever is owed one, benches
   * whoever should rest. One request, one transaction, one returned snapshot --
   * `computeRotationHintPatches` already skips a row that matches its hint, so
   * a second click with nothing left to apply never reaches the server.
   */
  const applyRotationHints = useMutation({
    mutationFn: async () => {
      const players = participationEntries(
        computeRotationHintPatches(gameQuery.data?.players ?? [], rotationQuery.data ?? []),
      );
      if (players.length === 0) {
        return { appliedCount: 0, game: null };
      }
      const game = await customGameService.setParticipation(
        workspaceId,
        selectedGameId as number,
        players,
      );
      return { appliedCount: players.length, game };
    },
    onSuccess: ({ appliedCount, game }) => {
      if (game != null) {
        applyGame(game);
      }
      notify.success(
        appliedCount > 0
          ? `Applied ${appliedCount} hint${appliedCount === 1 ? "" : "s"}`
          : "Lineup already matches the hints",
      );
    },
    onError: (error) => notify.apiError(error),
  });

  const setTeamNames = useMutation({
    mutationFn: (input: PickupTeamNameInput) =>
      customGameService.setTeamNames(workspaceId, selectedGameId as number, {
        [String(input.teamIndex)]: input.name,
      }),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  const setRoleMask = useMutation({
    mutationFn: (roleMask: RosterSlotMap | null) =>
      customGameService.setRoleMask(workspaceId, selectedGameId as number, roleMask),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  const setPointsPerWin = useMutation({
    mutationFn: (pointsPerWin: number | null) =>
      customGameService.setPointsPerWin(workspaceId, selectedGameId as number, pointsPerWin),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  const transferHost = useMutation({
    mutationFn: (newHostUserId: number) =>
      customGameService.transferHost(workspaceId, selectedGameId as number, newHostUserId),
    onSuccess: (game) => {
      applyGame(game);
      notify.success("Host transferred");
    },
    onError: (error) => notify.apiError(error),
  });

  const addCoHost = useMutation({
    mutationFn: (coHostUserId: number) =>
      customGameService.addCoHost(workspaceId, selectedGameId as number, coHostUserId),
    onSuccess: (game) => {
      applyGame(game);
      notify.success("Co-host added");
    },
    onError: (error) => notify.apiError(error),
  });

  const removeCoHost = useMutation({
    mutationFn: (coHostUserId: number) =>
      customGameService.removeCoHost(workspaceId, selectedGameId as number, coHostUserId),
    onSuccess: (game) => {
      applyGame(game);
      notify.success("Co-host removed");
    },
    onError: (error) => notify.apiError(error),
  });

  const swapSeats = useMutation({
    mutationFn: (input: PickupSwapSeatsInput) =>
      customGameService.swapSeats(
        workspaceId,
        selectedGameId as number,
        input.variantIndex,
        input.firstUuid,
        input.secondUuid,
      ),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  const balance = useMutation({
    mutationFn: () => customGameService.balance(workspaceId, selectedGameId as number),
    onSuccess: (game) => {
      applyGame(game);
      notify.success("Teams balanced");
    },
    onError: (error) => notify.apiError(error),
  });

  const recordOutcome = useMutation({
    mutationFn: (input: PickupRecordOutcomeInput) =>
      customGameService.recordOutcome(
        workspaceId,
        selectedGameId as number,
        input.outcome,
        input.variantIndex,
        input.mapId,
      ),
    onSuccess: (game) => {
      applyGame(game);
      notify.success("Result recorded");
    },
    onError: (error) => notify.apiError(error),
  });

  const closeMix = useMutation({
    mutationFn: () => customGameService.close(workspaceId, selectedGameId as number),
    onSuccess: (game) => {
      applyGame(game);
      notify.success("Mix closed");
    },
    onError: (error) => notify.apiError(error),
  });

  /** Irreversible: removes the game row and every match it recorded. */
  const hardDeleteMix = useMutation({
    mutationFn: () => customGameService.hardDelete(workspaceId, selectedGameId as number),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: customGameKeys.one(workspaceId, selectedGameId ?? 0) });
      await queryClient.invalidateQueries({ queryKey: customGameKeys.list(workspaceId) });
      notify.success("Mix deleted");
    },
    onError: (error) => notify.apiError(error),
  });

  /**
   * The host's own rank book. Unlike every other write here it does not return
   * the game, so the mix detail is refetched: the book feeds rank resolution,
   * which decides the effective rank of every roster row.
   *
   * `scope: "author"` is not a parameter the caller may vary — the endpoint
   * takes no author id, so this can only ever write the caller's own book.
   */
  const setAuthorRanks = useMutation({
    mutationFn: (input: PickupAuthorRanksInput) =>
      workspacePlayerService.setRanks(workspaceId, input.workspaceMemberId, {
        scope: "author",
        ranks: input.ranks,
        clear: input.clear ?? [],
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: customGameKeys.all(workspaceId) });
      // The roster sidebar shows the same two layers this write changes one of.
      await queryClient.invalidateQueries({ queryKey: workspacePlayerKeys.all(workspaceId) });
    },
    onError: (error) => notify.apiError(error),
  });

  return {
    selectedGameId,
    gamesQuery,
    gameQuery,
    matchesQuery,
    rotationQuery,
    createGame,
    setRoster,
    patchPlayer,
    applyRotationHints,
    balance,
    recordOutcome,
    closeMix,
    hardDeleteMix,
    setAuthorRanks,
    setTeamNames,
    setRoleMask,
    setPointsPerWin,
    transferHost,
    addCoHost,
    removeCoHost,
    swapSeats,
  };
}
