"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { LogIn, LogOut } from "lucide-react";

import { PickupRoleOrderEditor } from "@/app/balancer/mix/PickupRoleOrderEditor";
import { CAPTION_CLASS, EYEBROW_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { PANEL_CLASS } from "@/components/balancer/balancer-page-helpers";
import { Button } from "@/components/ui/button";
import { ROLE_LABELS, type RoleCode } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import {
  type MixSelfBlocker,
  type MixSelfSeat,
  type MixSelfState,
} from "@/services/custom-game.service";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";

import { resolveRoleOrder, toggleRole } from "./pickup-lineup";

/**
 * Blockers an account link fixes, and only those. Linking happens in account
 * settings, which is a modal on every page (`app/layout.tsx`), so the panel
 * opens it in place rather than navigating away from the board the player is
 * watching (the registration form does the same, `RegistrationSchemaForm`).
 */
const LINKABLE_BLOCKERS: Record<string, true> = {
  discord_not_linked: true,
  battlenet_not_linked: true,
  player_not_linked: true,
};

type PickupMySeatPanelProps = {
  state: MixSelfState;
  saving: boolean;
  onJoin: () => void;
  onLeave: () => void;
  onSave: (patch: { roles: RoleCode[] | null; is_flex: boolean }) => void;
};

/** Everything the panel edits before Save, kept apart from the server seat. */
type SeatDraft = { order: RoleCode[]; isFlex: boolean };

/** Ranks with no layer behind them are absent, which is what `resolveRoleOrder` reads. */
function rankedRoles(seat: MixSelfSeat): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [role, rank] of Object.entries(seat.ranks)) {
    if (rank != null) out[role] = rank;
  }
  return out;
}

function buildDraft(seat: MixSelfSeat | null): SeatDraft {
  if (seat == null) return { order: [], isFlex: false };
  return {
    order: resolveRoleOrder({ roles: seat.roles, ranks: rankedRoles(seat) }),
    isFlex: seat.is_flex,
  };
}

/** The server seat as one comparable string, so a refetch that changed nothing leaves a draft alone. */
function signatureOf(seat: MixSelfSeat | null): string {
  if (seat == null) return "none";
  return `${seat.participation}|${seat.roles?.join(",") ?? "all"}|${seat.is_flex}`;
}

/**
 * The player's own corner of a public mix board: where they stand, and the two
 * things they own -- being in the lineup at all, and the order their roles are
 * tried in.
 *
 * Presentational on purpose, like every other panel on this screen: the seat
 * read and its three writes live in `usePickupMix`, so the realtime echo that
 * refreshes the board refreshes this with it.
 *
 * Every role edit is written the moment it is made -- a toggle, a drop, the
 * flex switch are each one deliberate action, so there is nothing to batch
 * behind a Save button. The draft shows the edit while it is in flight and is
 * re-read from the server when the write settles, so a refused write snaps
 * back instead of leaving the screen claiming an order the balancer never got.
 *
 * Ranks are printed, never edited. A mix resolves ranks against the HOST's own
 * book (`author_user_id = game.host_user_id`), so a field here would write a
 * number the balance never reads -- the spec's "игрок правит только `roles` и
 * `is_flex`".
 */
