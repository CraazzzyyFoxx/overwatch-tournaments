"use client";

import { useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { useInvalidation } from "@/hooks/useInvalidation";
import { notify } from "@/lib/notify";
import type { RoleRef } from "@/lib/roster/role-ref";
import {
  customGameKeys,
  customGameService,
  type CustomGame,
  type CustomGamePlayerPatch,
  type HeroRoomPatch,
  type MixSelfSignup,
  type MixSelfState,
  type MixTeamFormation,
  type MixVoicePatch,
} from "@/services/custom-game.service";

import { OPEN_MIXES } from "@/app/balancer/mix/pickup-chrome";
import {
  computeRotationHintPatches,
  participationEntries,
  waitingQueuePosition,
  type PickupRecordOutcomeInput,
} from "@/app/balancer/mix/pickup-lineup";
import { voiceRefusal } from "@/app/balancer/mix/pickup-voice";
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
  /** The mix's own discipline, captured at submit: the book is written for that game, never the workspace default. */
  discipline: string;
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
  lobbyIndex: number;
  variantIndex: number;
  firstUuid: string;
  secondUuid: string;
};

/** Which lobby a balance run covers: one of them, or the whole pool split across all of them. */
export type PickupBalanceInput = { scope: "lobby"; lobbyIndex: number } | { scope: "all" };

/** The two fields a player owns on their own row. `roles: null` is `all_ranked`. */
export type PickupMySeatInput = { roles: RoleRef[] | null; is_flex: boolean };


/**
 * Every read and write for one workspace's mixes, in one place.
 *
 * The mix detail query is the single source of truth for the lineup — every
 * write returns the whole game, so the cache is seeded from the response
 * instead of a refetch, and no panel keeps a private copy of the roster.
 *
 * The route's explicit game stays selected even if it was deleted or is absent
 * from the workspace list: show its real read error, never a different mix.
 */
