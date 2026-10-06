"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useInvalidation } from "@/hooks/useInvalidation";
import { notify } from "@/lib/notify";
import type { RoleCode } from "@/lib/roster/roles";
import {
  customGameKeys,
  customGameService,
  type CustomGame,
  type CustomGamePlayerPatch,
  type MixSelfSignup,
  type MixSelfState,
} from "@/services/custom-game.service";

import {
  computeRotationHintPatches,
  participationEntries,
  type PickupRecordOutcomeInput,
} from "@/app/balancer/mix/pickup-lineup";
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
  lobbyIndex: 0 | 1;
  variantIndex: number;
  firstUuid: string;
  secondUuid: string;
};

/** Which lobby a balance run covers: one of them, or the whole pool split across both. */
export type PickupBalanceInput = { scope: "lobby"; lobbyIndex: 0 | 1 } | { scope: "all" };

/** The two fields a player owns on their own row. `roles: null` is `all_ranked`. */
export type PickupMySeatInput = { roles: RoleCode[] | null; is_flex: boolean };

export type PickupCreateGameInput = {
  name: string;
  /** Copy a previous mix's lineup and settings, or `null` to start empty. */
  cloneFromGameId: number | null;
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
export function usePickupMix(
  workspaceId: number,
  pickedGameId: number | null,
  options: { seatEnabled?: boolean } = {},
) {
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

  // The lobby on screen. Page state, not server state: two co-hosts may well be
  // watching different lobbies of the same mix.
  const [activeLobby, setActiveLobby] = useState<0 | 1>(0);
  const lobbyCount = gameQuery.data?.lobby_count ?? 1;
  // Dropping to one lobby while B is open would leave the page pointing at a
  // lobby the mix no longer has. Reset during render, React's own pattern for
  // state derived from a prop that must follow it.
  if (activeLobby >= lobbyCount) {
    setActiveLobby(0);
  }

  /**
   * Who is owed the next seat in the open lobby and who should rest, from this
   * mix's own map history -- feeds a hint into the lineup panel, ahead of
   * `balance` rather than as a separate screen (see
   * `mix_rotation.recommend_rotation`). Keyed by lobby: the candidates of lobby
   * A are not the candidates of lobby B.
   */
  const rotationQuery = useQuery({
    queryKey: customGameKeys.rotation(workspaceId, selectedGameId ?? 0, activeLobby),
    queryFn: () => customGameService.rotation(workspaceId, selectedGameId as number, activeLobby),
    enabled: selectedGameId != null,
  });

  /**
   * The caller's own standing in this mix. A separate read from the board on
   * purpose: the board is public and identical for every viewer, this answer is
   * about the caller. Off for a signed-out visitor -- the endpoint requires
   * auth and the panel has nothing to show them.
   */
  const mySeatQuery = useQuery({
    queryKey: customGameKeys.me(workspaceId, selectedGameId ?? 0),
    queryFn: () => customGameService.getMySeat(workspaceId, selectedGameId as number),
    enabled: selectedGameId != null && options.seatEnabled === true,
  });

  // Another host editing this workspace's mixes (roster, ranks, bench, role
  // order) in a different tab/session: `workspace.pickup_mix` is the only way
  // that becomes visible here without a manual reload.
  useInvalidation({ scopeKind: "workspace", scopeId: workspaceId });

  const applyGame = (game: CustomGame) => {
    queryClient.setQueryData(customGameKeys.one(workspaceId, game.id), game);
    // The list carries name and status, both of which a write can change.
    // `exact`: the list key is a prefix of every mix key, so a bare invalidate
    // would also refetch the detail just seeded above -- the heaviest payload
    // the mix API has. Everything else follows on the realtime echo.
    void queryClient.invalidateQueries({ queryKey: customGameKeys.list(workspaceId), exact: true });
    // Roster, participation and match history all feed the rotation verdict --
    // any write here can flip it, so it is invalidated alongside the game
    // itself rather than only on the writes that look rotation-specific. The
    // history is refetched for the same reason: recording and undoing both
    // rewrite it, and until now that only landed through the realtime echo.
    void queryClient.invalidateQueries({ queryKey: customGameKeys.rotationAll(workspaceId, game.id) });
    void queryClient.invalidateQueries({ queryKey: customGameKeys.matches(workspaceId, game.id) });
  };

  const createGame = useMutation({
    mutationFn: (input: PickupCreateGameInput) =>
      customGameService.create(workspaceId, input.name, input.cloneFromGameId),
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

  const renameMix = useMutation({
    mutationFn: (name: string) => customGameService.rename(workspaceId, selectedGameId as number, name),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  /**
   * Hands the matchup to the bot for the mix's Discord channel, as the PNG the
   * caller rasterised from the matchup card. Nothing about the mix changes, so
   * no cache is touched -- the only feedback is that the message was queued.
   */
  const postToDiscord = useMutation({
    mutationFn: ({
      lobbyIndex,
      variantIndex,
      image,
    }: {
      lobbyIndex: 0 | 1;
      variantIndex: number;
      image: Blob | null;
    }) =>
      customGameService.postToDiscord(
        workspaceId,
        selectedGameId as number,
        lobbyIndex,
        variantIndex,
        image,
      ),
    onSuccess: () => notify.success("Sent to Discord"),
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
        input.lobbyIndex,
        input.variantIndex,
        input.firstUuid,
        input.secondUuid,
      ),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  const balance = useMutation({
    mutationFn: (input: PickupBalanceInput) =>
      customGameService.balance(workspaceId, selectedGameId as number, input),
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
        input.lobbyIndex,
        input.outcome,
        input.variantIndex,
      ),
    onSuccess: (game) => {
      applyGame(game);
      notify.success("Result recorded");
    },
    onError: (error) => notify.apiError(error),
  });

  /**
   * Takes the newest recorded match back out -- the correction for a
   * mis-clicked scoreline. Rank points move back by what that match applied,
   * and only the newest one can go.
   */
  const undoMatch = useMutation({
    mutationFn: (matchId: number) =>
      customGameService.undoMatch(workspaceId, selectedGameId as number, matchId),
    onSuccess: (game) => {
      applyGame(game);
      notify.success("Match undone");
    },
    onError: (error) => notify.apiError(error),
  });

  /** The map this lobby's next match is on -- rolled or picked; `null` clears it. */
  const setNextMap = useMutation({
    mutationFn: ({ lobbyIndex, mapId }: { lobbyIndex: 0 | 1; mapId: number | null }) =>
      customGameService.setNextMap(workspaceId, selectedGameId as number, lobbyIndex, mapId),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  /**
   * Which balance option the mix shows -- stored on the mix, so a viewer reads
   * the matchup the host is calling out instead of whatever their own browser
   * last paged to.
   *
   * Optimistic, and deliberately not routed through `applyGame`: this changes
   * nothing about roster, history or rotation, and a pager clicked through
   * twenty options must not refetch three queries per click or lag a round
   * trip behind the arrow keys.
   */
  const setVariantIndex = useMutation({
    mutationFn: ({ lobbyIndex, variantIndex }: { lobbyIndex: 0 | 1; variantIndex: number }) =>
      customGameService.setVariantIndex(
        workspaceId,
        selectedGameId as number,
        lobbyIndex,
        variantIndex,
      ),
    onMutate: ({ lobbyIndex, variantIndex }: { lobbyIndex: 0 | 1; variantIndex: number }) => {
      const key = customGameKeys.one(workspaceId, selectedGameId ?? 0);
      const previous = queryClient.getQueryData<CustomGame>(key);
      if (previous != null) {
        queryClient.setQueryData(key, {
          ...previous,
          lobbies: previous.lobbies.map((row) =>
            row.lobby_index === lobbyIndex ? { ...row, selected_variant_index: variantIndex } : row,
          ),
        });
      }
      return { previous };
    },
    onSuccess: (game) => queryClient.setQueryData(customGameKeys.one(workspaceId, game.id), game),
    onError: (error, _input, context) => {
      if (context?.previous != null) {
        queryClient.setQueryData(customGameKeys.one(workspaceId, selectedGameId ?? 0), context.previous);
      }
      notify.apiError(error);
    },
  });

  /**
   * How many lobbies this mix runs. Going back to one drops lobby B's balance
   * and every pin server-side, so the whole game is re-seeded from the response.
   */
  const setLobbyCount = useMutation({
    mutationFn: (count: 1 | 2) =>
      customGameService.setLobbyCount(workspaceId, selectedGameId as number, count),
    onSuccess: (game) => {
      applyGame(game);
      notify.success(game.lobby_count === 2 ? "Second lobby opened" : "Back to one lobby");
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

  /**
   * A self-write answers with the caller's state, not with the game, so the
   * seat is seeded from the response and the board is invalidated instead:
   * joining and leaving move the roster every viewer reads.
   */
  const applySeat = (state: MixSelfState) => {
    queryClient.setQueryData(customGameKeys.me(workspaceId, state.custom_game_id), state);
    void queryClient.invalidateQueries({
      queryKey: customGameKeys.one(workspaceId, state.custom_game_id),
    });
    void queryClient.invalidateQueries({ queryKey: customGameKeys.list(workspaceId), exact: true });
    void queryClient.invalidateQueries({
      queryKey: customGameKeys.rotationAll(workspaceId, state.custom_game_id),
    });
  };

  const joinMix = useMutation({
    mutationFn: () => customGameService.joinMix(workspaceId, selectedGameId as number),
    onSuccess: applySeat,
    onError: (error) => notify.apiError(error),
  });

  const leaveMix = useMutation({
    mutationFn: () => customGameService.leaveMix(workspaceId, selectedGameId as number),
    onSuccess: applySeat,
    onError: (error) => notify.apiError(error),
  });

  const updateMySeat = useMutation({
    mutationFn: (input: PickupMySeatInput) =>
      customGameService.updateMySeat(workspaceId, selectedGameId as number, input),
    // Every toggle writes, so success is silent: the cards already show it.
    onSuccess: applySeat,
    onError: (error) => notify.apiError(error),
  });

  /** The host's switches. Returns the game, so the board is seeded like any other host write. */
  const setSelfService = useMutation({
    mutationFn: (patch: { self_signup?: MixSelfSignup; self_role_edit?: boolean }) =>
      customGameService.setSelfService(workspaceId, selectedGameId as number, patch),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  /**
   * Opens signup and hands the card to the bot. The mix's own `self_signup`
   * moves server-side, so the board is refetched; the message itself is
   * fire-and-forget, exactly like `postToDiscord`.
   */
  const postSignup = useMutation({
    mutationFn: (selfSignup: "pool" | "benched") =>
      customGameService.postSignup(workspaceId, selectedGameId as number, selfSignup),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: customGameKeys.one(workspaceId, selectedGameId ?? 0),
      });
      notify.success("Signup opened in Discord");
    },
    onError: (error) => notify.apiError(error),
  });

  /**
   * Deletes one of the mix's Discord posts. The server answers with the mix,
   * the post already `deleting`; the bot removes the message asynchronously
   * and the realtime refetch then drops the row.
   */
  const deleteDiscordPost = useMutation({
    mutationFn: (postId: number) =>
      customGameService.deleteDiscordPost(workspaceId, selectedGameId as number, postId),
    onSuccess: (game) => {
      applyGame(game);
      notify.success("Removing the post from Discord");
    },
    onError: (error) => notify.apiError(error),
  });

  return {
    selectedGameId,
    activeLobby,
    setActiveLobby,
    gamesQuery,
    gameQuery,
    matchesQuery,
    rotationQuery,
    mySeatQuery,
    createGame,
    setRoster,
    patchPlayer,
    applyRotationHints,
    balance,
    recordOutcome,
    undoMatch,
    setNextMap,
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
    setSelfService,
    postSignup,
    deleteDiscordPost,
  };
}
