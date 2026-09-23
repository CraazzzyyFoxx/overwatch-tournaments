"use client";

import { useState } from "react";
import { Crown, Heart, Loader2, WifiOff, X } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import DivisionIcon from "@/components/DivisionIcon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useDraftPlayerCardQuery, type DraftMutations } from "@/hooks/useDraftData";
import { usePickCountdown } from "@/hooks/usePickCountdown";
import { describeApiError } from "@/lib/api/error";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/divisions/grid";
import type { DraftGating } from "@/lib/draft/logic";
import {
  turnsUntil,
  type PickTarget,
  type QueueControls,
  type RoomSelection,
  type TeamView
} from "@/lib/draft/room-model";
import { playerRoles, rosterRoleForPlayer } from "@/lib/draft/workspace-model";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type { DraftAutopickPreview, DraftBoard, DraftPlayer, DraftRole } from "@/types/draft.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { formatSubRoleLabel, getPlayerSlug } from "@/utils/player";

import { CareerStats, CareerTables } from "./island/PlayerCareer";
import { RegistrationSection } from "./island/RegistrationSection";
import { RoleTiles } from "./island/RoleTiles";
import { actionBorder, clockColor, isMyTurnFor } from "./PickPill";

interface PickIslandProps {
  board: DraftBoard;
  gating: DraftGating;
  /** Card subject; null → the island is closed and PickPill renders instead (when the seat can act). */
  player: DraftPlayer | null;
  selection: RoomSelection | null;
  onSelectRole: (role: DraftRole) => void;
  onClose: () => void;
  actingTeam: TeamView | null;
  overrideMode: boolean;
  /** captain_admin while another team is on the clock. */
  showTargets: boolean;
  target: PickTarget;
  onTargetChange: (target: PickTarget) => void;
  canConfirm: boolean;
  connectionState: RealtimeConnectionState;
  mutations: DraftMutations;
  autopickPreview: DraftAutopickPreview | null;
  queue: QueueControls | null;
  divisionGrid: DivisionGrid;
  /** After a successful pick/override: clear selection and card. */
  onPicked: () => void;
}

const ICON_BUTTON =
  "flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] outline-none hover:bg-[color:var(--aqt-overlay-3)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]";

/**
 * The floating player card and, for a seat that can act on this player, the
 * pick action. Stays mounted with `player = null` so the result announcement
 * outlives the card closing on a successful pick.
 */