export function usePickupMix(
  workspaceId: number,
  pickedGameId: number | null,
  options: { seatEnabled?: boolean; voiceEnabled?: boolean; initialGame?: CustomGame; initialLobby?: number } = {},
) {
  const queryClient = useQueryClient();
  const tVoiceError = useTranslations("mixes.voice.errors");
  const tRoom = useTranslations("mixes.room");
  const tDraft = useTranslations("mixes.draft");
  const tToast = useTranslations("mixes.toast");

  // Every open mix of the workspace, whatever its game: the voice panel names the channels this workspace's OTHER
  // open mixes already took, and voice channels are shared across games. The same page the directory's "now" block
  // reads, so the two share one cache entry.
  const gamesQuery = useQuery({
    queryKey: customGameKeys.list(workspaceId, null, OPEN_MIXES),
    queryFn: ({ signal }) => customGameService.list(workspaceId, null, OPEN_MIXES, { signal }),
    select: (page) => page.items,
  });

  const selectedGameId = pickedGameId;

  const gameQuery = useQuery({
    queryKey: customGameKeys.one(workspaceId, selectedGameId ?? 0),
    queryFn: () => customGameService.getById(selectedGameId as number, workspaceId),
    initialData: options.initialGame,
    enabled: selectedGameId != null,
  });

  /** The permanent match history for the selected mix, newest first. */
  const matchesQuery = useQuery({
    queryKey: customGameKeys.matches(workspaceId, selectedGameId ?? 0),
    queryFn: () => customGameService.listMatches(workspaceId, selectedGameId as number),
    enabled: selectedGameId != null,
  });

  // The lobby on screen. Page state, not server state: two co-hosts may well be
  // watching different lobbies of the same mix. A room opens on its own lobby.
  const [activeLobby, setActiveLobby] = useState(options.initialLobby ?? 0);
  const lobbyCount = gameQuery.data?.lobby_count;
  // Dropping lobbies while a later one is open would leave the page pointing at
  // a lobby the mix no longer has. Reset during render, React's own pattern for
  // state derived from a prop that must follow it -- and only against a loaded
  // mix: until the detail arrives a room's requested lobby is kept.
  if (lobbyCount != null && activeLobby >= lobbyCount) {
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

  // The caller's place in the mix-wide waiting line. Each lobby's rotation leaves out whoever is pinned to another
  // lobby, so the line reads every lobby's -- only while the caller waits, at most six reads. The history is the
  // whole mix's, so a member two lobbies both rank carries the same numbers in each.
  const mySeat = mySeatQuery.data?.seat ?? null;
  const waiting =
    mySeat != null && !mySeat.away && mySeat.participation !== "benched" && mySeat.current_lobby == null;
  const queueRotations = useQueries({
    queries: Array.from({ length: waiting ? (lobbyCount ?? 0) : 0 }, (_, lobbyIndex) => ({
      queryKey: customGameKeys.rotation(workspaceId, selectedGameId ?? 0, lobbyIndex),
      queryFn: () => customGameService.rotation(workspaceId, selectedGameId as number, lobbyIndex),
      enabled: selectedGameId != null,
    })),
  });
  // No number until every lobby has answered: a partial line would rank a player pinned elsewhere as a newcomer.
  const myQueuePosition =
    mySeat == null || queueRotations.length === 0 || queueRotations.some((query) => query.data == null)
      ? null
      : waitingQueuePosition(
          gameQuery.data?.players ?? [],
          queueRotations.flatMap((query) => query.data ?? []),
          mySeat.workspace_member_id,
        );

  /**
   * The voices this mix may pick, listed from Discord through the workspace's
   * category. A writer's read only -- the endpoint 403s anyone else, and a
   * viewer has nothing to pick. Cached for a minute: a Discord channel list
   * does not move between two clicks of the same panel.
   */
  const voiceOptionsQuery = useQuery({
    queryKey: customGameKeys.voiceOptions(workspaceId, selectedGameId ?? 0),
    queryFn: () => customGameService.voiceOptions(workspaceId, selectedGameId as number),
    enabled: selectedGameId != null && options.voiceEnabled === true,
    staleTime: 60_000,
  });

  // Another host editing this workspace's mixes (roster, ranks, bench, role
  // order) in a different tab/session: `workspace.pickup_mix` is the only way
  // that becomes visible here without a manual reload.
  useInvalidation({ scopeKind: "workspace", scopeId: workspaceId });

  const applyGame = (game: CustomGame) => {
    queryClient.setQueryData(customGameKeys.one(workspaceId, game.id), game);
    // The directory lists carry name and status, both of which a write can change. `lists` is not a prefix of
    // any mix's own reads, so this never refetches the detail just seeded above -- the heaviest payload the mix
    // API has. Everything else follows on the realtime echo.
    void queryClient.invalidateQueries({ queryKey: customGameKeys.lists(workspaceId) });
    // Roster, participation and match history all feed the rotation verdict --
    // any write here can flip it, so it is invalidated alongside the game
    // itself rather than only on the writes that look rotation-specific. The
    // history is refetched for the same reason: recording and undoing both
    // rewrite it, and until now that only landed through the realtime echo.
    void queryClient.invalidateQueries({ queryKey: customGameKeys.rotationAll(workspaceId, game.id) });
    void queryClient.invalidateQueries({ queryKey: customGameKeys.matches(workspaceId, game.id) });
  };


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
      notify.success(appliedCount > 0 ? tToast("hintsApplied", { count: appliedCount }) : tToast("hintsMatch"));
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
   * Hands the matchup to the bot for the mix's Discord channel; the server
   * draws its picture. Nothing about the mix changes, so no cache is touched
   * -- the only feedback is that the message was queued.
   */
  const postToDiscord = useMutation({
    mutationFn: ({ lobbyIndex, variantIndex }: { lobbyIndex: number; variantIndex: number }) =>
      customGameService.postToDiscord(workspaceId, selectedGameId as number, lobbyIndex, variantIndex),
    onSuccess: () => notify.success(tToast("sentToDiscord")),
    onError: (error) => notify.apiError(error),
  });

  const transferHost = useMutation({
    mutationFn: (newHostUserId: number) =>
      customGameService.transferHost(workspaceId, selectedGameId as number, newHostUserId),
    onSuccess: (game) => {
      applyGame(game);
      notify.success(tToast("hostTransferred"));
    },
    onError: (error) => notify.apiError(error),
  });

  const addCoHost = useMutation({
    mutationFn: (coHostUserId: number) =>
      customGameService.addCoHost(workspaceId, selectedGameId as number, coHostUserId),
    onSuccess: (game) => {
      applyGame(game);
      notify.success(tToast("coHostAdded"));
    },
    onError: (error) => notify.apiError(error),
  });

  const removeCoHost = useMutation({
    mutationFn: (coHostUserId: number) =>
      customGameService.removeCoHost(workspaceId, selectedGameId as number, coHostUserId),
    onSuccess: (game) => {
      applyGame(game);
      notify.success(tToast("coHostRemoved"));
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
      notify.success(tToast("balanced"));
    },
    onError: (error) => notify.apiError(error),
  });

  const recordOutcome = useMutation({
    mutationFn: (input: PickupRecordOutcomeInput) =>
      customGameService.recordOutcome(workspaceId, selectedGameId as number, input.lobbyIndex, input.outcome),
    onSuccess: (game) => {
      applyGame(game);
      notify.success(tToast("resultRecorded"));
    },
    onError: (error) => notify.apiError(error),
  });

  /** Opens the lobby's match on the lineup it shows; the server splits the team voices when it has them. */
  const startMatch = useMutation({
    mutationFn: ({ lobbyIndex, flipOpener }: { lobbyIndex: number; flipOpener: boolean }) =>
      customGameService.startMatch(workspaceId, selectedGameId as number, lobbyIndex, flipOpener),
    onSuccess: (game) => {
      applyGame(game);
      notify.success(tRoom("started"));
    },
    onError: (error) => notify.apiError(error),
  });

  /** Throws the lobby's live match away; the lineup is ready to start again. */
  const cancelMatch = useMutation({
    mutationFn: (lobbyIndex: number) => customGameService.cancelMatch(workspaceId, selectedGameId as number, lobbyIndex),
    onSuccess: (game) => {
      applyGame(game);
      notify.success(tRoom("cancelled"));
    },
    onError: (error) => notify.apiError(error),
  });

  /** "Make captain" on a seat of the lobby's shown option. */
  const setCaptain = useMutation({
    mutationFn: ({ lobbyIndex, workspaceMemberId }: { lobbyIndex: number; workspaceMemberId: number }) =>
      customGameService.setCaptain(workspaceId, selectedGameId as number, lobbyIndex, workspaceMemberId),
    onSuccess: applyGame,
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
      notify.success(tToast("matchUndone"));
    },
    onError: (error) => notify.apiError(error),
  });

  /** The map this lobby's next match is on -- rolled or picked; `null` clears it. */
  const setNextMap = useMutation({
    mutationFn: ({ lobbyIndex, mapId }: { lobbyIndex: number; mapId: number | null }) =>
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
    mutationFn: ({ lobbyIndex, variantIndex }: { lobbyIndex: number; variantIndex: number }) =>
      customGameService.setVariantIndex(
        workspaceId,
        selectedGameId as number,
        lobbyIndex,
        variantIndex,
      ),
    onMutate: ({ lobbyIndex, variantIndex }: { lobbyIndex: number; variantIndex: number }) => {
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
   * How many lobbies this mix runs. Dropping lobbies throws their balances away
   * and clears the pins onto them server-side, so the whole game is re-seeded
   * from the response.
   */
  const setLobbyCount = useMutation({
    mutationFn: (count: number) =>
      customGameService.setLobbyCount(workspaceId, selectedGameId as number, count),
    onSuccess: (game) => {
      applyGame(game);
      notify.success(tToast("lobbyCount", { count: game.lobby_count }));
    },
    onError: (error) => notify.apiError(error),
  });

  const closeMix = useMutation({
    mutationFn: () => customGameService.close(workspaceId, selectedGameId as number),
    onSuccess: (game) => {
      applyGame(game);
      notify.success(tToast("mixClosed"));
    },
    onError: (error) => notify.apiError(error),
  });

  /** Irreversible: removes the game row and every match it recorded. */
  const hardDeleteMix = useMutation({
    mutationFn: () => customGameService.hardDelete(workspaceId, selectedGameId as number),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: customGameKeys.one(workspaceId, selectedGameId ?? 0) });
      await queryClient.invalidateQueries({ queryKey: customGameKeys.lists(workspaceId) });
      notify.success(tToast("mixDeleted"));
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
        discipline: input.discipline,
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
    void queryClient.invalidateQueries({ queryKey: customGameKeys.lists(workspaceId) });
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

  /** The caller's own away switch: answers with their seat, and moves the board every viewer reads. */
  const setMyAway = useMutation({
    mutationFn: (away: boolean) => customGameService.setMyAway(workspaceId, selectedGameId as number, away),
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

  /** The mix's hero room (preset, Fearless, clocks). Returns the game, so the board is seeded like any host write. */
  const setBanPreset = useMutation({
    mutationFn: (patch: HeroRoomPatch) =>
      customGameService.setBanPreset(workspaceId, selectedGameId as number, patch),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  /** The mix's team formation and pick clock. Returns the game, like every host write. */
  const setDraftSettings = useMutation({
    mutationFn: (settings: { team_formation: MixTeamFormation; draft_pick_seconds: number }) =>
      customGameService.setDraftSettings(workspaceId, selectedGameId as number, settings),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  /** Draft: the lobby re-formed as a captain draft (spec §9.2). The variables are the lobby, so only its card spins. */
  const seedDraft = useMutation({
    mutationFn: (lobbyIndex: number) => customGameService.seedDraft(workspaceId, selectedGameId as number, lobbyIndex),
    onSuccess: (game) => {
      applyGame(game);
      notify.success(tDraft("seeded"));
    },
    onError: (error) => notify.apiError(error),
  });

  const splitPool = useMutation({
    mutationFn: () => customGameService.splitPool(workspaceId, selectedGameId as number),
    onSuccess: (game) => {
      applyGame(game);
      notify.success(tDraft("seeded"));
    },
    onError: (error) => notify.apiError(error),
  });

  const replaceDraftCaptain = useMutation({
    mutationFn: (input: { lobbyIndex: number; teamId: number; playerId: number }) =>
      customGameService.replaceDraftCaptain(
        workspaceId,
        selectedGameId as number,
        input.lobbyIndex,
        input.teamId,
        input.playerId,
      ),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  const addDraftPlayer = useMutation({
    mutationFn: (input: { lobbyIndex: number; workspaceMemberId: number }) =>
      customGameService.addDraftPlayer(workspaceId, selectedGameId as number, input.lobbyIndex, input.workspaceMemberId),
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
      notify.success(tToast("signupPosted"));
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
      notify.success(tToast("postRemoving"));
    },
    onError: (error) => notify.apiError(error),
  });

  /**
   * The four refusals a move or a return answers with are setup problems with a
   * sentence of their own (`mixes.voice.errors.*`); everything else is an
   * ordinary failure and reads as one.
   */
  const notifyVoiceError = (error: unknown) => {
    const refusal = voiceRefusal(error);
    if (refusal) {
      notify.error(tVoiceError(refusal));
      return;
    }
    notify.apiError(error);
  };

  /** The mix's whole voice setup at once -- the endpoint replaces it, not patches it. */
  const setVoiceChannels = useMutation({
    mutationFn: (patch: MixVoicePatch) =>
      customGameService.setVoiceChannels(workspaceId, selectedGameId as number, patch),
    onSuccess: applyGame,
    onError: (error) => notify.apiError(error),
  });

  /** Players into their team voices: one lobby, or every lobby for `null`. */
  const voiceMove = useMutation({
    mutationFn: (lobbyIndex: number | null) =>
      customGameService.voiceMove(workspaceId, selectedGameId as number, lobbyIndex),
    onError: notifyVoiceError,
  });

  /** And back into the general voice. The report is read off `.data` by the panel. */
  const voiceReturn = useMutation({
    mutationFn: (lobbyIndex: number | null) =>
      customGameService.voiceReturn(workspaceId, selectedGameId as number, lobbyIndex),
    onError: notifyVoiceError,
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
    myQueuePosition,
    voiceOptionsQuery,
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
    replaceDraftCaptain,
    addDraftPlayer,
    postSignup,
    deleteDiscordPost,
    setVoiceChannels,
    voiceMove,
    voiceReturn,
  };
}
