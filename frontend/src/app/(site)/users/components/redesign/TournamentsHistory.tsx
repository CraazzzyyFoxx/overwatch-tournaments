"use client";

import React, { useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { UserTournament } from "@/types/user.types";
import {
  CardSurface,
  PipRow,
  StagePill,
  type ScoreKind
} from "@/app/(site)/users/components/redesign/atoms";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";

interface Props {
  tournaments: UserTournament[];
  selfUserId: number;
}

const tournamentClass = (t: UserTournament): "" | "gold" | "podium" => {
  if (t.placement === 1) return "gold";
  if (t.placement <= 3) return "podium";
  return "";
};

const stageKindForTournament = (t: UserTournament): "group" | "playoffs" | "finals" | "default" => {
  // Heuristic from name and result
  if (t.placement === 1) return "finals";
  if (t.placement <= 3) return "playoffs";
  return "group";
};

const computeTournamentResults = (tournament: UserTournament, selfUserId: number) => {
  const allEncounters = tournament.encounters ?? [];

  const allPips: ScoreKind[] = [];
  let won = 0,
    lost = 0,
    drawn = 0;

  for (const enc of allEncounters) {
    const homePlayers = enc.home_team?.players ?? [];
    const isUserHome = homePlayers.some((p) => p.user_id === selfUserId);
    for (const match of enc.matches ?? []) {
      if (!match.score) {
        drawn++;
        allPips.push("draw");
        continue;
      }
      const userScore = isUserHome ? match.score.home : match.score.away;
      const oppScore = isUserHome ? match.score.away : match.score.home;
      if (userScore > oppScore) {
        won++;
        allPips.push("win");
      } else if (userScore < oppScore) {
        lost++;
        allPips.push("loss");
      } else {
        drawn++;
        allPips.push("draw");
      }
    }
  }

  return { pips: allPips.slice(0, 5), won, lost, drawn };
};

const TournamentsHistory = ({ tournaments, selfUserId }: Props) => {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  return (
    <CardSurface
      flush
      title="Tournament history"
      icon={<span>▢</span>}
      subtitle="click to expand"
    >
      {tournaments.map((t) => {
        const cls = tournamentClass(t);
        const isOpen = expanded[t.id] ?? false;
        const stats = computeTournamentResults(t, selfUserId);
        const tournamentNumber = t.number ? `${t.number}` : t.name.split(" | ")[1] ?? "—";
        const tournamentRoleColor =
          t.role === "Tank"
            ? "var(--aqt-tank)"
            : t.role === "Support"
              ? "var(--aqt-support)"
              : "var(--aqt-damage)";
        return (
          <React.Fragment key={t.id}>
            <div
              className={cn("aqt-t-item", cls, isOpen && "expanded")}
              onClick={() => setExpanded((s) => ({ ...s, [t.id]: !isOpen }))}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  setExpanded((s) => ({ ...s, [t.id]: !isOpen }));
                }
              }}
            >
              <div className="aqt-display text-[22px] font-extrabold leading-none text-[color:var(--aqt-fg-muted)]">
                {tournamentNumber}
              </div>
              <div className="flex flex-col gap-1">
                <div className="text-[14px] font-semibold text-[color:var(--aqt-fg)]">
                  <Link href={`/tournaments/${t.id}`} onClick={(e) => e.stopPropagation()} className="hover:text-[color:var(--aqt-teal)]">
                    {t.name}
                  </Link>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-[color:var(--aqt-fg-dim)]">
                  <StagePill kind={stageKindForTournament(t)}>
                    {t.placement === 1 ? "Grand finals" : t.placement <= 3 ? "Playoffs reached" : "Groups"}
                  </StagePill>
                  <span className="inline-flex items-center gap-1">
                    <PlayerRoleIcon role={t.role} size={11} color={tournamentRoleColor} />
                    Team {t.team} · {t.role}
                  </span>
                </div>
              </div>
              <div className="aqt-mono inline-flex items-center gap-2 text-[12px] text-[color:var(--aqt-fg-muted)]">
                <DivisionIcon division={t.division} tournamentGrid={t.division_grid_version} width={24} height={24} />
                <span className="aqt-display aqt-tnum text-[18px] font-bold text-[color:var(--aqt-fg)]">
                  {t.placement || "—"}
                </span>
                <span className="text-[color:var(--aqt-fg-faint)]">/ {t.count_teams}</span>
              </div>
              <PipRow results={stats.pips} tall />
              <div
                className={cn("transition-transform", isOpen && "rotate-180 text-[color:var(--aqt-teal)]")}
                style={{ color: isOpen ? "var(--aqt-teal)" : "var(--aqt-fg-faint)" }}
              >
                ▾
              </div>
            </div>
            {isOpen ? (
              <div className="grid gap-4 border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.012)] p-4 md:grid-cols-[280px_1fr]">
                <div className="flex flex-col gap-3.5 rounded-[10px] border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.018)] p-3.5">
                  <div className="flex items-baseline justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
                      Matches
                    </span>
                    <span className="aqt-display text-[20px] font-bold leading-none text-[color:var(--aqt-fg)]">
                      {t.won + t.lost + t.draw}
                    </span>
                  </div>
                  <div className="grid grid-cols-[1fr_auto] gap-2 text-[12px] text-[color:var(--aqt-fg-muted)]">
                    <span>Record</span>
                    <span className="aqt-mono">
                      <span style={{ color: "var(--aqt-emerald)" }}>{t.won}W</span>{" "}
                      <span style={{ color: "var(--aqt-rose)" }}>{t.lost}L</span>{" "}
                      <span style={{ color: "var(--aqt-amber)" }}>{t.draw}D</span>
                    </span>
                  </div>
                  <div className="grid grid-cols-[1fr_auto] gap-2 text-[12px] text-[color:var(--aqt-fg-muted)]">
                    <span>Maps won</span>
                    <span className="aqt-mono font-semibold text-[color:var(--aqt-fg)]">
                      {t.maps_won} of {t.maps_won + t.maps_lost}
                    </span>
                  </div>
                  <div className="grid grid-cols-[1fr_auto] gap-2 text-[12px] text-[color:var(--aqt-fg-muted)]">
                    <span>Closeness</span>
                    <span className="aqt-mono font-semibold text-[color:var(--aqt-fg)]">
                      {(t.closeness * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
                <div className="flex flex-col gap-3.5">
                  <div className="rounded-[10px] border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.018)] p-4">
                    <div className="mb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
                      Roster
                    </div>
                    <div className="grid gap-1.5">
                      {t.players?.slice(0, 5).map((p) => {
                        const isSelf = p.user_id === selfUserId;
                        const playerRoleColor =
                          p.role === "Tank"
                            ? "var(--aqt-tank)"
                            : p.role === "Support"
                              ? "var(--aqt-support)"
                              : "var(--aqt-damage)";
                        return (
                          <div key={p.id} className="grid grid-cols-[18px_1fr_auto] items-center gap-2">
                            <PlayerRoleIcon role={p.role} size={14} color={playerRoleColor} />
                            <div className="flex items-center gap-2 truncate text-[13px]">
                              <span className={cn("font-semibold", isSelf && "text-[color:var(--aqt-amber)]")}>
                                {p.name?.split("#")[0]}
                              </span>
                              {p.name?.includes("#") ? (
                                <span className="aqt-mono text-[10px] text-[color:var(--aqt-fg-faint)]">
                                  #{p.name.split("#")[1]}
                                </span>
                              ) : null}
                            </div>
                            <DivisionIcon division={p.division} width={24} height={24} />
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>
            ) : null}
          </React.Fragment>
        );
      })}
    </CardSurface>
  );
};

export default TournamentsHistory;
