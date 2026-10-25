"use client";

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import pickBanService, {
  type PickBanActionInput,
  type PickBanSubmitInput
} from "@/services/pickBan.service";
import type {
  PickBanAction,
  PickBanKind,
  PickBanResolvedStep,
  PickBanState,
  PickBanSubmissionItem,
  PickBanTarget
} from "@/types/tournament.types";

import {
  DRAFT_SAVE_DELAY_MS,
  eligibleItemIds,
  isSessionActive,
  lastRevealedBlindStep,
  memberChoice,
  memberName,
  pickBanSeats,
  seatName,
  viewerSubmission,
  type PickBanSeat
} from "./pick-ban-model";
import type { PickBanItemLike } from "./PickBanGrid";
import { useSideLabel } from "./useSideLabel";

/**
 * What the board lends the room's admin panel: the tile the organizer has
 * selected here, and the cleanup only this board can do (its selection and
 * its unsaved draft are local state).
 */
export interface PickBanAdminSlot {
  kind: PickBanKind;
  selectedItemId: number | null;
  selectedItemName: string | null;
  /**
   * The blind draft being built out of THIS pool for an absent captain, or
   * null when no blind step is open to an organizer. The board owns the tile
   * clicks that fill it; the panel owns whose draft it is and when it is sent.
   */
  blind: {
    items: PickBanSubmissionItem[];
    /** The opponent player the next tile click lands on, on a targeted step. */
    targetPlayerId: number | null;
    setTargetPlayerId: (playerId: number | null) => void;
    removeAt: (index: number) => void;
    /** Drop the whole draft — the panel does this when the side changes. */
    clear: () => void;
  } | null;
  onMutated: () => void;
}

/** What the board reads off its room: the game, its two seats. A mix room has no Encounter read (D77). */
export type PickBanBoardEncounter = { workspace_id: number; discipline: string; teams: readonly PickBanSeat[] };

/** One board's decisions and writes, whatever its layout (see {@link usePickBanController}). */
export interface PickBanController {
  step: PickBanResolvedStep | null;
  /** The room's participations in slot order. */
  seats: PickBanSeat[];
  viewerTeamId: number | null;
  opponentTeamId: number | null;
  /** The open step is answered for one player (a mix's member pick). */
  memberStep: boolean;
  /** The open step maps a team's picked heroes to its players. */
  assignStep: boolean;
  /** Whom this viewer may pick for on a member step, themselves first. */
  choosableMembers: number[];
  actingMemberId: number | null;
  /** The player a member step picks for, by name; null on a team step. */
  actingMemberName: string | null;
  selectedItemId: number | null;
  selectedItemName: string | null;
  selectedTargetId: number | null;
  setSelectedTargetId: Dispatch<SetStateAction<number | null>>;
  isSideStep: boolean;
  /** The side index chosen on a side step; null until one is. */
  selectedSide: number | null;
  chooseSide: (index: number | null) => void;
  sideLabel: (code: string) => string;
  sideLabels: string[];
  isBlindStep: boolean;
  /** The viewer's own pending action on an open step; null on a blind step and for a spectator. */
  captainAction: PickBanAction | null;
  /** A host fills a blind draft for an absent captain. */
  adminDrafting: boolean;
  canSelect: boolean;
  draftItems: PickBanSubmissionItem[];
  draftItemIds: ReadonlySet<number>;
  draftLocked: boolean;
  draftDirty: boolean;
  eligibleIds: Set<number> | null;
  assignedByPlayer: Record<number, number | undefined>;
  targetRoster: PickBanTarget[];
  targetName: (playerId: number) => string | null;
  teamName: (teamId: number) => string;
  /** A pool tile clicked: edits a blind draft, else selects the tile. */
  selectTile: (itemId: number) => void;
  /** Answers the open step with the item (or side index) chosen. */
  confirm: (itemId: number) => void;
  cancelSelection: () => void;
  removeDraftAt: (index: number) => void;
  lockDraft: () => void;
  /** What the board lends a host's admin panel. */
  adminSlot: PickBanAdminSlot;
  revealedStep: PickBanResolvedStep | null;
  showElectOpener: boolean;
  pendingOpenerTeamId: number | null;
  /** An act or a host's pick for a seat is in flight. */
  acting: boolean;
  locking: boolean;
  dispute: { pending: boolean; run: () => void };
}