export function PickupMySeatPanel({
  state,
  saving,
  onJoin,
  onLeave,
  onSave,
}: Readonly<PickupMySeatPanelProps>) {
  const t = useTranslations("mixes.self");
  const openAccountSettings = useAccountSettingsModalStore((store) => store.open);

  const signature = signatureOf(state.seat);
  const [draft, setDraft] = useState<SeatDraft>(() => buildDraft(state.seat));
  // Reset during render (not in an effect) when the server's own seat changes:
  // React's pattern for state derived from a prop that should reset when the
  // prop's identity changes. A background refetch that changed nothing leaves
  // an edit in progress alone, because the signature is the same string.
  const [seenSignature, setSeenSignature] = useState(signature);
  if (signature !== seenSignature) {
    setSeenSignature(signature);
    setDraft(buildDraft(state.seat));
  }
  // A write that just settled: success already seeded the new seat, failure
  // left the old one -- either way the server's seat is the truth again.
  const [wasSaving, setWasSaving] = useState(saving);
  if (saving !== wasSaving) {
    setWasSaving(saving);
    if (!saving) setDraft(buildDraft(state.seat));
  }

  const { policy, seat } = state;
  // Off the roster the only question is joining; on it, the edit gate is the
  // live one and the join gate ("already in") is just how they got here.
  const blocker: MixSelfBlocker | null =
    seat == null ? policy.join_blocker : (policy.edit_blocker ?? policy.join_blocker);
  // `already_joined` is not a refusal, it is the state the panel already shows.
  const shownBlocker = blocker === "already_joined" ? null : blocker;
  const canLink = shownBlocker != null && LINKABLE_BLOCKERS[shownBlocker] === true;
  const editable = policy.can_edit_roles && seat != null;
  const commit = (next: SeatDraft) => {
    setDraft(next);
    onSave({ roles: next.order, is_flex: next.isFlex });
  };

  return (
    <div className={cn(PANEL_CLASS, "flex flex-col gap-3 px-4 py-3.5")}>
      <div className="flex flex-wrap items-center gap-2.5">
        <span className={EYEBROW_CLASS}>{t("title")}</span>
        <span className="text-caption font-semibold text-[color:var(--aqt-fg)]">
          {seat == null ? t("seat.none") : t(`seat.${seat.participation}`)}
        </span>
        {state.lobby_count > 1 && seat != null ? (
          // Two lobbies means two games at once: "signed up" no longer says
          // which one is theirs, or whether a balance has seated them at all.
          <span className={CAPTION_CLASS}>
            {seat.current_lobby == null
              ? t("waitingSeat")
              : t("inLobby", { letter: "AB"[seat.current_lobby] })}
          </span>
        ) : null}

        <div className="ml-auto flex items-center gap-2">
          {policy.can_join ? (
            <Button type="button" className="h-9 shrink-0" disabled={saving} onClick={onJoin}>
              <LogIn className="mr-1.5 size-3.5" aria-hidden="true" />
              {t("join")}
            </Button>
          ) : null}
          {policy.can_leave ? (
            <Button
              type="button"
              variant="outline"
              className="h-9 shrink-0 text-[color:var(--aqt-fg-muted)] hover:border-[color:color-mix(in_srgb,var(--aqt-rose)_40%,transparent)] hover:text-rose-200"
              disabled={saving}
              onClick={onLeave}
            >
              <LogOut className="mr-1.5 size-3.5" aria-hidden="true" />
              {t("leave")}
            </Button>
          ) : null}
        </div>
      </div>

      {shownBlocker ? (
        <div className="flex flex-wrap items-center gap-2.5">
          <p className="text-caption text-[color:var(--aqt-fg-muted)]">
            {t(`blocker.${shownBlocker}`)}
          </p>
          {canLink ? (
            <Button
              type="button"
              variant="outline"
              className="h-8 shrink-0"
              onClick={() => openAccountSettings("profile")}
            >
              {t("fixLinks")}
            </Button>
          ) : null}
        </div>
      ) : null}

      {state.unranked_roles.length > 0 ? (
        <p className="text-caption text-amber-200">
          {t("unranked", {
            roles: state.unranked_roles.map((role) => ROLE_LABELS[role] ?? role).join(", "),
          })}
        </p>
      ) : null}

      {seat == null ? null : (
        <div className="space-y-2">
          {seat.roles == null ? <p className={CAPTION_CLASS}>{t("rolesAllRanked")}</p> : null}
          <PickupRoleOrderEditor
            order={draft.order}
            isFlex={draft.isFlex}
            disabled={!editable || saving}
            label="you"
            layout="grid"
            onReorder={(order) => commit({ ...draft, order })}
            onToggle={(role) => commit({ ...draft, order: toggleRole(draft.order, role) })}
            onFlexChange={(isFlex) => commit({ ...draft, isFlex })}
            rankFor={(role) => ({
              rankValue: seat.ranks[role] ?? null,
              sourceLabel: null,
              onChange: null,
              onClear: null,
            })}
          />
        </div>
      )}
    </div>
  );
}
