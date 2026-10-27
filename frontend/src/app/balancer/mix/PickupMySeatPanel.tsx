"use client";

import { Fragment, useState } from "react";
import { useTranslations } from "next-intl";
import { Coffee, Crown, DoorOpen, Headphones, LogIn, LogOut } from "lucide-react";

import { PickupRoleOrderEditor } from "@/app/balancer/mix/PickupRoleOrderEditor";
import { RoomLink } from "@/app/balancer/mix/_room/room-navigation";
import { LobbyCode } from "@/app/balancer/mix/_components/LobbyCodeStrip";
import { CAPTION_CLASS, CARD_TITLE_CLASS, lobbyLetter } from "@/app/balancer/mix/pickup-chrome";
import { HandleLabel } from "@/components/HandleLabel";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { cn } from "@/lib/utils";
import { roleOf, type RoleRef } from "@/lib/roster/role-ref";
import {
  type MixLobbyState,
  type MixSelfBlocker,
  type MixSelfSeat,
  type MixSelfState,
} from "@/services/custom-game.service";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";

import { resolveRoleOrder, roleRefsOf, toggleRole, type MixOwner, type MySeatTeam } from "./pickup-lineup";

/**
 * Blockers an account link fixes, and only those. Linking happens in account
 * settings, which is a modal on every page (`app/layout.tsx`), so the panel
 * opens it in place rather than navigating away from the board the player is
 * watching (the registration form does the same, `RegistrationSchemaForm`).
 */
const LINKABLE_BLOCKERS: Record<string, true> = {
  discord_not_linked: true,
  battlenet_not_linked: true,
  riot_not_linked: true,
  steam_not_linked: true,
  player_not_linked: true,
};

type PickupMySeatPanelProps = {
  state: MixSelfState;
  /** The mix owner's game: the roles on offer, their names/tints and the grid. */
  owner: MixOwner;
  saving: boolean;
  onJoin: () => void;
  onLeave: () => void;
  onSave: (patch: { roles: RoleRef[] | null; is_flex: boolean }) => void;
  /** The player's own team when a lobby seats them (G1); `null` while waiting or away. */
  myTeam: MySeatTeam | null;
  /** That lobby's next map, once rolled. */
  nextMapName: string | null;
  /** Their place in the waiting line (G2), 1-based; `null` when not waiting. */
  queuePosition: number | null;
  /** Every lobby's stage, for the waiting view. */
  lobbies: readonly { lobbyIndex: number; state: MixLobbyState }[];
  onSetAway: (away: boolean) => void;
  /** Their lobby's room while something plays out there (draft, bans and picks, the match); `null` otherwise. */
  roomHref: string | null;
};

/** Everything the panel edits before Save, kept apart from the server seat. */
type SeatDraft = { order: string[]; isFlex: boolean };

/** Ranks with no layer behind them are absent, which is what `resolveRoleOrder` reads. */
function rankedRoles(seat: MixSelfSeat): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [role, rank] of Object.entries(seat.ranks)) {
    if (rank != null) out[role] = rank;
  }
  return out;
}

function buildDraft(seat: MixSelfSeat | null, roles: readonly string[]): SeatDraft {
  if (seat == null) return { order: [], isFlex: false };
  return {
    order: resolveRoleOrder({ roles: seat.roles, ranks: rankedRoles(seat) }, roles),
    isFlex: seat.is_flex,
  };
}

