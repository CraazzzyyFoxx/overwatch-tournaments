"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Pause, Play } from "lucide-react";

import { useTurnAlert } from "@/app/balancer/mix/_hooks/useTurnAlert";
import { teamAccent } from "@/app/balancer/mix/pickup-chrome";
import { playerLabel, type MixOwner } from "@/app/balancer/mix/pickup-lineup";
import { HandleLabel } from "@/components/HandleLabel";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { RankCrest } from "@/components/RankCrest";
import { Button } from "@/components/ui/button";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { OverlayBar } from "@/components/ui/overlay-bar";
import { RowButton } from "@/components/ui/row-button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import type { DraftMutations } from "@/hooks/useDraftData";
import { usePickCountdown } from "@/hooks/usePickCountdown";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { canConfirmPick, type DraftGating } from "@/lib/draft/logic";
import { playerRoles } from "@/lib/draft/workspace-model";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type { CustomGamePlayer } from "@/services/custom-game.service";
import type { DraftBoard, DraftPickOptionsResponse } from "@/types/draft.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";

import { draftPlayerName, playerTransitionName, poolPlayers, type PoolPlayer } from "./room-model";

const NONE = "none";
const ALL = "all";
/** The reasons a refused player is labelled with; anything else reads as the generic one. */
const REASONS: Record<string, "slot_filled" | "role_shortage" | "no_slot"> = {
  slot_filled: "slot_filled",
  role_shortage: "role_shortage",
  no_slot: "no_slot"
};

/**
 * The draft in the room's centre (spec §9.3): who is on the clock, the snake order, and the pool. The captain on the
 * clock taps a player, the bar at the bottom confirms the pick (with the role, when the player fits more than one);
 * players the team cannot seat now are dimmed with the reason. Before the start a host checks the captains and starts
 * it here; a waiting player can join a draft short of a role.
 */
