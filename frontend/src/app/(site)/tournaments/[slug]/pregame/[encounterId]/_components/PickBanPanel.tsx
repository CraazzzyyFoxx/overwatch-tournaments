"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clock } from "lucide-react";

import { normalizeRole } from "@/lib/roster/player-role";
import { notify } from "@/lib/notify";
import pickBanService, { type PickBanActionInput } from "@/services/pickBan.service";
import type { Encounter } from "@/types/encounter.types";
import type { PickBanAction, PickBanKind, PickBanState } from "@/types/tournament.types";

import {
  attributeLocks,
  isSessionActive,
  pickBanReserveMap,
  type PickBanSide
} from "@/components/pick-ban/pick-ban-model";
import { PickBanCommandBar } from "@/components/pick-ban/PickBanCommandBar";
import { PickBanGrid, type PickBanItemLike } from "@/components/pick-ban/PickBanGrid";
import { PickBanStepTimeline } from "@/components/pick-ban/PickBanStepTimeline";
import { PickBanUndoControl } from "@/components/pick-ban/PickBanUndoControl";
import { ElectOpenerDialog } from "@/components/pick-ban/ElectOpenerDialog";
import { PregameAdminControls } from "./PregameAdminControls";

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

  const [pickedItemId, setSelectedItemId] = useState<number | null>(null);

  const selectedItemId =
    pickedItemId != null &&
    state.pool.some((entry) => entry.item_id === pickedItemId && entry.status === "available")
      ? pickedItemId
      : null;

  const actionMutation = useMutation({
    mutationFn: (input: PickBanActionInput) =>
      pickBanService.performPickBanAction(kind, encounterId, input),
    onSuccess: () => setSelectedItemId(null),
    onError: (error) => notify.apiError(error, { title: t("captain.actionFailed") }),
    onSettled: () => void queryClient.invalidateQueries({ queryKey })
  });

  const sideName = (side: PickBanSide) =>
    side === "home"
      ? (encounter.home_team?.name ?? t("side.home"))
      : (encounter.away_team?.name ?? t("side.away"));

  const captainAction: PickBanAction | null =
    state.viewer_can_act && state.allowed_actions.length > 0 ? state.allowed_actions[0] : null;
  const canSelect =
    isSessionActive(session) && !state.is_complete && (captainAction !== null || isAdmin);
  const selectedItemName =
    selectedItemId != null
      ? (itemsById[selectedItemId]?.name ?? t(`${kind}.itemNumber`, { id: selectedItemId }))
      : null;
  const allowProtect = state.sequence.some((token) => token.startsWith("protect_"));

  // Read off the SIDE ON THE CLOCK, not the viewer: the rule constrains whoever
  // is acting, so a captain, their opponent and a spectator all see the same
  // greyed-out tiles instead of three different pools.
  const locks = attributeLocks({
    pool: state.pool,
    uniqueAttribute: state.unique_attribute,
    action: state.expected_action,
    side: state.turn_side,
    currentRound: state.current_round,
    attributeOf: (itemId) => normalizeRole(itemsById[itemId]?.type ?? itemsById[itemId]?.role)
  });
  // Same reading, from the ledger instead of the round: what the side on the
  // clock already banned earlier in this SERIES and may not ban again
  // (`no_repeat_scope=encounter_same_side`). Those items stay in the pool, so
  // without this the only feedback was the 400 after the click. Gated on a BAN
  // step because the ledger is ban memory only: a `protect` on an item this
  // side already banned is legal and meaningful — the OPPONENT is not barred
  // from banning it — so it must stay clickable.
  const repeatBanned = new Set(state.expected_action === "ban" ? (state.repeat_banned ?? []) : []);

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
        <PickBanStepTimeline
          kind={kind}
          sequence={state.sequence}
          pool={state.pool}
          currentStepIndex={state.current_step_index}
          isComplete={state.is_complete}
          currentRound={state.current_round}
          itemsById={itemsById}
          sideName={sideName}
          session={session}
        />
        <div className="flex flex-col gap-4">
          <PickBanGrid
            kind={kind}
            pool={state.pool}
            itemsById={itemsById}
            selectedItemId={selectedItemId}
            canSelect={canSelect}
            currentRound={state.current_round}
            slotReserves={pickBanReserveMap(session)}
            repeatBanned={repeatBanned}
            locks={locks}
            onSelect={(itemId) =>
              setSelectedItemId((current) => (current === itemId ? null : itemId))
            }
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
              allowProtect={allowProtect}
              selectedItemId={selectedItemId}
              selectedItemName={selectedItemName}
              onMutated={() => {
                setSelectedItemId(null);
                void queryClient.invalidateQueries({ queryKey });
              }}
            />
          ) : null}
        </div>
      </div>

      {isSessionActive(session) ? (
        <PickBanCommandBar
          state={state}
          session={session}
          sideName={sideName}
          captainAction={state.is_complete ? null : captainAction}
          kind={kind}
          selectedItemId={selectedItemId}
          selectedItemName={selectedItemName}
          selectedItem={selectedItemId != null ? itemsById[selectedItemId] : undefined}
          pending={actionMutation.isPending}
          onConfirm={(itemId) => {
            if (captainAction != null)
              actionMutation.mutate({ item_id: itemId, action: captainAction });
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
