"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { usePermissions } from "@/hooks/usePermissions";
import { useTranslation } from "@/i18n/LanguageContext";
import type { DraftBoard as DraftBoardData, DraftPlayer } from "@/types/draft.types";
import type { Tournament } from "@/types/tournament.types";

import { useDraftBoardQuery, useDraftMutations, useDraftRealtime } from "../_hooks/useDraftData";
import { computeGating } from "../_lib/draft-logic";
import { DraftClock } from "./DraftClock";

interface DraftBoardProps {
  tournament: Tournament;
}

export function DraftBoard({ tournament }: DraftBoardProps) {
  const { t } = useTranslation();
  const tournamentId = tournament.id;
  const boardQuery = useDraftBoardQuery(tournamentId);
  useDraftRealtime(tournamentId);
  const mutations = useDraftMutations(tournamentId);

  const { user } = useAuthProfile();
  const { isSuperuser, isWorkspaceAdmin } = usePermissions();
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null);

  const board = boardQuery.data ?? null;
  const isAdmin = isSuperuser || isWorkspaceAdmin(tournament.workspace_id);
  const myPlayerIds = useMemo(
    () => (user?.linkedPlayers ?? []).map((p) => p.playerId),
    [user]
  );

  if (boardQuery.isLoading) {
    return <div className="p-8 text-[var(--aqt-fg-muted)]">{t("draft.loading")}</div>;
  }
  if (!board) {
    return (
      <div className="rounded-[14px] border border-[var(--aqt-border)] p-8 text-center">
        <p className="text-lg font-semibold">{t("draft.empty.title")}</p>
        <p className="text-[var(--aqt-fg-muted)]">{t("draft.empty.body")}</p>
      </div>
    );
  }

  return <DraftBoardView board={board} myPlayerIds={myPlayerIds} isAdmin={isAdmin}
    selectedPlayerId={selectedPlayerId} onSelectPlayer={setSelectedPlayerId} mutations={mutations} t={t} />;
}

interface DraftBoardViewProps {
  board: DraftBoardData;
  myPlayerIds: number[];
  isAdmin: boolean;
  selectedPlayerId: number | null;
  onSelectPlayer: (id: number | null) => void;
  mutations: ReturnType<typeof useDraftMutations>;
  t: (key: string) => string;
}