export function RoomDraftStage({
  board,
  teamNames,
  owner,
  gating,
  options,
  connectionState,
  mutations,
  canHost,
  myMemberId,
  waiting,
  adding,
  onAddPlayer
}: Readonly<{
  board: DraftBoard;
  /** The lobby's team names by position (the draft's pick position order). */
  teamNames: readonly string[];
  owner: MixOwner;
  gating: DraftGating;
  /** The captain's pick options for the pick on the clock; null for anyone else. */
  options: DraftPickOptionsResponse | null;
  connectionState: RealtimeConnectionState;
  mutations: DraftMutations;
  canHost: boolean;
  myMemberId: number | null;
  /** Present pool players no lobby seats: who a host may add to the draft. */
  waiting: readonly CustomGamePlayer[];
  adding: boolean;
  onAddPlayer: (workspaceMemberId: number) => void;
}>) {
  const t = useTranslations("mixes.arena.draft");
  const tDraft = useTranslations("mixes.draft");
  const slotLabel = useSlotLabel(owner.ontology);
  const session = board.session;
  const current = board.current_pick;
  const status = session.status;
  const setup = status === "setup" || status === "ready";
  const paused = status === "paused";
  const myPick = gating.isMyPick;
  useTurnAlert(myPick, tDraft("yourPickTitle"), String(current?.id ?? ""));
  const countdown = usePickCountdown(status === "live" ? current : null, paused);

  const positions = [...board.teams].sort((left, right) => left.draft_position - right.draft_position);
  const teamIndex = (teamId: number) => positions.findIndex((team) => team.id === teamId);
  const clockTeam = current != null ? teamIndex(current.draft_team_id) : -1;
  const clockName = clockTeam >= 0 ? (teamNames[clockTeam] ?? positions[clockTeam]?.name ?? "") : "";

  const [roleFilter, setRoleFilter] = useState<string>(ALL);
  const [selection, setSelection] = useState<{ pickId: number; playerId: number; role: string } | null>(null);
  const pool = poolPlayers(board, myPick ? options : null);
  const shown = roleFilter === ALL ? pool : pool.filter((entry) => playerRoles(entry.player).includes(roleFilter));
  const chosen =
    selection != null && current != null && selection.pickId === current.id
      ? (pool.find((entry) => entry.player.id === selection.playerId && entry.roles.includes(selection.role)) ?? null)
      : null;
  const chosenRole = chosen != null && selection != null ? selection.role : null;
  const confirmable =
    myPick &&
    current != null &&
    chosen != null &&
    chosenRole != null &&
    canConfirmPick(connectionState, current.version, options, { playerId: chosen.player.id, role: chosenRole });

  const choose = (entry: PoolPlayer) => {
    if (current == null || entry.roles.length === 0) return;
    setSelection((previous) =>
      previous?.pickId === current.id && previous.playerId === entry.player.id
        ? null
        : { pickId: current.id, playerId: entry.player.id, role: entry.roles[0] }
    );
  };

  const confirm = () => {
    if (!confirmable || current == null || chosen == null || chosenRole == null) return;
    mutations.makePick.mutate(
      {
        pickId: current.id,
        playerId: chosen.player.id,
        version: current.version,
        role: chosenRole,
        dimension: session.roster_shape.dimension
      },
      { onSuccess: () => setSelection(null), onError: (error) => notify.apiError(error) }
    );
  };

  const start = () =>
    mutations.lifecycle.mutate(
      { sessionId: session.id, action: "start" },
      {
        onSuccess: () => notify.success(tDraft("started")),
        onError: (error) => notify.apiError(error)
      }
    );

  const headline = setup
    ? t("setupTitle")
    : paused
      ? t("paused")
      : status === "live" && current != null
        ? myPick
          ? t("yourTurn")
          : t("turn", { team: clockName })
        : t("done");
  const detail = setup
    ? canHost
      ? t("setupHintHost")
      : t("setupHint")
    : paused && session.blocked_reason === "role_shortage"
      ? t("blocked")
      : status === "live" && current != null
        ? t("pickOf", { n: current.overall_no, total: board.picks.length })
        : null;
  const picks = [...board.picks].sort((left, right) => left.overall_no - right.overall_no);
  const roleColumns = owner.showsRoles ? owner.roles : [];

  return (
    <div className="flex flex-col gap-3">
      <div
        className={cn(
          "flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border bg-[color:var(--aqt-card)] px-3.5 py-3",
          myPick ? "border-[color:var(--aqt-teal)]/60" : "border-[color:var(--aqt-border)]"
        )}
      >
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 font-display text-ui font-semibold text-[color:var(--aqt-fg)]">
            {paused ? <Pause aria-hidden className="size-4 text-[color:var(--aqt-amber)]" /> : null}
            {headline}
          </p>
          {detail != null ? <p className="text-caption text-[color:var(--aqt-fg-muted)]">{detail}</p> : null}
        </div>
        {countdown.text != null ? (
          <span
            role="timer"
            aria-label={t("clock")}
            className={cn(
              "font-display text-title font-bold tabular-nums",
              countdown.overtime ? "text-[color:var(--aqt-amber)]" : "text-[color:var(--aqt-teal)]"
            )}
          >
            {countdown.text}
          </span>
        ) : null}
        {canHost && setup ? (
          <Button type="button" disabled={mutations.lifecycle.isPending} onClick={start}>
            {mutations.lifecycle.isPending ? (
              <Spinner className="mr-1.5 size-3.5" />
            ) : (
              <Play className="mr-1.5 size-3.5" aria-hidden="true" />
            )}
            {tDraft("startDraft")}
          </Button>
        ) : null}
        {canHost && waiting.length > 0 && (setup || paused) ? (
          <Select
            value={NONE}
            disabled={adding}
            onValueChange={(value) => value !== NONE && onAddPlayer(Number(value))}
          >
            <SelectTrigger aria-label={tDraft("addPlayer")} size="sm" className="w-48">
              <SelectValue placeholder={tDraft("addPlayer")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>{tDraft("addPlayer")}</SelectItem>
              {waiting.map((row) => (
                <SelectItem key={row.workspace_member_id} value={String(row.workspace_member_id)}>
                  {playerLabel(row)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
        {picks.length > 0 ? (
          <ol aria-label={t("order")} className="flex w-full flex-wrap gap-1">
            {picks.map((pick) => {
              const index = teamIndex(pick.draft_team_id);
              const done = pick.status === "completed" || pick.status === "autopicked" || pick.status === "skipped";
              const onClock = pick.status === "on_clock";
              return (
                <li
                  key={pick.id}
                  aria-current={onClock ? "step" : undefined}
                  title={teamNames[index] ?? ""}
                  className={cn(
                    "flex h-6 min-w-7 items-center justify-center gap-1 rounded-md border px-1.5 text-label font-semibold tabular-nums",
                    onClock
                      ? "border-[color:var(--aqt-teal)] text-[color:var(--aqt-teal)]"
                      : "border-[color:var(--aqt-border)]",
                    done ? "text-[color:var(--aqt-fg-faint)]" : onClock ? null : "text-[color:var(--aqt-fg-muted)]"
                  )}
                >
                  <span aria-hidden="true" className={cn("h-2.5 w-[3px] rounded-sm", teamAccent(index).bar, done && "opacity-40")} />
                  {String.fromCharCode(65 + Math.max(index, 0))}
                </li>
              );
            })}
          </ol>
        ) : null}
      </div>

      {roleColumns.length > 1 ? (
        <FilterChipGroup label={t("roleFilter")}>
          <FilterChip active={roleFilter === ALL} count={pool.length} onClick={() => setRoleFilter(ALL)}>
            {t("allRoles")}
          </FilterChip>
          {roleColumns.map((role) => (
            <FilterChip
              key={role}
              active={roleFilter === role}
              count={pool.filter((entry) => playerRoles(entry.player).includes(role)).length}
              onClick={() => setRoleFilter(role)}
            >
              {slotLabel(role)}
            </FilterChip>
          ))}
        </FilterChipGroup>
      ) : null}

      <ul aria-label={t("poolTitle")} className="grid grid-cols-1 gap-2 sm:grid-cols-2 2xl:grid-cols-3">
        {shown.map((entry) => (
          <PoolCard
            key={entry.player.id}
            entry={entry}
            owner={owner}
            mine={myMemberId != null && entry.player.workspace_member_id === myMemberId}
            choosing={myPick}
            selected={chosen?.player.id === entry.player.id}
            onChoose={() => choose(entry)}
          />
        ))}
      </ul>

      {status === "live" || paused ? (
        <OverlayBar tone={myPick ? "active" : "neutral"} ariaLabel={t("bar")} className="lg:w-[min(720px,52vw)]">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <div className="min-w-0 flex-1">
              <p className="truncate text-body font-semibold text-[color:var(--aqt-fg)]">{headline}</p>
              {myPick && connectionState !== "connected" ? (
                <p className="text-caption text-[color:var(--aqt-amber)]">{t("reconnecting")}</p>
              ) : null}
            </div>
            {countdown.text != null ? (
              <span className="font-display text-heading font-bold tabular-nums text-[color:var(--aqt-teal)]">
                {countdown.text}
              </span>
            ) : null}
            {myPick && chosen != null && chosen.roles.length > 1 ? (
              <div role="radiogroup" aria-label={t("role")} className="flex items-center gap-1">
                {chosen.roles.map((role) => (
                  <Button
                    key={role}
                    type="button"
                    role="radio"
                    aria-checked={chosenRole === role}
                    variant="outline"
                    className={cn(
                      chosenRole === role &&
                        "border-[color:var(--aqt-teal)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_14%,transparent)]"
                    )}
                    size="icon-sm"
                    aria-label={slotLabel(role)}
                    title={slotLabel(role)}
                    onClick={() => current != null && setSelection({ pickId: current.id, playerId: chosen.player.id, role })}
                  >
                    <PlayerRoleIcon role={role} ontology={owner.ontology} size={18} decorative />
                  </Button>
                ))}
              </div>
            ) : null}
            {myPick ? (
              <Button
                type="button"
                className="min-h-11 min-w-0 flex-1 sm:flex-initial"
                disabled={!confirmable || mutations.makePick.isPending}
                onClick={confirm}
              >
                {mutations.makePick.isPending ? <Spinner className="mr-2" /> : null}
                <span className="min-w-0 truncate">
                  {chosen != null ? t("pick", { player: draftPlayerName(chosen.player) }) : t("pickHint")}
                </span>
              </Button>
            ) : null}
          </div>
        </OverlayBar>
      ) : null}
    </div>
  );
}

function PoolCard({
  entry,
  owner,
  mine,
  choosing,
  selected,
  onChoose
}: Readonly<{
  entry: PoolPlayer;
  owner: MixOwner;
  mine: boolean;
  /** The viewer is the captain on the clock: cards are buttons, refused ones say why. */
  choosing: boolean;
  selected: boolean;
  onChoose: () => void;
}>) {
  const t = useTranslations("mixes.arena.draft");
  const tRoom = useTranslations("mixes.room");
  const slotLabel = useSlotLabel(owner.ontology);
  const { player } = entry;
  const key = player.workspace_member_id != null ? `m${player.workspace_member_id}` : `d${player.id}`;
  const refused = choosing && entry.roles.length === 0;
  const roles = owner.showsRoles ? playerRoles(player) : [];
  const body = (
    <>
      <RankCrest rank={player.effective_rank} grid={owner.grid} size={30} className="shrink-0" />
      <span className="flex min-w-0 flex-1 flex-col">
        <HandleLabel
          handle={draftPlayerName(player)}
          className="min-w-0 truncate text-body font-semibold text-[color:var(--aqt-fg)]"
          tagClassName="text-label"
        />
        {refused ? (
          <span className="truncate text-label text-[color:var(--aqt-fg-dim)]">
            {t(`unpickable.${(entry.reason != null ? REASONS[entry.reason] : undefined) ?? "other"}`)}
          </span>
        ) : roles.length > 0 ? (
          <span className="flex items-center gap-1" aria-label={roles.map((role) => slotLabel(role)).join(", ")}>
            {roles.map((role) => (
              <PlayerRoleIcon key={role} role={role} ontology={owner.ontology} size={16} decorative />
            ))}
          </span>
        ) : null}
      </span>
      {mine ? <span className="shrink-0 text-label font-semibold text-[color:var(--aqt-teal)]">{tRoom("you")}</span> : null}
    </>
  );
  const frame = cn(
    "flex min-h-14 w-full min-w-0 items-center gap-2.5 rounded-lg border px-3 py-2 text-left transition-colors",
    selected
      ? "border-[color:var(--aqt-teal)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)]"
      : "border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]",
    refused && "opacity-50"
  );
  return (
    <li style={{ viewTransitionName: playerTransitionName(key) }} className="min-w-0">
      {choosing && !refused ? (
        <RowButton
          aria-pressed={selected}
          className={cn(frame, "hover:border-[color:var(--aqt-teal)]/60")}
          onClick={onChoose}
        >
          {body}
        </RowButton>
      ) : (
        <div className={frame}>{body}</div>
      )}
    </li>
  );
}
