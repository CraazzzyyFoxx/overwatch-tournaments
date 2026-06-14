"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import { UserTournament } from "@/types/user.types";
import { TournamentTeamTable } from "@/components/TournamentTeamCard";
import { PipRow, StagePill, type ScoreKind } from "@/app/(site)/users/components/shared/atoms";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import EncounterRow from "@/app/(site)/users/components/tournaments/EncounterRow";
import { StatLine, HeaderCell } from "@/app/(site)/users/components/tournaments/tournaments-history.atoms";

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

const roleColor = (role: string | null): string =>
  role === "Tank" ? "var(--aqt-tank)" : role === "Support" ? "var(--aqt-support)" : "var(--aqt-damage)";

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

// ─── Single tournament item (row + expanded panel) ──────────────────────────────

const TournamentItem = ({
  t,
  selfUserId,
  isOpen,
  onToggle
}: {
  t: UserTournament;
  selfUserId: number;
  isOpen: boolean;
  onToggle: () => void;
}) => {
  const cls = tournamentClass(t);
  const stats = computeTournamentResults(t, selfUserId);
  const tournamentNumber = t.number ? `${t.number}` : t.name.split(" | ")[1] ?? "—";
  const maps = t.maps_won + t.maps_lost;
  const winrate = maps > 0 ? Math.round((t.maps_won / maps) * 100) : 0;
  const encounters = t.encounters ?? [];

  return (
    <>
      {/* ── Row ── */}
      <div
        className={cn("aqt-t-item", cls, isOpen && "expanded")}
        onClick={onToggle}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") onToggle();
        }}
      >
        <div className="aqt-display text-[28px] font-extrabold leading-none text-[color:var(--aqt-fg-muted)]">
          {tournamentNumber}
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="text-[17px] font-semibold text-[color:var(--aqt-fg)]">
            <Link
              href={`/tournaments/${t.id}`}
              onClick={(e) => e.stopPropagation()}
              className="hover:text-[color:var(--aqt-teal)]"
            >
              {t.name}
            </Link>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[14px] text-[color:var(--aqt-fg-dim)]">
            <StagePill kind={stageKindForTournament(t)}>
              {t.placement === 1 ? "Grand finals" : t.placement <= 3 ? "Playoffs reached" : "Groups"}
            </StagePill>
            <span className="inline-flex items-center gap-1.5" title={t.role}>
              <PlayerRoleIcon role={t.role} size={15} color={roleColor(t.role)} />
              Team {t.team}
            </span>
          </div>
        </div>

        <div className="aqt-mono inline-flex items-center gap-2 text-[14px] text-[color:var(--aqt-fg-muted)]">
          <DivisionIcon division={t.division} tournamentGrid={t.division_grid_version} width={28} height={28} />
          <span className="aqt-display aqt-tnum text-[23px] font-bold text-[color:var(--aqt-fg)]">
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
          <div className="grid gap-4 p-4 md:grid-cols-[240px_1fr]">
            {/* Stats */}
            <div className="flex flex-col gap-3 rounded-[10px] border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.018)] p-3.5">
              <div className="flex items-baseline justify-between">
                <span className="text-[12px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
                  Matches
                </span>
                <span className="aqt-display text-[26px] font-bold leading-none">{t.won + t.lost + t.draw}</span>
              </div>
              <StatLine label="Record">
                <span style={{ color: "var(--aqt-emerald)" }}>{t.won}W</span>{" "}
                <span style={{ color: "var(--aqt-rose)" }}>{t.lost}L</span>{" "}
                <span style={{ color: "var(--aqt-amber)" }}>{t.draw}D</span>
              </StatLine>
              <StatLine label="Maps won">
                <span className="font-semibold text-[color:var(--aqt-fg)]">
                  {t.maps_won} of {maps}
                </span>
              </StatLine>
              <StatLine label="Winrate">
                <span
                  className="font-semibold"
                  style={{
                    color: winrate >= 55 ? "var(--aqt-emerald)" : winrate < 45 ? "var(--aqt-rose)" : "var(--aqt-amber)"
                  }}
                >
                  {maps > 0 ? `${winrate}%` : "—"}
                </span>
              </StatLine>
              <StatLine label="Closeness">
                <span className="font-semibold text-[color:var(--aqt-fg)]">{(t.closeness * 100).toFixed(0)}%</span>
              </StatLine>
            </div>

            {/* Roster (full) */}
            <div className="rounded-[10px] border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.018)] p-3.5">
              <div className="mb-2.5 text-[12px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
                Roster
              </div>
              <TournamentTeamTable players={t.players ?? []} tournamentGrid={t.division_grid_version} />
            </div>
          </div>

          {/* Encounters table */}
          {encounters.length > 0 ? (
            <div className="mx-4 mb-4 overflow-hidden rounded-[10px] border border-[color:var(--aqt-border)]">
              <div className="grid grid-cols-[1fr_auto_auto] border-b border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.018)] px-4 py-2 md:grid-cols-[1fr_auto_auto_auto_auto_auto]">
                <HeaderCell>Opponent</HeaderCell>
                <HeaderCell className="hidden md:block">Heroes</HeaderCell>
                <HeaderCell className="hidden md:block">MVP</HeaderCell>
                <HeaderCell className="hidden md:block">Close.</HeaderCell>
                <HeaderCell className="text-right">Score</HeaderCell>
                <HeaderCell className="hidden text-right md:block">Logs</HeaderCell>
              </div>
              {encounters.map((enc) => (
                <EncounterRow key={enc.id} enc={enc} selfUserId={selfUserId} teamId={t.team_id} />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
};

export default TournamentItem;
