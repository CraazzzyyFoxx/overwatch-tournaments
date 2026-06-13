import React from "react";
import { Swords } from "lucide-react";
import Link from "next/link";
import { CardSurface } from "@/app/(site)/users/components/redesign/atoms";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import { EncounterWithUserStats, UserTournament } from "@/types/user.types";
import { cn } from "@/lib/utils";

interface Props {
  encounters: EncounterWithUserStats[];
  userName: string;
  tournaments: UserTournament[];
}

const getStageLabel = (encounter: EncounterWithUserStats): string => {
  return encounter.stage_item?.name ?? encounter.stage?.name ?? "";
};

const getTeamLabels = (
  encounter: EncounterWithUserStats,
  userTeamId: number | undefined
): { home: string; away: string; isUserHome: boolean } => {
  const homeTeam = encounter.home_team;
  const awayTeam = encounter.away_team;
  const home = homeTeam?.name ?? "Home";
  const away = awayTeam?.name ?? "Away";
  const isUserHome = userTeamId != null && encounter.home_team_id === userTeamId;
  return { home, away, isUserHome };
};

const OverviewRecentEncounters = ({ encounters, userName, tournaments }: Props) => {
  if (encounters.length === 0) return null;
  const userSlug = userName.replace("#", "-");
  const teamIdByTournament = new Map(tournaments.map((t) => [t.id, t.team_id]));

  return (
    <CardSurface
      flush
      title="Recent encounters"
      icon={<Swords size={15} />}
      action={
        <Link href={`/users/${userSlug}?tab=matches`} className="aqt-seeall">
          All matches →
        </Link>
      }
    >
      {encounters.map((enc) => {
        const userTeamId = enc.tournament ? teamIdByTournament.get(enc.tournament.id) : undefined;
        const { home, away, isUserHome } = getTeamLabels(enc, userTeamId);
        const stage = getStageLabel(enc);
        const t = enc.tournament;
        const tournamentLabel = t ? (t.number ? `T${t.number}` : t.name.slice(0, 3)) : "T?";
        const score = enc.score;
        const scoreKind = score.home === score.away ? "draw" : (isUserHome ? score.home > score.away : score.away > score.home) ? "win" : "loss";
        const scoreStr = `${score.home} - ${score.away}`;

        const pips = (enc.matches ?? []).map((m): "win" | "loss" | "draw" => {
          if (!m.score) return "draw";
          const userScore = isUserHome ? m.score.home : m.score.away;
          const oppScore = isUserHome ? m.score.away : m.score.home;
          if (userScore > oppScore) return "win";
          if (userScore < oppScore) return "loss";
          return "draw";
        });
        const stageShort = stage ? stage.split(" ")[0] : "";
        const subText = `${stage || "BO" + (enc.best_of || "?")} · ${enc.matches?.length || 0} maps`;

        return (
          <Link
            key={enc.id}
            href={`/encounters/${enc.id}`}
            className="grid cursor-pointer grid-cols-[auto_1fr_auto_auto_auto] items-center gap-3 border-b border-[color:var(--aqt-border)] px-4 py-3 transition-colors last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)]"
          >
            <span className="aqt-mono min-w-[42px] text-[10px] uppercase tracking-[0.08em] text-[color:var(--aqt-fg-faint)]">
              {tournamentLabel}{stageShort ? `·${stageShort.charAt(0)}` : ""}
            </span>
            <div className="flex flex-col gap-0.5 leading-tight">
              <div className="text-[13px] font-semibold text-[color:var(--aqt-fg)]">
                {isUserHome ? <em className="not-italic" style={{ color: "var(--aqt-teal)" }}>{home}</em> : home}
                {" vs "}
                {!isUserHome ? <em className="not-italic" style={{ color: "var(--aqt-teal)" }}>{away}</em> : away}
              </div>
              <div className="text-[11px] text-[color:var(--aqt-fg-dim)]">{subText}</div>
            </div>
            <span className="inline-flex gap-[3px]">
              {pips.map((p, i) => (
                <span key={i} className={cn("aqt-pip", p)} />
              ))}
            </span>
            <span
              className={cn("aqt-mono min-w-[42px] text-right text-[16px] font-bold", scoreKind === "win" && "text-[color:var(--aqt-emerald)]", scoreKind === "loss" && "text-[color:var(--aqt-rose)]", scoreKind === "draw" && "text-[color:var(--aqt-amber)]")}
            >
              {scoreStr}
            </span>
            <MatchLogIndicator hasLogs={enc.has_logs} size={13} className="h-6 w-6" />
          </Link>
        );
      })}
    </CardSurface>
  );
};

export default OverviewRecentEncounters;
