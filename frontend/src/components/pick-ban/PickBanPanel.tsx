"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Clock, UserX } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import type { PickBanKind, PickBanState } from "@/types/tournament.types";

import {
  isSessionActive,
  memberName,
  pickBanReserveMap,
  stepSubmissions
} from "@/components/pick-ban/pick-ban-model";
import { PickBanCommandBar } from "@/components/pick-ban/PickBanCommandBar";
import { PickBanDraftTray } from "@/components/pick-ban/PickBanDraftTray";
import { PickBanGrid, type PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import { PickBanRevealPanel } from "@/components/pick-ban/PickBanRevealPanel";
import { PickBanAssignBoard, PickBanMemberChooser } from "@/components/pick-ban/PickBanMemberTurn";
import { PickBanStepTimeline } from "@/components/pick-ban/PickBanStepTimeline";
import { PickBanTargetBoard } from "@/components/pick-ban/PickBanTargetBoard";
import { PickBanUndoControl } from "@/components/pick-ban/PickBanUndoControl";
import { PickBanSideAssignment, PickBanSideChoice } from "@/components/pick-ban/PickBanSideChoice";
import {
  usePickBanController,
  type PickBanAdminSlot,
  type PickBanBoardEncounter
} from "@/components/pick-ban/usePickBanController";
import { ElectOpenerDialog } from "@/components/pick-ban/ElectOpenerDialog";

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
  adminPanel,
  header,
  previousMatchId
}: Readonly<{
  kind: PickBanKind;
  encounterId: number;
  encounter: PickBanBoardEncounter;
  state: PickBanState;
  session: NonNullable<PickBanState["session"]>;
  queryKey: unknown[];
  itemsById: Record<number, PickBanItemLike | undefined>;
  isAdmin: boolean;
  /**
   * The organizer's panel, rendered under the pool. The room owns it (one per
   * screen, across every phase) and only borrows this board's selection.
   */
  adminPanel?: (slot: PickBanAdminSlot) => React.ReactNode;
  header: React.ReactNode;
  /** The previous map's parsed match, for a per-player ban's "last played" hints; null when there is none. */
  previousMatchId: number | null;
}>) {
  const t = useTranslations("pickBan.room");
  // The room's own game: its role dictionary names the targets' roles, its declared classes order the pool filter.
  const metadata = useDisciplineMetadata(encounter.workspace_id, encounter.discipline);
  const sideHintId = useId();
  const [chosenMember, chooseMember] = useState<number | null>(null);
  const {
    step,
    seats,
    viewerTeamId,
    opponentTeamId,
    memberStep,
    assignStep,
    choosableMembers,
    actingMemberId,
    actingMemberName,
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
    acting,
    locking,
    dispute
  } = usePickBanController({ kind, encounterId, encounter, state, session, queryKey, itemsById, isAdmin, chosenMember });

  return (
    <>
      {pendingOpenerTeamId != null ? (
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-[color:var(--aqt-amber)]/45 bg-[color:var(--aqt-card-2)]/40 p-3 text-sm">
          <Clock className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--aqt-amber)]" aria-hidden />
          <p className="text-[color:var(--aqt-fg-muted)]">
            {t("electOpener.waiting", { team: teamName(pendingOpenerTeamId) })}
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
            sideLabels={sideLabels}
            teamName={teamName}
            memberName={(memberId) => memberName(state.members, memberId)}
            session={session}
          />
          <PickBanSideAssignment
            startingSides={state.starting_sides}
            position={state.current_round}
            seats={seats}
            sideLabel={sideLabel}
          />
          {memberStep && choosableMembers.length > 1 ? (
            <PickBanMemberChooser
              members={choosableMembers.map((id) => ({ id, name: memberName(state.members, id) }))}
              value={actingMemberId}
              onChange={chooseMember}
            />
          ) : null}
          {step?.target != null && opponentTeamId != null ? (
            targetRoster.length > 0 ? (
              <div className="lg:sticky lg:top-[var(--aqt-sticky-top)]">
                <PickBanTargetBoard
                  targets={targetRoster}
                  discipline={encounter.discipline}
                  ontology={metadata.data ?? null}
                  previousMatchId={previousMatchId}
                  selectedPlayerId={selectedTargetId}
                  assignedByPlayer={assignedByPlayer}
                  itemsById={itemsById}
                  onSelect={(playerId) =>
                    setSelectedTargetId((current) => (current === playerId ? null : playerId))
                  }
                  teamName={teamName(opponentTeamId)}
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
                <UserX
                  className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--aqt-amber)]"
                  aria-hidden
                />
                <p className="text-[color:var(--aqt-fg-muted)]">
                  {t("target.noRoster", { team: teamName(opponentTeamId) })}
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
              seats={seats}
              targetName={targetName}
              dispute={state.dispute}
              disputing={dispute.pending}
              onDispute={dispute.run}
            />
          ) : null}

          {isSideStep ? (
            // No pool on a side step: the captain chooses a side, and a champion tile here would be a 400.
            <Card>
              <CardHeader className="flex flex-col gap-4 pb-3">
                {header}
                <div className="border-t border-[color:var(--aqt-border)] pt-4">
                  <CardTitle id={sideHintId}>
                    {t("captain.chooseSideHint")}
                  </CardTitle>
                </div>
              </CardHeader>
              <CardContent>
                <PickBanSideChoice
                  labelledBy={sideHintId}
                  labels={sideLabels}
                  value={selectedSide}
                  size="lg"
                  disabled={captainAction !== "side_pick" || acting}
                  onChange={(index) => chooseSide(selectedSide === index ? null : index)}
                />
              </CardContent>
            </Card>
          ) : assignStep ? (
            <PickBanAssignBoard
              kind={kind}
              encounterId={encounterId}
              state={state}
              itemsById={itemsById}
              isAdmin={isAdmin}
              queryKey={queryKey}
              teamName={teamName}
              header={header}
            />
          ) : (
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
              onSelect={selectTile}
              seats={seats}
              header={header}
              characterClasses={metadata.data?.discipline.character_classes}
            />
          )}

          {/* Under the grid, above the admin panel: the correction path a
              captain reaches for belongs next to the pool they misclicked, and
              it is the captains' own — an organizer's blunt reset is separate. */}
          <PickBanUndoControl
            kind={kind}
            encounterId={encounterId}
            undo={state.undo}
            viewerTeamId={viewerTeamId}
            itemsById={itemsById}
            sideLabels={sideLabels}
            seats={seats}
            invalidateKeys={[queryKey]}
          />

          {adminPanel?.(adminSlot)}
        </div>
      </div>

      {isSessionActive(session) ? (
        <PickBanCommandBar
          state={state}
          teamName={teamName}
          captainAction={state.is_complete ? null : captainAction}
          draft={
            isBlindStep && step != null && viewerTeamId != null ? (
              <PickBanDraftTray
                kind={kind}
                step={step}
                items={draftItems}
                locked={draftLocked}
                dirty={draftDirty}
                issues={state.draft_issues}
                locking={locking}
                itemsById={itemsById}
                targetName={targetName}
                opponentTeamId={opponentTeamId}
                opponentProgress={
                  opponentTeamId != null ? state.step_progress?.[opponentTeamId] : undefined
                }
                opponentName={opponentTeamId != null ? teamName(opponentTeamId) : ""}
                onRemove={removeDraftAt}
                onLock={lockDraft}
              />
            ) : null
          }
          draftOpen={isBlindStep && state.viewer_can_act && !draftLocked && !state.is_complete}
          kind={kind}
          selectedItemId={isSideStep ? selectedSide : selectedItemId}
          selectedItemName={
            isSideStep
              ? selectedSide != null
                ? (sideLabels[selectedSide] ?? `#${selectedSide}`)
                : null
              : selectedItemName
          }
          selectedItem={!isSideStep && selectedItemId != null ? itemsById[selectedItemId] : undefined}
          pending={acting}
          forMember={actingMemberName}
          onConfirm={confirm}
          onCancel={cancelSelection}
        />
      ) : null}

      <ElectOpenerDialog
        kind={kind}
        encounterId={encounterId}
        open={showElectOpener}
        seats={seats}
        queryKey={queryKey}
      />
    </>
  );
}
