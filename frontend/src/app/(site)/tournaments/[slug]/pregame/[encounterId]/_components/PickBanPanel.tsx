"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clock, UserX } from "lucide-react";

import { notify } from "@/lib/notify";
import pickBanService, {
  type PickBanActionInput,
  type PickBanSubmitInput
} from "@/services/pickBan.service";
import type { Encounter } from "@/types/encounter.types";
import type {
  PickBanAction,
  PickBanKind,
  PickBanState,
  PickBanSubmissionItem
} from "@/types/tournament.types";

import {
  eligibleItemIds,
  isSessionActive,
  lastRevealedBlindStep,
  pickBanReserveMap,
  stepSubmissions,
  viewerSubmission,
  type PickBanSide
} from "@/components/pick-ban/pick-ban-model";
import { PickBanCommandBar } from "@/components/pick-ban/PickBanCommandBar";
import { PickBanDraftTray } from "@/components/pick-ban/PickBanDraftTray";
import { PickBanGrid, type PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import { PickBanRevealPanel } from "@/components/pick-ban/PickBanRevealPanel";
import { PickBanStepTimeline } from "@/components/pick-ban/PickBanStepTimeline";
import { PickBanTargetBoard } from "@/components/pick-ban/PickBanTargetBoard";
import { PickBanUndoControl } from "@/components/pick-ban/PickBanUndoControl";
import { ElectOpenerDialog } from "@/components/pick-ban/ElectOpenerDialog";
import { PregameAdminControls } from "./PregameAdminControls";

/** How long a blind draft edit waits before it is saved, so five quick clicks are one request. */
const DRAFT_SAVE_DELAY_MS = 300;

/** The board for whichever pick-ban kind is on the clock: timeline, pool, command bar. */
export function PickBanPanel({
  kind,
  encounterId,
  encounter,
  state,
  session,
  queryKey,
  itemsById,
  isAdmin,
  header
}: Readonly<{
  kind: PickBanKind;
  encounterId: number;
  encounter: Encounter;
  state: PickBanState;
  session: NonNullable<PickBanState["session"]>;
  queryKey: unknown[];
  itemsById: Record<number, PickBanItemLike | undefined>;
  isAdmin: boolean;
  header: React.ReactNode;
}>) {
  const t = useTranslations("pickBan.room");
  const queryClient = useQueryClient();

  const step = state.current_step;
  const viewerSide = state.viewer_side;
  const opponentSide: PickBanSide | null =
    viewerSide === "home" ? "away" : viewerSide === "away" ? "home" : null;
  const submission = viewerSubmission(state);
  const serverDraft = submission?.items ?? [];
  const draftLocked = submission != null && submission.state !== "draft";

  const [pickedItemId, setSelectedItemId] = useState<number | null>(null);
  const [selectedTargetId, setSelectedTargetId] = useState<number | null>(null);
  /**
   * The viewer's own edits since the last server read, keyed by the step and
   * attempt they were made on — so a reveal, a new round or a dispute
   * (attempt + 1, prefilled by the server) drops them without an effect and
   * without ever showing one step's draft on another.
   */
  const stepKey = `${state.current_step_index ?? -1}:${submission?.attempt ?? 0}`;
  const [localDraft, setLocalDraft] = useState<{ key: string; items: PickBanSubmissionItem[] } | null>(
    null
  );
  const draftItems = localDraft?.key === stepKey ? localDraft.items : serverDraft;
  // The Lock trusts `draft_issues`, and those judge the SAVED draft — so it
  // waits until the local edits are that draft.
  const draftKey = (items: PickBanSubmissionItem[]) =>
    items.map((item) => `${item.item_id}:${item.target_player_id ?? ""}`).join(",");
  const draftDirty = draftKey(draftItems) !== draftKey(serverDraft);

  const selectedItemId =
    pickedItemId != null &&
    state.pool.some((entry) => entry.item_id === pickedItemId && entry.status === "available")
      ? pickedItemId
      : null;

  const actionMutation = useMutation({
    mutationFn: (input: PickBanActionInput) =>
      pickBanService.performPickBanAction(kind, encounterId, input),
    onSuccess: (next) => {
      setSelectedItemId(null);
      setSelectedTargetId(null);
      queryClient.setQueryData(queryKey, next);
    },
    onError: (error) => notify.apiError(error, { title: t("captain.actionFailed") }),
    onSettled: () => void queryClient.invalidateQueries({ queryKey })
  });

  const submitMutation = useMutation({
    mutationFn: (input: PickBanSubmitInput) =>
      pickBanService.submitDraft(kind, encounterId, input),
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

  const sideName = (side: PickBanSide) =>
    side === "home"
      ? (encounter.home_team?.name ?? t("side.home"))
      : (encounter.away_team?.name ?? t("side.away"));

  const targets = state.targets;
  const targetRoster = targets != null && opponentSide != null ? targets[opponentSide] : [];
  const targetName = (playerId: number) =>
    [...(targets?.home ?? []), ...(targets?.away ?? [])].find(
      (player) => player.player_id === playerId
    )?.name ?? null;

  const isBlindStep = step?.blind === true;
  const captainAction: PickBanAction | null =
    !isBlindStep && state.viewer_can_act && state.allowed_actions.length > 0
      ? state.allowed_actions[0]
      : null;
  const canSelect =
    isSessionActive(session) &&
    !state.is_complete &&
    ((state.viewer_can_act && !draftLocked) || (isAdmin && !isBlindStep));
  const selectedItemName =
    selectedItemId != null
      ? (itemsById[selectedItemId]?.name ?? t(`${kind}.itemNumber`, { id: selectedItemId }))
      : null;

  const draftItemIds = new Set(draftItems.map((item) => item.item_id));
  const eligibleIds = eligibleItemIds(state.eligible, selectedTargetId);
  const assignedByPlayer: Record<number, number | undefined> = {};
  for (const item of draftItems) {
    if (item.target_player_id != null) assignedByPlayer[item.target_player_id] = item.item_id;
  }

  /**
   * One tile click on a blind step: add the item to the private draft, or take
   * it back out. On a per-player step the click lands on the SELECTED player,
   * and a second hero for that player replaces the first — `one_per_target`
   * makes two of them illegal anyway, and silently refusing the click would
   * read as a broken tile.
   */
  const toggleDraftItem = (itemId: number) => {
    if (step == null || draftLocked) return;
    const targeted = step.target != null;
    const existing = draftItems.findIndex(
      (item) =>
        item.item_id === itemId &&
        (!targeted || item.target_player_id === selectedTargetId || selectedTargetId == null)
    );
    let next: PickBanSubmissionItem[];
    if (existing >= 0) {
      next = draftItems.filter((_, index) => index !== existing);
    } else {
      if (targeted && selectedTargetId == null) {
        notify.info(t("target.selectFirst"));
        return;
      }
      const room = targeted
        ? draftItems.filter((item) => item.target_player_id !== selectedTargetId)
        : draftItems;
      if (room.length >= step.count) return;
      next = [...room, { item_id: itemId, target_player_id: targeted ? selectedTargetId : null }];
    }
    setLocalDraft({ key: stepKey, items: next });
  };

  const revealedStep = lastRevealedBlindStep(state.sequence, state.submissions);

  // The backend enforces who may elect (pending_loser_side); this only gates
  // whether the losing captain's own client shows the modal at all.
  const showElectOpener =
    session.awaiting_choice && state.viewer_side === session.pending_loser_side;
  // ...and everyone ELSE has to be told why the room stopped. The round the
  // choice is holding does not exist yet, so a spectator, the winning captain
  // and an organizer all saw a finished round with nothing to click and no
  // reason given — the exact shape of a hung room.
  const pendingOpenerSide = session.awaiting_choice ? session.pending_loser_side : null;

  return (
    <>
      {pendingOpenerSide != null ? (
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-[color:var(--aqt-amber)]/45 bg-[color:var(--aqt-card-2)]/40 p-3 text-sm">
          <Clock className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--aqt-amber)]" aria-hidden />
          <p className="text-[color:var(--aqt-fg-muted)]">
            {t("electOpener.waiting", { team: sideName(pendingOpenerSide) })}
          </p>
        </div>
      ) : null}
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(260px,1fr)_2fr]">
        {/* Stretched to the row so the per-player board can stick inside it for
            the whole height of the pool beside it: the captain alternates
            "who" (here) and "which hero" (the grid) five times in a row. */}
        <div className="flex flex-col gap-4 lg:self-stretch">
          <PickBanStepTimeline
            kind={kind}
            sequence={state.sequence}
            submissions={state.submissions}
            currentStepIndex={state.current_step_index}
            isComplete={state.is_complete}
            currentRound={state.current_round}
            itemsById={itemsById}
            sideName={sideName}
            session={session}
          />
          {step?.target != null && opponentSide != null ? (
            targetRoster.length > 0 ? (
              <div className="lg:sticky lg:top-[var(--aqt-sticky-top)]">
                <PickBanTargetBoard
                  targets={targetRoster}
                  selectedPlayerId={selectedTargetId}
                  assignedByPlayer={assignedByPlayer}
                  itemsById={itemsById}
                  onSelect={(playerId) =>
                    setSelectedTargetId((current) => (current === playerId ? null : playerId))
                  }
                  teamName={sideName(opponentSide)}
                  disabled={!canSelect}
                />
              </div>
            ) : (
              // Without the opponent's roster nobody can be named, so the whole
              // pool is ineligible — say why instead of leaving a grey grid.
              <div
                data-pick-ban-no-roster
                className="flex items-start gap-2 rounded-xl border border-[color:var(--aqt-amber)]/45 bg-[color:var(--aqt-card-2)]/40 p-3 text-sm"
              >
                <UserX className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--aqt-amber)]" aria-hidden />
                <p className="text-[color:var(--aqt-fg-muted)]">
                  {t("target.noRoster", { team: sideName(opponentSide) })}
                </p>
              </div>
            )
          ) : null}
        </div>
        <div className="flex flex-col gap-4">
          {revealedStep != null ? (
            <PickBanRevealPanel
              kind={kind}
              step={revealedStep}
              submissions={stepSubmissions(state.submissions, revealedStep.index)}
              itemsById={itemsById}
              sideName={sideName}
              targetName={targetName}
              dispute={state.dispute}
              disputing={disputeMutation.isPending}
              onDispute={() => disputeMutation.mutate()}
            />
          ) : null}

          <PickBanGrid
            kind={kind}
            pool={state.pool}
            itemsById={itemsById}
            selectedItemId={selectedItemId}
            canSelect={canSelect}
            currentRound={state.current_round}
            slotReserves={pickBanReserveMap(session)}
            eligibleIds={eligibleIds}
            draftItemIds={draftItemIds}
            onSelect={(itemId) => {
              if (isBlindStep) {
                toggleDraftItem(itemId);
                return;
              }
              setSelectedItemId((current) => (current === itemId ? null : itemId));
            }}
            header={header}
          />

          {/* Under the grid, above the admin panel: the correction path a
              captain reaches for belongs next to the pool they misclicked, and
              it is the captains' own — an organizer's blunt reset is separate. */}
          <PickBanUndoControl
            kind={kind}
            encounterId={encounterId}
            undo={state.undo}
            viewerSide={state.viewer_side}
            itemsById={itemsById}
            sideName={sideName}
            invalidateKeys={[queryKey]}
          />

          {isAdmin ? (
            <PregameAdminControls
              kind={kind}
              encounterId={encounterId}
              state={state}
              selectedItemId={selectedItemId}
              selectedItemName={selectedItemName}
              onMutated={() => {
                setSelectedItemId(null);
                setLocalDraft(null);
                void queryClient.invalidateQueries({ queryKey });
              }}
            />
          ) : null}
        </div>
      </div>

      {isSessionActive(session) ? (
        <PickBanCommandBar
          state={state}
          sideName={sideName}
          captainAction={state.is_complete ? null : captainAction}
          draft={
            isBlindStep && step != null && viewerSide != null ? (
              <PickBanDraftTray
                kind={kind}
                step={step}
                items={draftItems}
                locked={draftLocked}
                dirty={draftDirty}
                issues={state.draft_issues}
                locking={submitMutation.isPending}
                itemsById={itemsById}
                targetName={targetName}
                opponentSide={opponentSide}
                opponentProgress={
                  opponentSide != null ? state.step_progress?.[opponentSide] : undefined
                }
                opponentName={opponentSide != null ? sideName(opponentSide) : ""}
                onRemove={(index) =>
                  setLocalDraft({
                    key: stepKey,
                    items: draftItems.filter((_, position) => position !== index)
                  })
                }
                onLock={() => submitDraft({ items: draftItems, lock: true })}
              />
            ) : null
          }
          draftOpen={isBlindStep && state.viewer_can_act && !draftLocked && !state.is_complete}
          kind={kind}
          selectedItemId={selectedItemId}
          selectedItemName={selectedItemName}
          selectedItem={selectedItemId != null ? itemsById[selectedItemId] : undefined}
          pending={actionMutation.isPending}
          onConfirm={(itemId) => {
            if (captainAction == null) return;
            actionMutation.mutate({
              item_id: itemId,
              action: captainAction,
              ...(step?.target != null ? { target_player_id: selectedTargetId } : {})
            });
          }}
          onCancel={() => setSelectedItemId(null)}
        />
      ) : null}

      <ElectOpenerDialog
        kind={kind}
        encounterId={encounterId}
        open={showElectOpener}
        homeName={sideName("home")}
        awayName={sideName("away")}
        queryKey={queryKey}
      />
    </>
  );
}
