"use client";

import { useEffect, useState } from "react";
import { Loader2, ShieldCheck, Shuffle, WifiOff } from "lucide-react";
import { useTranslations } from "next-intl";

import { OverlayBar } from "@/components/ui/overlay-bar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { describeApiError } from "@/lib/api/error";
import { resolveDivisionFromRank } from "@/lib/divisions/grid";
import { notify } from "@/lib/notify";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type { DraftGating } from "@/lib/draft/logic";
import type { DraftMutations } from "@/hooks/useDraftData";
import type { DraftBoard, DraftPlayer, DraftRole } from "@/types/draft.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { AdminDock } from "./AdminDock";
import { DraftClockRing } from "./DraftClockRing";
import { resolveDraftAccent } from "@/lib/draft/visual";
import { picksUntilTeamTurn, slotRankForPlayer } from "@/lib/draft/workspace-model";

export interface PickSelection {
  player: DraftPlayer;
  role: DraftRole;
}

interface PickCommandBarProps {
  board: DraftBoard;
  gating: DraftGating;
  selection: PickSelection | null;
  /** Server-verified: connected, options current, and this pair is safe. */
  canConfirm: boolean;
  connectionState: RealtimeConnectionState;
  mutations: DraftMutations;
  onClearSelection: () => void;
  divisionGrid: DivisionGrid;
  onlineCaptainIds?: ReadonlySet<number>;
}

/**
 * The one bar every seat in the room gets.
 *
 * A spectator reads it (clock, who is on the clock, how far the draft is). A
 * captain also confirms from it — in ONE click, not through a review dialog
 * that only restated a selection already spelled out beside the button. An
 * admin gets the same bar plus their own row of controls.
 */