/**
 * Everything a pick-ban board decides that is not layout: which step is open and for whom, the viewer's selection,
 * their blind draft (debounced autosave, then the lock), the side a side step chose, and the writes that answer the
 * step. The tournament pregame board and the mix room lay it out differently; this is the one copy of the rules both
 * obey. The player a member step picks for is the caller's (`chosenMember`): the mix room chooses it on its rosters.
 */
export function usePickBanController({
  kind,
  encounterId,
  encounter,
  state,
  session,
  queryKey,
  itemsById,
  isAdmin,
  chosenMember
}: Readonly<{
  kind: PickBanKind;
  encounterId: number;
  encounter: PickBanBoardEncounter;
  state: PickBanState;
  session: NonNullable<PickBanState["session"]>;
  queryKey: unknown[];
  itemsById: Record<number, PickBanItemLike | undefined>;
  isAdmin: boolean;
  /** The player chosen to pick for on a member step (`PickBanMember.id`); see {@link memberChoice}. */
  chosenMember: number | null;
}>): PickBanController {
  const t = useTranslations("pickBan.room");
  const queryClient = useQueryClient();

  const step = state.current_step;
  const viewerTeamId = state.viewer_team_id;
  const seats = pickBanSeats(encounter.teams);
  const opponentTeamId =
    viewerTeamId == null ? null : (seats.find((seat) => seat.id !== viewerTeamId)?.id ?? null);
  // A mix's hero picks (spec §11.6): a member step is answered for ONE player, an assignment by a captain at once.
  const memberStep = step?.member != null;
  const assignStep = step?.action === "assign";
  const { choosable: choosableMembers, acting: actingMemberId } = memberChoice(state, isAdmin, chosenMember);
  // On a member step the answer is that player's own: a teammate's lock never closes this pick.
  const submission = viewerSubmission(state, actingMemberId);
  const serverDraft = submission?.items ?? [];
  const draftLocked = submission != null && submission.state !== "draft";

  const [pickedItemId, setSelectedItemId] = useState<number | null>(null);
  const [selectedTargetId, setSelectedTargetId] = useState<number | null>(null);
  /**
   * The draft an organizer is building out of this pool for an absent captain.
   * It lives here, not in the admin panel, because the clicks that fill it are
   * this board's — the panel only names the side it is for and sends it.
   */
  const [adminDraft, setAdminDraft] = useState<PickBanSubmissionItem[]>([]);
  const [adminTargetId, setAdminTargetId] = useState<number | null>(null);
  /**
   * The viewer's own edits since the last server read, keyed by the step and
   * attempt they were made on — so a reveal, a new round or a dispute
   * (attempt + 1, prefilled by the server) drops them without an effect and
   * without ever showing one step's draft on another.
   */
  const stepKey = `${state.current_step_index ?? -1}:${submission?.attempt ?? 0}`;
  const [localDraft, setLocalDraft] = useState<{
    key: string;
    items: PickBanSubmissionItem[];
  } | null>(null);
  const draftItems = localDraft?.key === stepKey ? localDraft.items : serverDraft;
  // The Lock trusts `draft_issues`, and those judge the SAVED draft — so it
  // waits until the local edits are that draft.
  const draftKey = (items: PickBanSubmissionItem[]) =>
    items.map((item) => `${item.item_id}:${item.target_player_id ?? ""}`).join(",");
  const draftDirty = draftKey(draftItems) !== draftKey(serverDraft);

  const selectedItemId =
    pickedItemId != null &&
    state.pool.some((entry) => entry.item_id === pickedItemId && entry.status === "available") &&
    // A member pick is the chosen player's: switching to one who may not take the hero (Fearless) drops it.
    (!memberStep || (state.member_eligible?.[String(actingMemberId)] ?? []).includes(pickedItemId))
      ? pickedItemId
      : null;

  // A side step chooses an index into `state.sides`, never a catalog item: its own state, never filtered through
  // the pool. It belongs to one turn — this step as it was (re)opened — and is DISCARDED the moment the turn
  // changes, so an undo back to the same step index starts with no side chosen instead of resurrecting one.
  const isSideStep = step?.action === "side_pick";
  const sideKey = `${session.id}:${stepKey}:${session.current_step_started_at ?? ""}`;
  const [pickedSide, setPickedSide] = useState<{ key: string; index: number | null }>({
    key: sideKey,
    index: null
  });
  if (pickedSide.key !== sideKey) setPickedSide({ key: sideKey, index: null });
  const selectedSide = isSideStep && pickedSide.key === sideKey ? pickedSide.index : null;
  const sideLabelOf = useSideLabel();
  const sideLabel = (code: string) => sideLabelOf(encounter.discipline, code);
  const sideLabels = state.sides.map(sideLabel);

  const actionMutation = useMutation({
    mutationFn: (input: PickBanActionInput) =>
      pickBanService.performPickBanAction(kind, encounterId, input),
    onSuccess: (next) => {
      setSelectedItemId(null);
      setPickedSide((current) => ({ ...current, index: null }));
      setSelectedTargetId(null);
      queryClient.setQueryData(queryKey, next);
    },
    onError: (error) => notify.apiError(error, { title: t("captain.actionFailed") }),
    onSettled: () => void queryClient.invalidateQueries({ queryKey })
  });

  // A host picking for a player they are not: the organizer route, which acts for any seat (spec §11.6 R4-9).
  const hostPickMutation = useMutation({
    mutationFn: (input: { encounter_team_id: number; item_id: number; member_id: number }) =>
      adminService.adminPickBanAct(encounterId, { kind, action: "pick", ...input }),
    onSuccess: () => setSelectedItemId(null),
    onError: (error) => notify.apiError(error, { title: t("captain.actionFailed") }),
    onSettled: () => void queryClient.invalidateQueries({ queryKey })
  });

  const submitMutation = useMutation({
    mutationFn: (input: PickBanSubmitInput) => pickBanService.submitDraft(kind, encounterId, input),
    onSuccess: (next) => queryClient.setQueryData(queryKey, next),
    onError: (error) => {
      // The optimistic tray is wrong now; the server's answer is the truth.
      setLocalDraft(null);
      notify.apiError(error, { title: t("draft.saveFailed") });
    }
  });
  const submitDraft = submitMutation.mutate;

  const disputeMutation = useMutation({
    mutationFn: () => pickBanService.disputeStep(kind, encounterId),
    onSuccess: (next) => queryClient.setQueryData(queryKey, next),
    onError: (error) => notify.apiError(error, { title: t("dispute.failed") }),
    onSettled: () => void queryClient.invalidateQueries({ queryKey })
  });

  // Debounced autosave: a blind draft is built by clicking five tiles in a row,
  // and each click is not worth a round trip. The lock is sent separately and
  // immediately — it is the only write that has a deadline behind it.
  const savedRef = useRef<string | null>(null);
  useEffect(() => {
    if (localDraft == null || localDraft.key !== stepKey) return;
    const payload = JSON.stringify(localDraft.items);
    if (savedRef.current === `${stepKey}|${payload}`) return;
    const timer = setTimeout(() => {
      savedRef.current = `${stepKey}|${payload}`;
      submitDraft({ items: localDraft.items, lock: false });
    }, DRAFT_SAVE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [localDraft, stepKey, submitDraft]);

  const teamName = (teamId: number) => seatName(seats, teamId);

  const targets = state.targets;
  const targetRoster =
    targets != null && opponentTeamId != null ? (targets[opponentTeamId] ?? []) : [];
  const targetName = (playerId: number) =>
    Object.values(targets ?? {})
      .flat()
      .find((player) => player.player_id === playerId)?.name ?? null;

  const isBlindStep = step?.blind === true;
  // A member step picks for the chosen player; an assignment is answered by submit, never by an act (spec §11.6 R4-1).
  const captainAction: PickBanAction | null = memberStep
    ? actingMemberId != null
      ? "pick"
      : null
    : !isBlindStep &&
        state.viewer_can_act &&
        state.allowed_actions.length > 0 &&
        state.allowed_actions[0] !== "assign"
      ? state.allowed_actions[0]
      : null;
  // An organizer standing in for an absent captain fills the blind draft out of
  // this same pool — unless they ARE the captain on the clock, whose own draft
  // keeps the clicks.
  const adminDrafting = isAdmin && isBlindStep && !state.viewer_can_act;
  const canSelect =
    isSessionActive(session) &&
    !assignStep &&
    !state.is_complete &&
    ((state.viewer_can_act && !draftLocked) || (isAdmin && !isBlindStep) || adminDrafting);
  const selectedItemName =
    selectedItemId != null
      ? (itemsById[selectedItemId]?.name ?? t(`${kind}.itemNumber`, { id: selectedItemId }))
      : null;

  const draftItemIds = new Set(
    (adminDrafting ? adminDraft : draftItems).map((item) => item.item_id)
  );
  const eligibleIds = memberStep
    ? actingMemberId != null
      ? new Set(state.member_eligible?.[String(actingMemberId)] ?? [])
      : null
    : eligibleItemIds(state.eligible, selectedTargetId);
  const assignedByPlayer: Record<number, number | undefined> = {};
  for (const item of draftItems) {
    if (item.target_player_id != null) assignedByPlayer[item.target_player_id] = item.item_id;
  }

  /**
   * One tile click on a blind step against a draft: add the item, or take it
   * back out. On a per-player step the click lands on the given player, and a
   * second hero for that player replaces the first — `one_per_target` makes
   * two of them illegal anyway, and silently refusing the click would read as
   * a broken tile. `null` back means the step names a player and none is
   * chosen yet — the caller says so, this only computes.
   */
  const toggleBlindItem = (
    items: PickBanSubmissionItem[],
    itemId: number,
    targetPlayerId: number | null
  ): PickBanSubmissionItem[] | null => {
    if (step == null) return items;
    const targeted = step.target != null;
    const existing = items.findIndex(
      (item) =>
        item.item_id === itemId &&
        (!targeted || item.target_player_id === targetPlayerId || targetPlayerId == null)
    );
    if (existing >= 0) return items.filter((_, index) => index !== existing);
    if (targeted && targetPlayerId == null) return null;
    const room = targeted
      ? items.filter((item) => item.target_player_id !== targetPlayerId)
      : items;
    if (room.length >= step.count) return items;
    return [...room, { item_id: itemId, target_player_id: targeted ? targetPlayerId : null }];
  };

  const toggleDraftItem = (itemId: number) => {
    if (step == null || draftLocked) return;
    const next = toggleBlindItem(draftItems, itemId, selectedTargetId);
    if (next == null) {
      notify.info(t("target.selectFirst"));
      return;
    }
    setLocalDraft({ key: stepKey, items: next });
  };

  /** The same click, for the side an organizer is standing in for. */
  const toggleAdminDraftItem = (itemId: number) => {
    const next = toggleBlindItem(adminDraft, itemId, adminTargetId);
    if (next == null) {
      notify.info(t("target.selectFirst"));
      return;
    }
    setAdminDraft(next);
  };

  /** A pool tile clicked: a blind step edits a draft (the viewer's own, or the one a host builds), else it selects. */
  const selectTile = (itemId: number) => {
    if (isBlindStep) {
      if (adminDrafting) toggleAdminDraftItem(itemId);
      else toggleDraftItem(itemId);
      return;
    }
    setSelectedItemId((current) => (current === itemId ? null : itemId));
  };

  /** The command bar's confirm: the viewer's own act, or -- on a member step -- a captain's or a host's pick for a seat. */
  const confirm = (itemId: number) => {
    if (captainAction == null) return;
    if (memberStep && actingMemberId != null) {
      // Their own or a teammate's pick goes by the captain route; anyone else's is a host's, for that seat.
      if (state.viewer_can_act && state.viewer_member_ids.includes(actingMemberId)) {
        actionMutation.mutate({ item_id: itemId, action: "pick", member_id: actingMemberId });
        return;
      }
      const seat = state.members.find((member) => member.id === actingMemberId);
      if (seat != null) {
        hostPickMutation.mutate({
          encounter_team_id: seat.encounter_team_id,
          item_id: itemId,
          member_id: actingMemberId
        });
      }
      return;
    }
    actionMutation.mutate({
      item_id: itemId,
      action: captainAction,
      ...(step?.target != null ? { target_player_id: selectedTargetId } : {})
    });
  };

  const cancelSelection = () =>
    isSideStep ? setPickedSide((current) => ({ ...current, index: null })) : setSelectedItemId(null);

  const chooseSide = (index: number | null) => setPickedSide({ key: sideKey, index });

  const removeDraftAt = (index: number) =>
    setLocalDraft({ key: stepKey, items: draftItems.filter((_, position) => position !== index) });

  const lockDraft = () => submitDraft({ items: draftItems, lock: true });

  const adminSlot: PickBanAdminSlot = {
    kind,
    // The organizer's side choice lives in the admin row; a tile picked on an earlier step is not it.
    selectedItemId: isSideStep ? null : selectedItemId,
    selectedItemName: isSideStep ? null : selectedItemName,
    blind: adminDrafting
      ? {
          items: adminDraft,
          targetPlayerId: adminTargetId,
          setTargetPlayerId: setAdminTargetId,
          removeAt: (index) => setAdminDraft((items) => items.filter((_, position) => position !== index)),
          clear: () => setAdminDraft([])
        }
      : null,
    onMutated: () => {
      setSelectedItemId(null);
      setLocalDraft(null);
      setAdminDraft([]);
      void queryClient.invalidateQueries({ queryKey });
    }
  };

  const revealedStep = lastRevealedBlindStep(state.sequence, state.submissions);

  // The backend enforces who may elect (pending_chooser_team_id); this only
  // gates whether the losing captain's own client shows the modal at all.
  const showElectOpener =
    session.awaiting_choice &&
    viewerTeamId != null &&
    viewerTeamId === session.pending_chooser_team_id;
  // ...and everyone ELSE has to be told why the room stopped. The round the
  // choice is holding does not exist yet, so a spectator, the winning captain
  // and an organizer all saw a finished round with nothing to click and no
  // reason given — the exact shape of a hung room.
  const pendingOpenerTeamId = session.awaiting_choice ? session.pending_chooser_team_id : null;

  return {
    step,
    seats,
    viewerTeamId,
    opponentTeamId,
    memberStep,
    assignStep,
    choosableMembers,
    actingMemberId,
    actingMemberName: memberStep && actingMemberId != null ? memberName(state.members, actingMemberId) : null,
    selectedItemId,
    selectedItemName,
    selectedTargetId,
    setSelectedTargetId,
    isSideStep,
    selectedSide,
    chooseSide,
    sideLabel,
    sideLabels,
    isBlindStep,
    captainAction,
    adminDrafting,
    canSelect,
    draftItems,
    draftItemIds,
    draftLocked,
    draftDirty,
    eligibleIds,
    assignedByPlayer,
    targetRoster,
    targetName,
    teamName,
    selectTile,
    confirm,
    cancelSelection,
    removeDraftAt,
    lockDraft,
    adminSlot,
    revealedStep,
    showElectOpener,
    pendingOpenerTeamId,
    acting: actionMutation.isPending || hostPickMutation.isPending,
    locking: submitMutation.isPending,
    dispute: { pending: disputeMutation.isPending, run: () => disputeMutation.mutate() }
  };
}
