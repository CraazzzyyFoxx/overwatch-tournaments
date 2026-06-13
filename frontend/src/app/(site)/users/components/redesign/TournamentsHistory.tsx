"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { UserTournament, EncounterWithUserStats } from "@/types/user.types";
import type { Hero } from "@/types/hero.types";
import { HeroStrip } from "@/components/hero/HeroImage";
import { TournamentTeamTable } from "@/components/TournamentTeamCard";
import {
  CardSurface,
  PipRow,
  StagePill,
  MvpPill,
  mvpRank,
  ordinal,
  type ScoreKind
} from "@/app/(site)/users/components/redesign/atoms";
import MatchLogIndicator from "@/app/(site)/users/components/redesign/MatchLogIndicator";
import {
  groupTournamentsByLeague,
  leagueKey
} from "@/app/(site)/users/components/redesign/tournaments-history.helpers";
import userService from "@/services/user.service";
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

// ─── Encounter row (expanded matches table) ─────────────────────────────────────

const scoreAccent: Record<ScoreKind, string> = {
  win: "var(--aqt-emerald)",
  loss: "var(--aqt-rose)",
  draw: "var(--aqt-amber)"
};

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
    enc.home_team_id === teamId || (enc.home_team?.players ?? []).some((p) => p.user_id === selfUserId);

  const userScore = isUserHome ? enc.score.home : enc.score.away;
  const oppScore = isUserHome ? enc.score.away : enc.score.home;
  const scoreKind: ScoreKind = userScore > oppScore ? "win" : userScore < oppScore ? "loss" : "draw";

  const opponent = isUserHome ? enc.away_team?.name : enc.home_team?.name;

  // Unique heroes across all maps in the encounter.
  const heroes: Hero[] = [];
  const seen = new Set<string>();
  for (const m of enc.matches ?? []) {
    for (const h of m.heroes ?? []) {
      const key = h.image_path || h.name;
      if (key && !seen.has(key)) {
        seen.add(key);
        heroes.push(h);
      }
    }
  }

  const stageLabel = enc.stage_item?.name ?? enc.stage?.name ?? enc.name ?? "—";

  return (
    <Link
      href={`/encounters/${enc.id}`}
      className="grid grid-cols-[1fr_auto_auto] items-center gap-3 border-b border-[color:var(--aqt-border)] px-4 py-2.5 text-[13px] transition-colors last:border-b-0 hover:bg-[hsl(0_0%_100%/0.025)] md:grid-cols-[1fr_auto_auto_auto_auto_auto]"
      style={{ boxShadow: `inset 3px 0 0 0 ${scoreAccent[scoreKind]}` }}
    >
      {/* Stage + opponent */}
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate font-medium text-[color:var(--aqt-fg)]">{opponent ?? enc.name}</span>
        <span className="aqt-mono text-[10.5px] text-[color:var(--aqt-fg-dim)]">{stageLabel}</span>
      </div>

      {/* Heroes */}
      <div className="hidden items-center md:flex">
        <HeroStrip heroes={heroes} size="sm" limit={6} />
      </div>

      {/* MVP pills (per map) */}
      <div className="hidden items-center gap-1 md:flex">
        {(enc.matches ?? []).map((m) =>
          m.performance != null ? (
            <MvpPill key={m.id} rank={mvpRank(m.performance)} label={ordinal(m.performance)} />
          ) : null
        )}
      </div>

      {/* Closeness */}
      {enc.closeness != null ? (
        <span className="aqt-mono hidden text-[11px] text-[color:var(--aqt-fg-dim)] md:block">
          {(enc.closeness * 100).toFixed(0)}%
        </span>
      ) : (
        <span className="hidden md:block" />
      )}

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

      {/* Logs */}
      <div className="hidden justify-end md:flex" onClick={(e) => e.preventDefault()}>
        <MatchLogIndicator
          hasLogs={enc.has_logs}
          logs={
            enc.has_logs
              ? (enc.matches ?? []).map((m, i) => ({ matchId: m.id, label: m.map?.name ?? `Map ${i + 1}` }))
              : undefined
          }
          hrefFor={userService.matchLogDownloadUrl}
        />
      </div>
    </Link>
  );
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
        <div className="aqt-display text-[24px] font-extrabold leading-none text-[color:var(--aqt-fg-muted)]">
          {tournamentNumber}
        </div>

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
              <PlayerRoleIcon role={t.role} size={11} color={roleColor(t.role)} />
              Team {t.team} · {t.role}
            </span>
          </div>
        </div>

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
          <div className="grid gap-4 p-4 md:grid-cols-[240px_1fr]">
            {/* Stats */}
            <div className="flex flex-col gap-3 rounded-[10px] border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.018)] p-3.5">
              <div className="flex items-baseline justify-between">
                <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
                  Matches
                </span>
                <span className="aqt-display text-[22px] font-bold leading-none">{t.won + t.lost + t.draw}</span>
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
              <div className="mb-2.5 text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
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

