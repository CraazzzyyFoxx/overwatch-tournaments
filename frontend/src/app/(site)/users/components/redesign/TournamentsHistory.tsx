"use client";

import React, { useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { cn } from "@/lib/utils";
import { UserTournament, EncounterWithUserStats } from "@/types/user.types";
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
  if (t.placement === 1) return "finals";
  if (t.placement <= 3) return "playoffs";
  return "group";
};

const computeTournamentResults = (tournament: UserTournament, selfUserId: number) => {
  const allEncounters = tournament.encounters ?? [];
  const allPips: ScoreKind[] = [];
  let won = 0, lost = 0, drawn = 0;

  for (const enc of allEncounters) {
    const homePlayers = enc.home_team?.players ?? [];
    const isUserHome = homePlayers.some((p) => p.user_id === selfUserId);
    for (const match of enc.matches ?? []) {
      if (!match.score) { drawn++; allPips.push("draw"); continue; }
      const userScore = isUserHome ? match.score.home : match.score.away;
      const oppScore = isUserHome ? match.score.away : match.score.home;
      if (userScore > oppScore) { won++; allPips.push("win"); }
      else if (userScore < oppScore) { lost++; allPips.push("loss"); }
      else { drawn++; allPips.push("draw"); }
    }
  }

  return { pips: allPips.slice(0, 5), won, lost, drawn };
};

// ─── Encounter row ────────────────────────────────────────────────────────────

const EncounterRow = ({
  enc,
  selfUserId,
  teamId
}: {
  enc: EncounterWithUserStats;
  selfUserId: number;
  teamId: number;
}) => {
  const isUserHome =
    enc.home_team_id === teamId ||
    (enc.home_team?.players ?? []).some((p) => p.user_id === selfUserId);

  const userScore = isUserHome ? enc.score.home : enc.score.away;
  const oppScore = isUserHome ? enc.score.away : enc.score.home;
  const scoreKind: ScoreKind =
    userScore > oppScore ? "win" : userScore < oppScore ? "loss" : "draw";

  const opponent = isUserHome ? enc.away_team?.name : enc.home_team?.name;

  // Collect unique hero images from all maps
  const heroImgs: string[] = [];
  const seen = new Set<string>();
  for (const m of enc.matches ?? []) {
    for (const h of m.heroes ?? []) {
      if (h.image_path && !seen.has(h.image_path)) {
        seen.add(h.image_path);
        heroImgs.push(h.image_path);
      }
    }
  }

  const stageLabel =
    enc.stage_item?.name ?? enc.stage?.name ?? enc.name ?? "—";

  return (
    <Link
      href={`/encounters/${enc.id}`}
      className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-3 border-b border-[color:var(--aqt-border)] px-4 py-2.5 text-[13px] transition-colors last:border-b-0 hover:bg-[hsl(0_0%_100%/0.025)]"
    >
      {/* Stage + opponent */}
      <div className="flex flex-col gap-0.5 min-w-0">
        <span className="truncate font-medium text-[color:var(--aqt-fg)]">
          {opponent ?? enc.name}
        </span>
        <span className="aqt-mono text-[10.5px] text-[color:var(--aqt-fg-dim)]">
          {stageLabel}
          {enc.has_logs ? (
            <span className="ml-1.5 text-[color:var(--aqt-emerald)]">· logs</span>
          ) : null}
        </span>
      </div>

      {/* Hero images */}
      <div className="hidden items-center gap-0.5 sm:flex">
        {heroImgs.slice(0, 5).map((src) => (
          <div key={src} className="relative h-5 w-5 overflow-hidden rounded-sm">
            <Image src={src} alt="" fill sizes="20px" className="object-cover" />
          </div>
        ))}
      </div>

      {/* Closeness */}
      {enc.closeness != null ? (
        <span className="aqt-mono hidden text-[11px] text-[color:var(--aqt-fg-dim)] sm:block">
          {(enc.closeness * 100).toFixed(0)}%
        </span>
      ) : <span />}

      {/* Score */}
      <span
        className={cn(
          "aqt-mono min-w-[52px] text-right text-[15px] font-bold",
          scoreKind === "win" && "text-[color:var(--aqt-emerald)]",
          scoreKind === "loss" && "text-[color:var(--aqt-rose)]",
          scoreKind === "draw" && "text-[color:var(--aqt-amber)]"
        )}
      >
        {enc.score.home} – {enc.score.away}
      </span>
    </Link>
  );
};