export function PickCommandBar({
  board,
  gating,
  selection,
  canConfirm,
  connectionState,
  mutations,
  onClearSelection,
  divisionGrid,
  onlineCaptainIds
}: Readonly<PickCommandBarProps>) {
  const t = useTranslations("draftRedesign");
  const [announcement, setAnnouncement] = useState("");
  const [note, setNote] = useState("");
  const isConnected = connectionState === "connected";
  const pending = mutations.makePick.isPending;
  const ready = canConfirm && !pending;
  const shape = board.session.roster_shape;
  const current = board.current_pick;
  const overtime = current?.overtime_started_at != null;
  const accent = resolveDraftAccent(board);
  const myTeam = board.teams.find((team) => team.id === gating.myTeamId) ?? null;
  const onClockTeam = board.teams.find((team) => team.id === current?.draft_team_id) ?? null;
  const selectionTeamName = myTeam?.name ?? onClockTeam?.name ?? t("myTeam");
  const picksUntilMyTurn =
    !gating.isMyPick && board.session.status === "live" && gating.myTeamId != null
      ? picksUntilTeamTurn(board.picks, gating.myTeamId)
      : null;
  // The admin's override lane: they hold a selection while somebody else is on
  // the clock. A captain acting on their own pick uses the confirm button.
  const overrideMode = gating.isAdmin && !gating.isMyPick && selection != null && current != null;
  const showSelection = gating.isCaptain || gating.isAdmin;
  const selectedRank = selection ? slotRankForPlayer(selection.player, selection.role, shape) : null;
  const selectedDivision =
    selectedRank != null ? resolveDivisionFromRank(divisionGrid, selectedRank) : null;
  const selectedName = selection
    ? selection.player.battle_tag ?? `#${selection.player.id}`
    : null;

  const confirm = () => {
    if (!canConfirm || pending || !current || !selection) return;
    mutations.makePick.mutate(
      {
        pickId: current.id,
        playerId: selection.player.id,
        version: current.version,
        role: selection.role
      },
      {
        onSuccess: () => {
          const message = t("pickSuccess", { player: selectedName! });
          setAnnouncement(message);
          notify.success(message);
          onClearSelection();
        },
        onError: (error) => {
          // Both: the toast is what a sighted captain actually notices, the
          // live region is what a screen reader gets without one.
          const described = describeApiError(error);
          setAnnouncement([described.title, described.description].filter(Boolean).join(". "));
          notify.apiError(error);
        }
      }
    );
  };

  const applyOverride = () => {
    if (!current || !selection || note.trim().length === 0 || mutations.override.isPending) return;
    mutations.override.mutate(
      {
        pickId: current.id,
        playerId: selection.player.id,
        version: current.version,
        role: selection.role,
        note: note.trim()
      },
      {
        onSuccess: () => {
          const message = t("overrideSuccess", { player: selectedName! });
          setAnnouncement(message);
          notify.success(message);
          setNote("");
          onClearSelection();
        },
        onError: (error) => {
          const described = describeApiError(error);
          setAnnouncement([described.title, described.description].filter(Boolean).join(". "));
          notify.apiError(error);
        }
      }
    );
  };

  useEffect(() => {
    if (!gating.isMyPick) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Enter" || event.repeat || !canConfirm || pending) return;
      // Enter already activates whatever holds focus. Without this guard the
      // shortcut fires on top of that, so toggling a shortlist heart or
      // picking a role would also confirm the pick.
      const el = event.target as HTMLElement | null;
      if (
        el?.closest(
          "a,button,input,textarea,select,summary,[role=button],[role=tab],[role=radio],[role=option],[contenteditable=true]"
        )
      ) {
        return;
      }
      event.preventDefault();
      confirm();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <OverlayBar
      tone={!isConnected ? "warn" : ready ? "active" : "neutral"}
      // Overtime outranks every other tone: the pick is past its clock and the
      // autopick is what happens next.
      className={cn(overtime && "border-[color:var(--aqt-live)]/70")}
      ariaLabel={t("pickCommand")}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
        {/* `sm:contents` dissolves this mobile-only row so the wide layout keeps
            clock, meta, selection and the button on one line. */}
        <div className="flex min-w-0 items-center gap-2 sm:contents">
          <DraftClockRing
            expiresAt={current?.clock_expires_at ?? null}
            paused={board.session.status === "paused"}
            totalSeconds={board.session.pick_time_seconds}
            accent={accent}
            overtimeStartedAt={current?.overtime_started_at ?? null}
            overtimeSeconds={board.session.overtime_seconds}
          />
          <div className="min-w-0 shrink-0 border-r border-[color:var(--aqt-border-2)] pr-3 sm:pr-4">
            <p className="text-label uppercase tracking-[0.15em] text-[color:var(--aqt-teal)]">
              {gating.isMyPick ? t("yourTurn") : t("onClockLabel")}
            </p>
            <p className="text-sm font-semibold">
              <span className="hidden sm:inline">
                <span className="inline-block max-w-[12rem] truncate align-bottom" title={onClockTeam?.name}>
                  {onClockTeam?.name ?? "—"}
                </span>{" · "}
              </span>
              <span className="font-normal text-[color:var(--aqt-fg-muted)]">
                {t("pickMeta", { pick: current?.overall_no ?? 0, total: board.picks.length })}
              </span>
            </p>
            {picksUntilMyTurn != null && (
              <p className="mt-0.5 text-xs text-[color:var(--aqt-fg-muted)]">
                {t("yourTurnInPicks", { n: picksUntilMyTurn })}
              </p>
            )}
            {overtime && (
              <p className="mt-0.5 text-label font-bold uppercase tracking-label text-[color:var(--aqt-live)]">
                {t("overtime")}
              </p>
            )}
          </div>
          {showSelection && (
            <div className="min-w-0 flex-1">
              <p className="text-label uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
                {t("selectionFor", { team: selectionTeamName })}
              </p>
              <p className="mt-1 flex items-center gap-2 text-sm font-medium">
                {selection ? (
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="truncate" title={selectedName ?? undefined}>{selectedName}</span>
                    {shape.has_role_slots ? (
                      <PlayerRoleIcon role={getRoleIconName(selection.role)} size={18} color={ROLE_ACCENT[selection.role]} />
                    ) : (
                      <Shuffle className="h-4 w-4 shrink-0 text-[color:var(--aqt-fg-muted)]" aria-hidden />
                    )}
                    <span className="tabular-nums text-[color:var(--aqt-fg-muted)]">{selectedRank ?? "—"}</span>
                  </span>
                ) : (
                  <span className="line-clamp-2 text-[color:var(--aqt-fg-muted)]">{t("noSelection")}</span>
                )}
                {selectedDivision != null && (
                  <DivisionIcon division={selectedDivision} tournamentGrid={divisionGrid} width={24} height={24} className="h-6 w-6 shrink-0 object-contain" />
                )}
              </p>
            </div>
          )}
          {!isConnected && (
            // Shrinkable: a fixed-width hint next to a flex-1 selection block
            // squeezed the selection to nothing and drew over it. The sentence
            // is about confirming, so only the captain on the clock reads it;
            // everyone else gets the icon.
            <span className="flex min-w-0 shrink items-center gap-2 text-sm text-[color:var(--aqt-warm)]">
              <WifiOff className="h-4 w-4 shrink-0" aria-hidden />
              <span className={cn("line-clamp-2", gating.isMyPick ? "sr-only lg:not-sr-only" : "sr-only")}>
                {t("waitingFreshData")}
              </span>
            </span>
          )}
        </div>

        {gating.isMyPick && (
          <Button
            className={cn(
              "min-h-11 w-full sm:w-auto sm:shrink-0",
              !isConnected && "bg-[color:var(--aqt-warm)] text-[color:var(--aqt-bg)] hover:bg-[color:var(--aqt-warm)]/90",
              ready && "ring-2 ring-[color:var(--aqt-teal)]/40 ring-offset-2 ring-offset-[color:var(--aqt-card)]"
            )}
            disabled={!canConfirm || pending}
            onClick={confirm}
          >
            {pending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />
            ) : (
              <ShieldCheck className="mr-2 h-4 w-4" aria-hidden />
            )}
            {t("confirmPick")}
            {ready && (
              <span className="ml-1 hidden items-center rounded border border-current/40 px-1.5 py-0.5 text-label font-normal opacity-80 sm:inline-flex">
                {t("enterHint")}
              </span>
            )}
          </Button>
        )}

        {overrideMode &&
          (board.session.allow_admin_override ? (
            <div className="flex w-full items-center gap-2 sm:w-auto sm:shrink-0">
              {/* The note is the audit trail for taking a pick away from a
                  captain, so the button stays disabled until it exists. */}
              <Input
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder={t("overrideNote")}
                aria-label={t("overrideNote")}
                className="min-w-0 sm:w-56"
              />
              <Button
                variant="outline"
                className="min-h-11 shrink-0"
                disabled={note.trim().length === 0 || mutations.override.isPending}
                onClick={applyOverride}
              >
                {mutations.override.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />
                )}
                {t("applyOverride")}
              </Button>
            </div>
          ) : (
            <p className="shrink-0 text-xs text-[color:var(--aqt-fg-muted)]">{t("overrideDisabled")}</p>
          ))}
      </div>

      {gating.isAdmin && (
        <AdminDock board={board} mutations={mutations} onlineCaptainIds={onlineCaptainIds} />
      )}

      <p className="sr-only" aria-live="polite">{announcement}</p>
    </OverlayBar>
  );
}