const StatLine = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="grid grid-cols-[1fr_auto] gap-1.5 text-[12.5px] text-[color:var(--aqt-fg-muted)]">
    <span>{label}</span>
    <span className="aqt-mono">{children}</span>
  </div>
);

const HeaderCell = ({ children, className }: { children: React.ReactNode; className?: string }) => (
  <span
    className={cn(
      "text-[10px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]",
      className
    )}
  >
    {children}
  </span>
);

// ─── League group (collapsible parent over division entries) ────────────────────

const LeagueGroup = ({
  name,
  entries,
  selfUserId,
  isOpen,
  onToggle,
  isTournamentOpen,
  onToggleTournament
}: {
  name: string;
  entries: UserTournament[];
  selfUserId: number;
  isOpen: boolean;
  onToggle: () => void;
  isTournamentOpen: (t: UserTournament) => boolean;
  onToggleTournament: (t: UserTournament) => void;
}) => {
  const bestPlacement = entries.reduce((best, t) => (t.placement && t.placement < best ? t.placement : best), Infinity);

  return (
    <div className="border-b border-[color:var(--aqt-border)]">
      <div
        className="flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-[hsl(0_0%_100%/0.02)]"
        onClick={onToggle}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") onToggle();
        }}
      >
        <span
          className="aqt-mono rounded-[5px] border px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em]"
          style={{
            background: "hsl(258 60% 62% / 0.1)",
            borderColor: "hsl(258 60% 62% / 0.25)",
            color: "var(--aqt-violet)"
          }}
        >
          League
        </span>
        <span className="flex-1 truncate text-[15px] font-semibold text-[color:var(--aqt-fg)]">{name}</span>
        <span className="aqt-mono text-[11px] text-[color:var(--aqt-fg-dim)]">
          {entries.length} divisions
          {bestPlacement !== Infinity ? ` · best #${bestPlacement}` : ""}
        </span>
        <div
          className={cn("transition-transform", isOpen && "rotate-180")}
          style={{ color: isOpen ? "var(--aqt-teal)" : "var(--aqt-fg-faint)" }}
        >
          ▾
        </div>
      </div>

      {isOpen ? (
        <div className="border-t border-[color:var(--aqt-border)] pl-4">
          {entries.map((t) => (
            <TournamentItem
              key={t.id}
              t={t}
              selfUserId={selfUserId}
              isOpen={isTournamentOpen(t)}
              onToggle={() => onToggleTournament(t)}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
};

// ─── Main component ─────────────────────────────────────────────────────────────

const TournamentsHistory = ({ tournaments, selfUserId }: Props) => {
  const searchParams = useSearchParams();
  const selectedId = useMemo(() => {
    const raw = searchParams?.get("selectedTournamentId");
    const parsed = raw ? Number(raw) : NaN;
    return Number.isFinite(parsed) ? parsed : null;
  }, [searchParams]);

  // Group consecutive league entries (sharing the league-name prefix) under one parent.
  const grouped = useMemo(() => groupTournamentsByLeague(tournaments), [tournaments]);

  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [expandedLeagues, setExpandedLeagues] = useState<Record<string, boolean>>({});

  const syncUrl = (id: number, open: boolean) => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (open) url.searchParams.set("selectedTournamentId", String(id));
    else url.searchParams.delete("selectedTournamentId");
    window.history.replaceState(null, "", url.toString());
  };

  const isTournamentOpen = (t: UserTournament) => expanded[t.id] ?? t.id === selectedId;

  const toggleTournament = (t: UserTournament) => {
    const next = !isTournamentOpen(t);
    setExpanded((s) => ({ ...s, [t.id]: next }));
    syncUrl(t.id, next);
  };

  const isLeagueOpen = (name: string, entries: UserTournament[]) =>
    expandedLeagues[name] ?? entries.some((t) => t.id === selectedId);

  return (
    <CardSurface flush title="Tournament history" icon={<span>▢</span>} subtitle="click to expand">
      {grouped.map((entry) => {
        if (!Array.isArray(entry)) {
          return (
            <TournamentItem
              key={entry.id}
              t={entry}
              selfUserId={selfUserId}
              isOpen={isTournamentOpen(entry)}
              onToggle={() => toggleTournament(entry)}
            />
          );
        }
        const name = leagueKey(entry[0]);
        return (
          <LeagueGroup
            key={name}
            name={name}
            entries={entry}
            selfUserId={selfUserId}
            isOpen={isLeagueOpen(name, entry)}
            onToggle={() => setExpandedLeagues((s) => ({ ...s, [name]: !isLeagueOpen(name, entry) }))}
            isTournamentOpen={isTournamentOpen}
            onToggleTournament={toggleTournament}
          />
        );
      })}
    </CardSurface>
  );
};

export default TournamentsHistory;