/** The server seat as one comparable string, so a refetch that changed nothing leaves a draft alone. */
function signatureOf(seat: MixSelfSeat | null): string {
  if (seat == null) return "none";
  return `${seat.participation}|${seat.roles?.map(roleOf).join(",") ?? "all"}|${seat.is_flex}`;
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
 *
 * On a phone this is the player's whole view (spec §7.5): their team, its captain, the next map and their voice while
 * a lobby seats them (G1), their place in line and the lobbies' stages while they wait (G2), and Back while they are
 * away (G3).
 */
export function PickupMySeatPanel({
  state,
  owner,
  saving,
  onJoin,
  onLeave,
  onSave,
  myTeam,
  nextMapName,
  queuePosition,
  lobbies,
  onSetAway,
  roomHref,
}: Readonly<PickupMySeatPanelProps>) {
  const t = useTranslations("mixes.self");
  const tRoom = useTranslations("mixes.room");
  const tRoles = useTranslations("mixes.roleOrder");
  const openAccountSettings = useAccountSettingsModalStore((store) => store.open);
  const slotLabel = useSlotLabel(owner.ontology);

  const signature = signatureOf(state.seat);
  const [draft, setDraft] = useState<SeatDraft>(() => buildDraft(state.seat, owner.roles));
  // Reset during render (not in an effect) when the server's own seat changes:
  // React's pattern for state derived from a prop that should reset when the
  // prop's identity changes. A background refetch that changed nothing leaves
  // an edit in progress alone, because the signature is the same string.
  const [seenSignature, setSeenSignature] = useState(signature);
  if (signature !== seenSignature) {
    setSeenSignature(signature);
    setDraft(buildDraft(state.seat, owner.roles));
  }
  // A write that just settled: success already seeded the new seat, failure
  // left the old one -- either way the server's seat is the truth again.
  const [wasSaving, setWasSaving] = useState(saving);
  if (saving !== wasSaving) {
    setWasSaving(saving);
    if (!saving) setDraft(buildDraft(state.seat, owner.roles));
  }

  const { policy, seat } = state;
  // Off the roster the only question is joining; on it, the edit gate is the
  // live one and the join gate ("already in") is just how they got here.
  const blocker: MixSelfBlocker | null =
    seat == null ? policy.join_blocker : (policy.edit_blocker ?? policy.join_blocker);
  // `already_joined` is not a refusal, it is the state the panel already shows.
  const shownBlocker = blocker === "already_joined" ? null : blocker;
  const canLink = shownBlocker != null && LINKABLE_BLOCKERS[shownBlocker] === true;
  const editable = policy.can_edit_roles && seat != null && owner.dimension != null;
  const showFlex = owner.flex && draft.isFlex;
  // Read-only roles are one line; with no role on and no flex there is nothing to print under the hairline.
  const showRoles = editable || draft.order.length > 0 || showFlex;
  const dot = (
    <span aria-hidden="true" className="text-[color:var(--aqt-fg-dim)]">
      ·
    </span>
  );
  const commit = (next: SeatDraft) => {
    if (owner.dimension == null) return;
    setDraft(next);
    onSave({
      roles: roleRefsOf(next.order, owner.dimension),
      // A game without Full flex never sends one, which also clears a flag stored before it lost it.
      is_flex: owner.flex && next.isFlex,
    });
  };
  // Beside the title, the most specific thing that is true of this player: seated beats signed up, away beats both.
  const status =
    seat == null
      ? t("seat.none")
      : seat.away
        ? tRoom("away")
        : myTeam != null
          ? tRoom("yourTeam", { letter: lobbyLetter(myTeam.lobbyIndex), team: myTeam.teamName })
          : seat.current_lobby != null
            ? t("inLobby", { letter: lobbyLetter(seat.current_lobby) })
            : seat.participation === "pool"
              ? [t("waitingSeat"), queuePosition == null ? null : tRoom("queue", { position: queuePosition })]
                  .filter(Boolean)
                  .join(" · ")
              : t(`seat.${seat.participation}`);
  const rolesHint =
    owner.flex && draft.isFlex ? tRoles("flexOn") : seat?.roles == null ? t("rolesAllRanked") : tRoles("flexOff");
  const rolesHeading = (
    <>
      <Eyebrow>{t("rolesHeading")}</Eyebrow>
      {editable && owner.showsRoles ? <span className={CAPTION_CLASS}>{rolesHint}</span> : null}
    </>
  );

  return (
    <Card className="flex flex-col gap-3 px-4 py-3.5">
      {/* Who they are here, then every action they own in one row: the body below only reads. */}
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2">
        <h2 className={CARD_TITLE_CLASS}>{t("title")}</h2>
        <span
          className={cn(
            "text-caption",
            seat?.away ? "text-[color:var(--aqt-amber)]" : "text-[color:var(--aqt-fg-muted)]",
          )}
        >
          {status}
        </span>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {roomHref != null ? (
            <Button asChild variant="accent" size="sm">
              <RoomLink href={roomHref}>
                <DoorOpen aria-hidden="true" />
                {tRoom("openRoom")}
              </RoomLink>
            </Button>
          ) : null}
          {policy.can_join ? (
            <Button type="button" variant="accent" size="sm" disabled={saving} onClick={onJoin}>
              <LogIn aria-hidden="true" />
              {t("join")}
            </Button>
          ) : null}
          {myTeam != null && seat?.voice_url && !seat.away ? (
            <Button asChild variant="outline" size="sm">
              <a href={seat.voice_url} target="_blank" rel="noreferrer">
                <Headphones aria-hidden="true" />
                {tRoom("voice")}
              </a>
            </Button>
          ) : null}
          {seat != null && policy.can_set_away ? (
            <Button
              type="button"
              variant={seat.away ? "accent" : "outline"}
              size="sm"
              disabled={saving}
              onClick={() => onSetAway(!seat.away)}
            >
              <Coffee aria-hidden="true" />
              {seat.away ? tRoom("back") : tRoom("goAway")}
            </Button>
          ) : null}
          {policy.can_leave ? (
            <Button type="button" variant="outline" size="sm" disabled={saving} onClick={onLeave}>
              <LogOut aria-hidden="true" />
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
              size="sm"
              className="shrink-0"
              onClick={() => openAccountSettings("profile")}
            >
              {t("fixLinks")}
            </Button>
          ) : null}
        </div>
      ) : null}

      {state.unranked_roles.length > 0 ? (
        <p className="text-caption text-[color:var(--aqt-amber)]">
          {owner.showsRoles
            ? t("unranked", { roles: state.unranked_roles.map((role) => slotLabel(role)).join(", ") })
            : t("unrankedOne")}
        </p>
      ) : null}

      {seat == null ? null : seat.away ? (
        <p className="text-caption text-[color:var(--aqt-fg-muted)]">{tRoom("awayStatus")}</p>
      ) : myTeam != null ? (
        // The team as one inline roster (DESIGN §8): role glyph and nick, the captain's crown, the player in teal.
        <div className="space-y-1">
          <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-caption text-[color:var(--aqt-fg)]">
            {myTeam.members.map((member, index) => (
              <Fragment key={member.uuid}>
                {index > 0 ? dot : null}
                <span className="flex min-w-0 items-center gap-1">
                  <PlayerRoleIcon role={member.role} ontology={owner.ontology} size={14} />
                  <HandleLabel
                    handle={member.name}
                    className={member.isMe ? "font-semibold text-[color:var(--aqt-teal)]" : undefined}
                  />
                  {member.isCaptain ? (
                    <span role="img" aria-label={tRoom("captain")} className="flex shrink-0 items-center">
                      <Crown aria-hidden className="size-3.5 text-[color:var(--aqt-amber)]" />
                    </span>
                  ) : null}
                  {member.isMe ? <Eyebrow className="text-[color:var(--aqt-teal)]">{tRoom("you")}</Eyebrow> : null}
                </span>
              </Fragment>
            ))}
          </p>
          {nextMapName ? <p className={CAPTION_CLASS}>{tRoom("nextMap", { map: nextMapName })}</p> : null}
          {myTeam.lobbyCode ? (
            <p className={cn(CAPTION_CLASS, "flex flex-wrap items-center gap-1.5")}>
              {tRoom("lobbyCodeLabel")}
              <LobbyCode code={myTeam.lobbyCode} />
            </p>
          ) : null}
        </div>
      ) : state.lobby_count > 1 ? (
        // Waiting with several lobbies running: where each one is, so they can tell how soon a seat frees up.
        <p className="flex flex-wrap gap-x-3 gap-y-1">
          {lobbies.map((row) => (
            <span key={row.lobbyIndex} className={CAPTION_CLASS}>
              {`${lobbyLetter(row.lobbyIndex)} · ${tRoom(`state.${row.state}`)}`}
            </span>
          ))}
        </p>
      ) : null}

      {seat == null || !showRoles ? null : editable ? (
        <div className="border-t border-[color:var(--aqt-border)] pt-3">
          <PickupRoleOrderEditor
            owner={owner}
            order={draft.order}
            isFlex={draft.isFlex}
            disabled={saving}
            label={t("rolesOwner")}
            layout="row"
            heading={rolesHeading}
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
      ) : (
        // Read-only: no disabled editor, only what the balancer reads -- the on roles in priority order.
        <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 border-t border-[color:var(--aqt-border)] pt-3 text-caption text-[color:var(--aqt-fg-muted)]">
          {rolesHeading}
          {draft.order.map((role, index) => (
            <Fragment key={role}>
              {index > 0 ? dot : null}
              <span className="flex items-center gap-1">
                <PlayerRoleIcon role={role} ontology={owner.ontology} size={15} />
                <span className="aqt-tnum font-semibold text-[color:var(--aqt-fg)]">{seat.ranks[role] ?? "—"}</span>
              </span>
            </Fragment>
          ))}
          {showFlex ? (
            <>
              {draft.order.length > 0 ? dot : null}
              <span>{tRoles("fullFlex")}</span>
            </>
          ) : null}
        </p>
      )}
    </Card>
  );
}