// ─── Main component ───────────────────────────────────────────────────────────

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

        const encounters = t.encounters ?? [];

        return (
          <React.Fragment key={t.id}>
            {/* ── Row ── */}
            <div
              className={cn("aqt-t-item", cls, isOpen && "expanded")}
              onClick={() => setExpanded((s) => ({ ...s, [t.id]: !isOpen }))}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ")
                  setExpanded((s) => ({ ...s, [t.id]: !isOpen }));
              }}
            >
              {/* Placement number */}
              <div className="aqt-display text-[24px] font-extrabold leading-none text-[color:var(--aqt-fg-muted)]">
                {tournamentNumber}
              </div>

              {/* Name + meta */}
              <div className="flex flex-col gap-1.5">
                <div className="text-[15px] font-semibold text-[color:var(--aqt-fg)]">
                  <Link
                    href={`/tournaments/${t.id}`}
                    onClick={(e) => e.stopPropagation()}
                    className="hover:text-[color:var(--aqt-teal)]"
                  >
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

              {/* Division + placement */}
              <div className="aqt-mono inline-flex items-center gap-2 text-[12px] text-[color:var(--aqt-fg-muted)]">
                <DivisionIcon division={t.division} tournamentGrid={t.division_grid_version} width={26} height={26} />
                <span className="aqt-display aqt-tnum text-[20px] font-bold text-[color:var(--aqt-fg)]">
                  {t.placement || "—"}
                </span>
                <span className="text-[color:var(--aqt-fg-faint)]">/ {t.count_teams}</span>
              </div>

              <PipRow results={stats.pips} tall />

              <div
                className={cn("transition-transform", isOpen && "rotate-180")}
                style={{ color: isOpen ? "var(--aqt-teal)" : "var(--aqt-fg-faint)" }}
              >
                ▾
              </div>
            </div>

            {/* ── Expanded panel ── */}
            {isOpen ? (
              <div className="border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.012)]">
                {/* Stats + Roster row */}
                <div className="grid gap-4 p-4 md:grid-cols-[220px_1fr]">
                  {/* Stats */}
                  <div className="flex flex-col gap-3 rounded-[10px] border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.018)] p-3.5">
                    <div className="flex items-baseline justify-between">
                      <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">Matches</span>
                      <span className="aqt-display text-[22px] font-bold leading-none">{t.won + t.lost + t.draw}</span>
                    </div>
                    <div className="grid grid-cols-[1fr_auto] gap-1.5 text-[12.5px] text-[color:var(--aqt-fg-muted)]">
                      <span>Record</span>
                      <span className="aqt-mono">
                        <span style={{ color: "var(--aqt-emerald)" }}>{t.won}W</span>{" "}
                        <span style={{ color: "var(--aqt-rose)" }}>{t.lost}L</span>{" "}
                        <span style={{ color: "var(--aqt-amber)" }}>{t.draw}D</span>
                      </span>
                    </div>
                    <div className="grid grid-cols-[1fr_auto] gap-1.5 text-[12.5px] text-[color:var(--aqt-fg-muted)]">
                      <span>Maps won</span>
                      <span className="aqt-mono font-semibold text-[color:var(--aqt-fg)]">
                        {t.maps_won} of {t.maps_won + t.maps_lost}
                      </span>
                    </div>
                    <div className="grid grid-cols-[1fr_auto] gap-1.5 text-[12.5px] text-[color:var(--aqt-fg-muted)]">
                      <span>Closeness</span>
                      <span className="aqt-mono font-semibold text-[color:var(--aqt-fg)]">
                        {(t.closeness * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>

                  {/* Roster */}
                  <div className="rounded-[10px] border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.018)] p-3.5">
                    <div className="mb-2.5 text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">Roster</div>
                    <div className="grid gap-2">
                      {t.players?.slice(0, 5).map((p) => {
                        const isSelf = p.user_id === selfUserId;
                        const playerRoleColor =
                          p.role === "Tank" ? "var(--aqt-tank)"
                          : p.role === "Support" ? "var(--aqt-support)"
                          : "var(--aqt-damage)";
                        return (
                          <div key={p.id} className="grid grid-cols-[16px_1fr_auto] items-center gap-2">
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
                            <DivisionIcon division={p.division} width={26} height={26} />
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>

                {/* Encounters list */}
                {encounters.length > 0 ? (
                  <div className="mx-4 mb-4 overflow-hidden rounded-[10px] border border-[color:var(--aqt-border)]">
                    <div className="grid grid-cols-[1fr_auto_auto_auto] border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.018)] px-4 py-2">
                      <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">Opponent</span>
                      <span className="hidden text-[10px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)] sm:block">Heroes</span>
                      <span className="hidden text-[10px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)] sm:block">Close.</span>
                      <span className="text-right text-[10px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">Score</span>
                    </div>
                    {encounters.map((enc) => (
                      <EncounterRow
                        key={enc.id}
                        enc={enc}
                        selfUserId={selfUserId}
                        teamId={t.team_id}
                      />
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </React.Fragment>
        );
      })}
    </CardSurface>
  );
};

export default TournamentsHistory;
