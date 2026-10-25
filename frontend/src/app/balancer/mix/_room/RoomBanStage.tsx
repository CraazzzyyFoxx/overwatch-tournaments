"use client";

import { useEffect, useEffectEvent, useId, useMemo } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clock } from "lucide-react";

import { useTurnAlert } from "@/app/balancer/mix/_hooks/useTurnAlert";
import { ElectOpenerDialog } from "@/components/pick-ban/ElectOpenerDialog";
import { PickBanCommandBar } from "@/components/pick-ban/PickBanCommandBar";
import { PickBanDraftTray } from "@/components/pick-ban/PickBanDraftTray";
import { PickBanGrid, type PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import { PickBanAssignBoard } from "@/components/pick-ban/PickBanMemberTurn";
import { PickBanRevealPanel } from "@/components/pick-ban/PickBanRevealPanel";
import { PickBanSideChoice } from "@/components/pick-ban/PickBanSideChoice";
import { PickBanUndoControl } from "@/components/pick-ban/PickBanUndoControl";
import { PregameAdminControls } from "@/components/pick-ban/PregameAdminControls";
import {
  CHARACTER_PICK_BAN_KIND,
  isSessionActive,
  pickBanReserveMap,
  stepSubmissions,
  type PickBanSeat
} from "@/components/pick-ban/pick-ban-model";
import { usePickBanController } from "@/components/pick-ban/usePickBanController";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { PickBanAction, PickBanResolvedStep, PickBanState } from "@/types/tournament.types";

import { heroTransitionName } from "./room-model";

/**
 * A live match's hero bans and picks in the room's centre (spec §8, §11): the steps in order, the hero grid (or the
 * side choice, or the captains' assignment), and the bar that confirms the viewer's turn. The teams' bans and heroes
 * land in the columns beside it, where a member step's player is chosen too (`chosenMember`). A host acts for the team
 * on the clock from the same bar, and reaches everything else (a blind ban for an absent captain, a reopen, a reset)
 * through the organizer controls the host menu unfolds here. `onComplete` fires once when the room is done -- the
 * steps finished or a host cancelled it -- so the room re-reads the lobby, which then reads Live.
 */
export function RoomBanStage({
  encounterId,
  workspaceId,
  discipline,
  seats,
  state,
  queryKey,
  heroesById,
  canHost,
  showAdmin,
  chosenMember,
  onComplete
}: Readonly<{
  encounterId: number;
  workspaceId: number;
  discipline: string;
  /** The live match's participations in slot order. */
  seats: readonly PickBanSeat[];
  state: PickBanState & { session: NonNullable<PickBanState["session"]> };
  queryKey: unknown[];
  heroesById: Record<number, PickBanItemLike | undefined>;
  canHost: boolean;
  /** The host unfolded the organizer controls from the room's host menu. */
  showAdmin: boolean;
  /** The player a member step picks for, as chosen on the rosters (`PickBanMember.id`). */
  chosenMember: number | null;
  onComplete: () => void;
}>) {
  const t = useTranslations("mixes.arena.bans");
  const tRoom = useTranslations("mixes.room");
  const tPickBan = useTranslations("pickBan.room");
  const sideHintId = useId();
  const queryClient = useQueryClient();
  const metadata = useDisciplineMetadata(workspaceId, discipline);
  const session = state.session;
  const encounter = useMemo(
    () => ({ workspace_id: workspaceId, discipline, teams: seats }),
    [workspaceId, discipline, seats]
  );
  const room = usePickBanController({
    kind: CHARACTER_PICK_BAN_KIND,
    encounterId,
    encounter,
    state,
    session,
    queryKey,
    itemsById: heroesById,
    isAdmin: canHost,
    chosenMember
  });

  // A pick or an assignment says so in the tab title; a ban keeps its own (spec §11.6 R4-11). Each step (and each
  // reopening of one) is a turn of its own, so two picks of the viewer's in a row alert twice.
  const picking = state.expected_action === "pick" || state.expected_action === "assign";
  const turnStep = state.current_step_index;
  const turnAttempt = turnStep != null ? (stepSubmissions(state.submissions, turnStep)[0]?.attempt ?? 1) : 0;
  useTurnAlert(
    state.viewer_can_act,
    tRoom(picking ? "yourPickTitle" : "yourTurnTitle"),
    `${session.id}:${turnStep}:${turnAttempt}`
  );
  // An effect event: the room hands a fresh callback every render, and the re-read must still happen once.
  const complete = useEffectEvent(onComplete);
  const done = state.is_complete || session.status === "cancelled";
  useEffect(() => {
    if (done) complete();
  }, [done]);

  const step = room.step;
  const open = isSessionActive(session) && !state.is_complete && session.paused_at == null;
  // A host standing in for the one team on the clock of an open team step: the bar answers it through the
  // organizer route (spec §8.4: hosts act for anyone). Member picks already go that way through the board itself.
  const hostAction: PickBanAction | null =
    canHost &&
    open &&
    room.captainAction == null &&
    step != null &&
    !room.isBlindStep &&
    !room.memberStep &&
    !room.assignStep &&
    step.action !== "decider" &&
    step.action !== "assign" &&
    state.acting_team_ids.length === 1
      ? step.action
      : null;
  const hostAct = useMutation({
    mutationFn: (input: { encounter_team_id: number; item_id: number; action: PickBanAction }) =>
      adminService.adminPickBanAct(encounterId, { kind: CHARACTER_PICK_BAN_KIND, ...input }),
    onSuccess: () => room.cancelSelection(),
    onError: (error) => notify.apiError(error, { title: tPickBan("admin.actFailed") }),
    onSettled: () => void queryClient.invalidateQueries({ queryKey })
  });
  const barAction = state.is_complete ? null : (room.captainAction ?? hostAction);
  // Why the bar has nothing to confirm: a free-order pick waits for a player tapped on the rosters, and on a
  // captains-only pick everyone else is told who answers it.
  const pickHint =
    !open || step?.member == null || barAction != null
      ? null
      : room.choosableMembers.length > 1 && room.actingMemberId == null
        ? t("choosePlayer")
        : step.captains_only === true && !state.viewer_can_act && !canHost
          ? t("captainsPick")
          : null;
  const sideActor = room.captainAction === "side_pick" || hostAction === "side_pick";
  const canSelect = room.canSelect || hostAction != null;
  const title = tRoom(state.sequence.some((candidate) => candidate.action === "pick") ? "picksTitle" : "bansTitle");

  const header = (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-heading font-semibold text-[color:var(--aqt-fg)]">{title}</h2>
      </div>
      <StepStrip state={state} seats={seats} />
    </div>
  );

  return (
    <div className="flex flex-col gap-3">
      {room.pendingOpenerTeamId != null ? (
        <div className="flex items-start gap-2 rounded-xl border border-[color:var(--aqt-amber)]/45 bg-[color:var(--aqt-card-2)]/40 p-3 text-caption">
          <Clock className="mt-0.5 size-4 shrink-0 text-[color:var(--aqt-amber)]" aria-hidden />
          <p className="text-[color:var(--aqt-fg-muted)]">
            {tPickBan("electOpener.waiting", { team: room.teamName(room.pendingOpenerTeamId) })}
          </p>
        </div>
      ) : null}

      {room.revealedStep != null ? (
        <PickBanRevealPanel
          kind={CHARACTER_PICK_BAN_KIND}
          step={room.revealedStep}
          submissions={stepSubmissions(state.submissions, room.revealedStep.index)}
          itemsById={heroesById}
          seats={room.seats}
          targetName={room.targetName}
          dispute={state.dispute}
          disputing={room.dispute.pending}
          onDispute={room.dispute.run}
        />
      ) : null}

      {room.isSideStep ? (
        <Card variant="flat">
          <CardHeader className="flex flex-col gap-4 pb-3">
            {header}
            <CardTitle id={sideHintId} className="border-t border-[color:var(--aqt-border)] pt-4 text-base">
              {tPickBan("captain.chooseSideHint")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <PickBanSideChoice
              labelledBy={sideHintId}
              labels={room.sideLabels}
              value={room.selectedSide}
              size="lg"
              disabled={!sideActor || room.acting || hostAct.isPending}
              onChange={(index) => room.chooseSide(room.selectedSide === index ? null : index)}
            />
          </CardContent>
        </Card>
      ) : room.assignStep ? (
        <PickBanAssignBoard
          kind={CHARACTER_PICK_BAN_KIND}
          encounterId={encounterId}
          state={state}
          itemsById={heroesById}
          isAdmin={canHost}
          queryKey={queryKey}
          teamName={room.teamName}
          header={header}
        />
      ) : (
        <PickBanGrid
          kind={CHARACTER_PICK_BAN_KIND}
          pool={state.pool}
          itemsById={heroesById}
          selectedItemId={room.selectedItemId}
          canSelect={canSelect}
          currentRound={state.current_round}
          slotReserves={pickBanReserveMap(session)}
          eligibleIds={room.eligibleIds}
          draftItemIds={room.draftItemIds}
          onSelect={room.selectTile}
          seats={room.seats}
          header={header}
          characterClasses={metadata.data?.discipline.character_classes}
          itemTransitionName={(entry) =>
            entry.status === "available" ? heroTransitionName(entry.item_id) : undefined
          }
        />
      )}

      <PickBanUndoControl
        kind={CHARACTER_PICK_BAN_KIND}
        encounterId={encounterId}
        undo={state.undo}
        viewerTeamId={room.viewerTeamId}
        itemsById={heroesById}
        sideLabels={room.sideLabels}
        seats={room.seats}
        invalidateKeys={[queryKey]}
      />

      {canHost && showAdmin ? (
        <PregameAdminControls
          kind={CHARACTER_PICK_BAN_KIND}
          encounterId={encounterId}
          state={state}
          selectedItemId={room.adminSlot.selectedItemId}
          selectedItemName={room.adminSlot.selectedItemName}
          itemsById={heroesById}
          sideLabels={room.sideLabels}
          games={[]}
          blind={room.adminSlot.blind}
          seats={room.seats}
          bestOf={1}
          seriesWins={null}
          onMutated={room.adminSlot.onMutated}
          technicalLoss={false}
        />
      ) : null}

      {isSessionActive(session) ? (
        <PickBanCommandBar
          state={state}
          teamName={room.teamName}
          captainAction={barAction}
          draft={
            room.isBlindStep && step != null && room.viewerTeamId != null ? (
              <PickBanDraftTray
                kind={CHARACTER_PICK_BAN_KIND}
                step={step}
                items={room.draftItems}
                locked={room.draftLocked}
                dirty={room.draftDirty}
                issues={state.draft_issues}
                locking={room.locking}
                itemsById={heroesById}
                targetName={room.targetName}
                opponentTeamId={room.opponentTeamId}
                opponentProgress={
                  room.opponentTeamId != null ? state.step_progress?.[room.opponentTeamId] : undefined
                }
                opponentName={room.opponentTeamId != null ? room.teamName(room.opponentTeamId) : ""}
                onRemove={room.removeDraftAt}
                onLock={room.lockDraft}
              />
            ) : null
          }
          draftOpen={room.isBlindStep && state.viewer_can_act && !room.draftLocked && !state.is_complete}
          kind={CHARACTER_PICK_BAN_KIND}
          selectedItemId={room.isSideStep ? room.selectedSide : room.selectedItemId}
          selectedItemName={
            room.isSideStep
              ? room.selectedSide != null
                ? (room.sideLabels[room.selectedSide] ?? `#${room.selectedSide}`)
                : null
              : room.selectedItemName
          }
          selectedItem={!room.isSideStep && room.selectedItemId != null ? heroesById[room.selectedItemId] : undefined}
          pending={room.acting || hostAct.isPending}
          forMember={room.actingMemberName}
          hint={pickHint}
          onConfirm={(itemId) => {
            if (room.captainAction != null) {
              room.confirm(itemId);
              return;
            }
            const teamId = state.acting_team_ids[0];
            if (hostAction != null && teamId != null) {
              hostAct.mutate({ encounter_team_id: teamId, item_id: itemId, action: hostAction });
            }
          }}
          onCancel={room.cancelSelection}
        />
      ) : (
        <p className="text-caption text-[color:var(--aqt-fg-muted)]">{t("closed")}</p>
      )}

      <ElectOpenerDialog
        kind={CHARACTER_PICK_BAN_KIND}
        encounterId={encounterId}
        open={room.showElectOpener}
        seats={room.seats}
        queryKey={queryKey}
      />
    </div>
  );
}

const STEP_LABEL: Record<
  PickBanResolvedStep["action"],
  "ban" | "pick" | "protect" | "side" | "decider" | "assign"
> = {
  ban: "ban",
  pick: "pick",
  protect: "protect",
  side_pick: "side",
  decider: "decider",
  assign: "assign"
};

/**
 * The room's steps in order, one chip each: what it is and whose (A, B or both), how many when more than one, the
 * one in play outlined and the ones behind it faded.
 */
function StepStrip({ state, seats }: Readonly<{ state: PickBanState; seats: readonly PickBanSeat[] }>) {
  const t = useTranslations("mixes.arena.bans");
  const order = [...seats].sort((left, right) => left.slot - right.slot).map((seat) => seat.id);
  const letter = (actor: number | null) => {
    const index = actor == null ? -1 : order.indexOf(actor);
    return index < 0 ? null : String.fromCharCode(65 + index);
  };
  const current = state.is_complete ? state.sequence.length : (state.current_step_index ?? -1);
  return (
    <ol aria-label={t("steps")} className="flex flex-wrap gap-1">
      {state.sequence.map((step) => {
        const who = step.actors.map(letter).filter((value): value is string => value != null);
        const now = step.index === current;
        return (
          <li
            key={`${step.round}:${step.index}`}
            aria-current={now ? "step" : undefined}
            className={cn(
              "flex h-6 items-center gap-1 rounded-md border px-1.5 text-label font-semibold",
              now
                ? "border-[color:var(--aqt-teal)] text-[color:var(--aqt-teal)]"
                : "border-[color:var(--aqt-border)]",
              step.index < current ? "text-[color:var(--aqt-fg-faint)]" : now ? null : "text-[color:var(--aqt-fg-muted)]"
            )}
          >
            {t(`step.${STEP_LABEL[step.action]}`)}
            {who.length > 0 ? <span className="tabular-nums">{who.join("·")}</span> : null}
            {step.member === "each" ? <span>{t("everyone")}</span> : null}
            {step.count > 1 ? <span className="tabular-nums">×{step.count}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}