function DraftBoardView({
  board,
  myPlayerIds,
  isAdmin,
  selectedPlayerId,
  onSelectPlayer,
  mutations,
  t,
}: DraftBoardViewProps) {
  const { session, teams, current_pick } = board;
  const gating = computeGating(board, myPlayerIds, isAdmin);

  const rosterByTeam = useMemo(() => {
    const map = new Map<number, DraftPlayer[]>();
    for (const p of board.players) {
      if (p.drafted_by_team_id != null) {
        const list = map.get(p.drafted_by_team_id) ?? [];
        list.push(p);
        map.set(p.drafted_by_team_id, list);
      }
    }
    return map;
  }, [board.players]);

  const available = board.players.filter((p) => p.status === "available");
  const onClockTeam = teams.find((tm) => tm.id === current_pick?.draft_team_id) ?? null;
  const totalPicks = session.rounds * teams.length;
  const completedCount = board.picks.filter(
    (p) => p.status === "completed" || p.status === "autopicked" || p.status === "skipped"
  ).length;

  const confirmPick = () => {
    if (current_pick == null || selectedPlayerId == null) return;
    mutations.makePick.mutate({
      pickId: current_pick.id,
      playerId: selectedPlayerId,
      version: current_pick.version,
    });
    onSelectPlayer(null);
  };

  const runLifecycle = (action: "start" | "pause" | "resume" | "cancel" | "export") =>
    mutations.lifecycle.mutate({ sessionId: session.id, action });

  return (
    <div className="aqt-tn flex flex-col gap-4">
      {/* Header */}
      <header className="tn-card flex flex-wrap items-center justify-between gap-4 rounded-[14px] border border-[var(--aqt-border)] p-5">
        <div className="flex items-center gap-3">
          <span className={`status-pill ${session.status}`}>{t(`draft.state.${session.status}`)}</span>
          <span className="text-[var(--aqt-fg-muted)]">
            {t("draft.round")} {current_pick?.round_no ?? "-"}/{session.rounds} · {t("draft.pick")}{" "}
            {completedCount}/{totalPicks}
          </span>
        </div>
        <div className="flex items-center gap-4">
          {onClockTeam && (
            <span className="text-sm">
              {t("draft.onTheClock")}: <strong>{onClockTeam.name}</strong>
            </span>
          )}
          <span className="text-2xl">
            <DraftClock
              expiresAt={current_pick?.clock_expires_at ?? null}
              paused={session.status === "paused"}
            />
          </span>
        </div>
      </header>

      {/* Admin controls */}
      {isAdmin && (
        <div className="flex flex-wrap gap-2">
          {(session.status === "setup" || session.status === "ready") && (
            <Button size="sm" disabled={mutations.lifecycle.isPending} onClick={() => runLifecycle("start")}>
              {t("draft.admin.start")}
            </Button>
          )}
          {session.status === "live" && (
            <Button size="sm" variant="secondary" onClick={() => runLifecycle("pause")}>
              {t("draft.admin.pause")}
            </Button>
          )}
          {session.status === "paused" && (
            <Button size="sm" onClick={() => runLifecycle("resume")}>
              {t("draft.admin.resume")}
            </Button>
          )}
          {(session.status === "live" || session.status === "paused" || session.status === "ready") && (
            <Button size="sm" variant="destructive" onClick={() => runLifecycle("cancel")}>
              {t("draft.admin.cancel")}
            </Button>
          )}
          {session.status === "completed" && (
            <Button size="sm" disabled={mutations.lifecycle.isPending} onClick={() => runLifecycle("export")}>
              {t("draft.admin.export")}
            </Button>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[2fr_1fr]">
        {/* Teams + rosters */}
        <section className="flex flex-col gap-3">
          {teams.map((team) => {
            const roster = rosterByTeam.get(team.id) ?? [];
            const onClock = team.id === current_pick?.draft_team_id;
            return (
              <div
                key={team.id}
                className={`tn-card rounded-[14px] border p-4 ${onClock ? "border-[var(--aqt-teal)]" : "border-[var(--aqt-border)]"}`}
              >
                <div className="mb-2 flex items-center justify-between">
                  <strong>
                    #{team.draft_position} {team.name}
                  </strong>
                  {onClock && <span className="status-pill live">{t("draft.onTheClock")}</span>}
                </div>
                <ul className="flex flex-wrap gap-2 text-sm">
                  {roster.map((p) => (
                    <li
                      key={p.id}
                      className="rounded-md bg-[var(--aqt-bg-2,rgba(255,255,255,0.04))] px-2 py-1"
                    >
                      {p.is_captain ? "★ " : ""}
                      {p.battle_tag ?? `#${p.id}`}{" "}
                      <span className="text-[var(--aqt-fg-muted)]">({p.primary_role})</span>
                    </li>
                  ))}
                  {roster.length === 0 && (
                    <li className="text-[var(--aqt-fg-muted)]">{t("draft.roster.empty")}</li>
                  )}
                </ul>
              </div>
            );
          })}
        </section>

        {/* Available pool */}
        <section className="tn-card rounded-[14px] border border-[var(--aqt-border)] p-4">
          <div className="mb-3 flex items-center justify-between">
            <strong>{t("draft.pool.title")}</strong>
            <span className="text-[var(--aqt-fg-muted)]">{available.length}</span>
          </div>
          <ul className="flex max-h-[60vh] flex-col gap-1 overflow-auto">
            {available.map((p) => {
              const selected = p.id === selectedPlayerId;
              return (
                <li key={p.id}>
                  <button
                    type="button"
                    disabled={!gating.isMyPick}
                    onClick={() => onSelectPlayer(p.id)}
                    className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm ${
                      selected ? "bg-[var(--aqt-teal)]/20" : "hover:bg-white/5"
                    } disabled:cursor-not-allowed disabled:opacity-60`}
                  >
                    <span>
                      {p.battle_tag ?? `#${p.id}`}{" "}
                      <span className="text-[var(--aqt-fg-muted)]">({p.primary_role})</span>
                    </span>
                    <span className="font-mono text-[var(--aqt-fg-muted)]">{p.rank_value ?? "—"}</span>
                  </button>
                </li>
              );
            })}
            {available.length === 0 && (
              <li className="text-[var(--aqt-fg-muted)]">{t("draft.pool.empty")}</li>
            )}
          </ul>

          {gating.isMyPick && (
            <div className="mt-3">
              <Button
                className="w-full"
                disabled={selectedPlayerId == null || mutations.makePick.isPending}
                onClick={confirmPick}
              >
                {t("draft.actions.confirm")}
              </Button>
            </div>
          )}
          {gating.isCaptain && !gating.isMyPick && session.status === "live" && (
            <p className="mt-3 text-center text-sm text-[var(--aqt-fg-muted)]">
              {t("draft.notYourPick")}
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