export function PickIsland(props: Readonly<PickIslandProps>) {
  const { board, gating, player, selection, onSelectRole, onClose, actingTeam, overrideMode } = props;
  const { showTargets, target, onTargetChange, queue, divisionGrid } = props;
  const t = useTranslations("draftRedesign");
  const [announcement, setAnnouncement] = useState("");
  const cardQuery = useDraftPlayerCardQuery(player?.user_id ?? null);

  const liveRegion = (
    <p className="sr-only" aria-live="polite">
      {announcement}
    </p>
  );
  if (!player) return liveRegion;

  const displayName = player.battle_tag ?? `#${player.id}`;
  const available = player.status === "available";
  const profileSlug = player.battle_tag ? getPlayerSlug(player.battle_tag) : null;
  const headerDivision = resolveDivisionFromRank(divisionGrid, player.effective_rank);
  const myTurn = isMyTurnFor(gating, actingTeam);
  const hasAccount = player.user_id != null;
  const cardPending = hasAccount && cardQuery.isPending;

  const draftedTeam = board.teams.find((team) => team.id === player.drafted_by_team_id) ?? null;
  const draftedRole = draftedTeam && !player.is_captain ? rosterRoleForPlayer(player, board.picks) : null;
  const statusText = available
    ? t("island.status.available")
    : player.status === "removed" || !draftedTeam
      ? t("profile.removed")
      : player.is_captain
        ? t("island.status.captain", { team: draftedTeam.name })
        : draftedRole
          ? t("island.status.pickedRole", { team: draftedTeam.name, role: t(`roles.${draftedRole}`) })
          : t("island.status.picked", { team: draftedTeam.name });

  const priorityLine = playerRoles(player)
    .map((role, index) => {
      const subRole = formatSubRoleLabel(player.role_sub_roles?.[role]);
      return subRole
        ? t("island.rolePriorityItemSub", { n: index + 1, role: t(`roles.${role}`), subRole })
        : t("island.rolePriorityItem", { n: index + 1, role: t(`roles.${role}`) });
    })
    .join(" · ");

  const myTeamName = board.teams.find((team) => team.id === gating.myTeamId)?.name ?? t("myTeam");
  const clockTeamName =
    board.teams.find((team) => team.id === board.current_pick?.draft_team_id)?.name ?? "—";
  const queued = queue?.ids.includes(player.id) ?? false;

  return (
    <>
      {liveRegion}
      <div
        role="dialog"
        aria-label={t("island.aria", { player: displayName })}
        className="flex max-h-[85svh] w-full flex-col overflow-hidden rounded-t-2xl border bg-[color:var(--aqt-card-2)] shadow-[0_18px_50px_rgb(0_0_0/0.45)] sm:max-h-[calc(100svh-40px)] sm:rounded-2xl"
        style={{ borderColor: actionBorder(board, myTurn, overrideMode) }}
      >
        <div className="flex flex-wrap items-center gap-3 px-3.5 pb-2.5 pt-3">
          {headerDivision != null && (
            <span className="shrink-0" title={getDivisionLabel(divisionGrid, headerDivision) ?? undefined}>
              <DivisionIcon
                division={headerDivision}
                tournamentGrid={divisionGrid}
                width={52}
                height={52}
                className="h-[52px] w-[52px] object-contain"
              />
            </span>
          )}
          <div className="min-w-0 flex-1">
            <p
              className="text-xs font-semibold uppercase tracking-[0.08em]"
              style={{ color: available ? "var(--aqt-teal)" : "var(--aqt-fg-muted)" }}
            >
              {statusText}
            </p>
            <div className="mt-0.5 flex min-w-0 items-center gap-2">
              <h2 className="min-w-0 truncate font-onest text-xl font-semibold leading-tight tracking-[-0.01em]">
                {profileSlug ? (
                  <Link
                    href={`/users/${profileSlug}`}
                    className="rounded hover:text-[color:var(--aqt-teal)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
                  >
                    {displayName}
                  </Link>
                ) : (
                  displayName
                )}
              </h2>
              {player.is_captain && (
                <Crown
                  className="h-[18px] w-[18px] shrink-0 text-[color:var(--aqt-warm)]"
                  role="img"
                  aria-label={t("captain")}
                />
              )}
              {player.is_flex && (
                <span className="shrink-0 rounded border border-[color:var(--aqt-border-2)] px-1.5 text-xs font-medium uppercase tracking-[0.08em] text-[color:var(--aqt-fg-muted)]">
                  {t("flex")}
                </span>
              )}
              {player.primary_role == null && (
                <span className="shrink-0 rounded border border-[color:var(--aqt-border-2)] px-1.5 text-xs font-medium uppercase tracking-[0.08em] text-[color:var(--aqt-fg-muted)]">
                  {t("noRole")}
                </span>
              )}
            </div>
            {priorityLine && (
              <p className="mt-0.5 truncate text-sm text-[color:var(--aqt-fg-muted)]" title={priorityLine}>
                {t("island.rolePriority", { roles: priorityLine })}
              </p>
            )}
          </div>
          {showTargets && (
            <ToggleGroup
              type="single"
              variant="pill"
              value={target}
              onValueChange={(value) => onTargetChange(value as PickTarget)}
              aria-label={t("island.targets.label")}
              className="order-last w-full sm:order-none sm:w-auto"
            >
              <ToggleGroupItem value="mine">{t("island.targets.mine", { team: myTeamName })}</ToggleGroupItem>
              <ToggleGroupItem value="clock">{t("island.targets.clock", { team: clockTeamName })}</ToggleGroupItem>
            </ToggleGroup>
          )}
          {queue && available && (
            <button
              type="button"
              aria-pressed={queued}
              aria-label={queued ? t("island.queue.remove") : t("island.queue.add")}
              title={queued ? t("island.queue.remove") : t("island.queue.add")}
              onClick={() => queue.toggle(player.id)}
              className={ICON_BUTTON}
              style={{ color: queued ? "var(--aqt-teal)" : "var(--aqt-fg-muted)" }}
            >
              <Heart className="h-5 w-5" fill={queued ? "currentColor" : "none"} aria-hidden />
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label={t("island.close")}
            className={cn(ICON_BUTTON, "text-[color:var(--aqt-fg-muted)]")}
          >
            <X className="h-[18px] w-[18px]" aria-hidden />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain border-t border-[color:var(--aqt-border)]">
          {hasAccount && <CareerStats query={cardQuery} />}
          <RoleTiles
            player={player}
            selection={selection}
            onSelectRole={onSelectRole}
            actingTeam={actingTeam}
            card={cardQuery.data ?? null}
            cardPending={cardPending}
            divisionGrid={divisionGrid}
          />
          {hasAccount && <CareerTables card={cardQuery.data} pending={cardPending} divisionGrid={divisionGrid} />}
          <RegistrationSection player={player} />
        </div>

        {actingTeam != null && available && (
          <IslandFooter
            {...props}
            player={player}
            actingTeam={actingTeam}
            myTurn={myTurn}
            onAnnounce={setAnnouncement}
          />
        )}
      </div>
    </>
  );
}

interface IslandFooterProps extends PickIslandProps {
  player: DraftPlayer;
  actingTeam: TeamView;
  myTurn: boolean;
  onAnnounce: (message: string) => void;
}

function IslandFooter({
  board,
  gating,
  player,
  selection,
  actingTeam,
  overrideMode,
  canConfirm,
  connectionState,
  mutations,
  autopickPreview,
  queue,
  onPicked,
  myTurn,
  onAnnounce
}: Readonly<IslandFooterProps>) {
  const t = useTranslations("draftRedesign");
  const [note, setNote] = useState("");
  const current = board.current_pick;
  const countdown = usePickCountdown(current, board.session.status === "paused");
  const isConnected = connectionState === "connected";
  const displayName = player.battle_tag ?? `#${player.id}`;
  // The action is about the card's player: a selection of somebody else is not confirmable from here.
  const chosen = selection?.playerId === player.id ? selection : null;
  const withRole = board.session.roster_shape.has_role_slots;
  const pickPending = mutations.makePick.isPending;
  const overridePending = mutations.override.isPending;

  const actionLabel = (kind: "pick" | "override") =>
    !chosen
      ? t(`island.action.${kind}Empty`)
      : withRole
        ? t(`island.action.${kind}Role`, { player: displayName, role: chosen.role })
        : t(`island.action.${kind}Player`, { player: displayName });

  const announceError = (error: unknown) => {
    // Both: the toast is what a sighted captain notices, the live region is what a screen reader gets.
    const described = describeApiError(error);
    onAnnounce([described.title, described.description].filter(Boolean).join(". "));
    notify.apiError(error);
  };

  const confirm = () => {
    if (!canConfirm || pickPending || !current || !chosen) return;
    mutations.makePick.mutate(
      { pickId: current.id, playerId: player.id, version: current.version, role: chosen.role },
      {
        onSuccess: () => {
          const message = t("pickSuccess", { player: displayName });
          onAnnounce(message);
          notify.success(message);
          onPicked();
        },
        onError: announceError
      }
    );
  };

  const applyOverride = () => {
    const reason = note.trim();
    if (!current || !chosen || reason.length === 0 || overridePending) return;
    mutations.override.mutate(
      { pickId: current.id, playerId: player.id, version: current.version, role: chosen.role, note: reason },
      {
        onSuccess: () => {
          const message = t("overrideSuccess", { player: displayName });
          onAnnounce(message);
          notify.success(message);
          setNote("");
          onPicked();
        },
        onError: announceError
      }
    );
  };

  let hint: string | null = null;
  if (!overrideMode && gating.myTeamId != null) {
    const previewName = autopickPreview
      ? (board.players.find((entry) => entry.id === autopickPreview.player_id)?.battle_tag ?? null)
      : null;
    if (current != null && turnsUntil(board, gating.myTeamId) == null) hint = t("island.hint.noPicksLeft");
    else if (myTurn && chosen)
      hint = previewName ? t("island.hint.confirmAutopick", { player: previewName }) : t("island.hint.confirm");
    else if (myTurn)
      hint = previewName
        ? autopickPreview?.source === "queue"
          ? t("island.hint.autopickQueue", { player: previewName })
          : t("island.hint.autopickFit", { player: previewName })
        : t("island.hint.chooseRole");
    else hint = queue && queue.ids.length > 0 ? t("island.hint.prepareQueue") : t("island.hint.prepare");
  }
  const captainTag = actingTeam.roster.find((entry) => entry.is_captain)?.battle_tag ?? actingTeam.team.name;

  return (
    <div className="border-t border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] px-3.5 pb-3 pt-2.5">
      {overrideMode && (
        <p className="mb-2 text-xs text-[color:var(--aqt-amber)]">{t("island.hint.override", { captain: captainTag })}</p>
      )}
      <div className="flex flex-wrap items-center gap-3.5 sm:flex-nowrap">
        <span
          className="min-w-12 font-onest text-[17px] font-bold tabular-nums"
          style={{ color: clockColor(board, myTurn, countdown.overtime) }}
        >
          {countdown.text ?? "—"}
        </span>

        {overrideMode && board.session.allow_admin_override && (
          // The reason is the audit trail for taking a pick from a captain: required.
          <Input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder={t("island.overrideNotePlaceholder")}
            aria-label={t("island.overrideNoteLabel")}
            required
            className="h-10 min-w-0 flex-1 bg-[color:var(--aqt-bg-2)]"
          />
        )}

        {/* About confirming MY pick (live options); an override needs neither. */}
        {!isConnected && !overrideMode ? (
          <p className="flex min-w-0 flex-1 items-center gap-2 text-[13px] text-[color:var(--aqt-warm)]">
            <WifiOff className="h-4 w-4 shrink-0" aria-hidden />
            <span className="line-clamp-2">{t("waitingFreshData")}</span>
          </p>
        ) : overrideMode && !board.session.allow_admin_override ? (
          <p className="min-w-0 flex-1 text-[13px] text-[color:var(--aqt-fg-muted)]">{t("overrideDisabled")}</p>
        ) : hint ? (
          <p className="line-clamp-2 min-w-0 flex-1 text-[13px] leading-snug text-[color:var(--aqt-fg-muted)]" title={hint}>
            {hint}
          </p>
        ) : null}

        {overrideMode ? (
          board.session.allow_admin_override && (
            <Button
              variant="outline"
              className="min-h-11 w-full shrink-0 sm:w-auto"
              disabled={!chosen || note.trim().length === 0 || overridePending}
              onClick={applyOverride}
            >
              {overridePending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />
              )}
              {actionLabel("override")}
            </Button>
          )
        ) : myTurn ? (
          <Button
            data-draft-confirm=""
            className={cn(
              "min-h-11 w-full shrink-0 sm:w-auto",
              !isConnected &&
                "bg-[color:var(--aqt-warm)] text-[color:var(--aqt-bg)] hover:bg-[color:var(--aqt-warm)]/90"
            )}
            disabled={!canConfirm || pickPending || !chosen}
            onClick={confirm}
          >
            {pickPending && <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />}
            {actionLabel("pick")}
          </Button>
        ) : (
          <Button className="min-h-11 w-full shrink-0 sm:w-auto" disabled>
            {t("island.action.wait")}
          </Button>
        )}
      </div>
    </div>
  );
}
