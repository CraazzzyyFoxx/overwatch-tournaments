import React from "react";

import { Encounter } from "@/types/encounter.types";
import { Standings } from "@/types/tournament.types";
import { cn } from "@/lib/utils";
import { sortStandingsMatches } from "@/lib/tournament-match-order";

export interface StandingTableProps {
  standings: Standings[];
  is_groups: boolean;
  // Groups: tint the top-N rows and draw a dashed "top N advance" cut-line.
  advanceCount?: number;
  // Playoff/overall: mark rank 1 as the crowned winner.
  crownTop?: boolean;
}

type ResultKind = "w" | "l" | "t";

const TEAM_GRADIENTS = [
  "linear-gradient(135deg,hsl(174 72% 60%),hsl(174 60% 32%))",
  "linear-gradient(135deg,hsl(340 75% 65%),hsl(340 60% 38%))",
  "linear-gradient(135deg,hsl(270 70% 68%),hsl(270 55% 42%))",
  "linear-gradient(135deg,hsl(38 95% 62%),hsl(38 80% 42%))",
  "linear-gradient(135deg,hsl(210 78% 65%),hsl(210 60% 38%))",
  "linear-gradient(135deg,hsl(142 65% 55%),hsl(142 50% 32%))",
];

function teamGradient(seed: number): string {
  return TEAM_GRADIENTS[Math.abs(seed) % TEAM_GRADIENTS.length];
}

function teamInitials(name?: string | null): string {
  const cleaned = (name ?? "").trim();
  if (!cleaned) return "?";
  const words = cleaned.split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return cleaned.slice(0, 2).toUpperCase();
}

function resultOf(teamId: number, encounter: Encounter): ResultKind {
  const teamScore =
    encounter.home_team_id === teamId ? encounter.score.home : encounter.score.away;
  const opponentScore =
    encounter.home_team_id === teamId ? encounter.score.away : encounter.score.home;
  if (teamScore === opponentScore) return "t";
  return teamScore > opponentScore ? "w" : "l";
}

function computeMaps(teamId: number, history: Encounter[]) {
  let won = 0;
  let lost = 0;
  for (const encounter of history) {
    const isHome = encounter.home_team_id === teamId;
    won += isHome ? encounter.score.home : encounter.score.away;
    lost += isHome ? encounter.score.away : encounter.score.home;
  }
  return { won, lost, diff: won - lost };
}

function MapDiff({ diff }: { diff: number }) {
  const tone = diff > 0 ? "pos" : diff < 0 ? "neg" : "zero";
  const text = diff > 0 ? `+${diff}` : diff < 0 ? `−${Math.abs(diff)}` : "0";
  return <span className={cn("st-diff", tone)}>{text}</span>;
}

function FormChips({ results }: { results: ResultKind[] }) {
  if (results.length === 0) {
    return <span style={{ color: "var(--fg-faint)" }}>—</span>;
  }
  return (
    <span className="form-chips">
      {results.slice(-5).map((result, index) => (
        <span key={index} className={cn("fc", result)}>
          {result.toUpperCase()}
        </span>
      ))}
    </span>
  );
}

function TeamCell({ standing, showGroup }: { standing: Standings; showGroup: boolean }) {
  const groupName = standing.team?.group?.name;
  return (
    <div className="st-team">
      <span className="av" style={{ background: teamGradient(standing.team_id) }}>
        {teamInitials(standing.team?.name)}
      </span>
      <div className="stack">
        <span className="nm">{standing.team?.name ?? "—"}</span>
        {showGroup && groupName && <span className="sub">Group {groupName}</span>}
      </div>
    </div>
  );
}

const StandingsTable = ({
  standings,
  is_groups,
  advanceCount = 2,
  crownTop = false,
}: StandingTableProps) => {
  const sortedStandings = [...standings].sort((a, b) => {
    const left = is_groups ? a.position : a.overall_position;
    const right = is_groups ? b.position : b.overall_position;
    return left - right;
  });

  const showCut = is_groups && sortedStandings.length > advanceCount;
  const columnCount = is_groups ? 6 : 7;

  return (
    <div className="st-scroll">
      <table className="st">
        <thead>
          {is_groups ? (
            <tr>
              <th style={{ width: 48 }}>#</th>
              <th>Team</th>
              <th className="c" style={{ width: 70 }}>
                W·L
              </th>
              <th className="c" style={{ width: 120 }}>
                Form
              </th>
              <th className="r" style={{ width: 80 }}>
                Map Δ
              </th>
              <th className="c" style={{ width: 90 }} />
            </tr>
          ) : (
            <tr>
              <th style={{ width: 56 }}>#</th>
              <th>Team</th>
              <th className="c" style={{ width: 90 }}>
                Record
              </th>
              <th className="r" style={{ width: 170 }}>
                Maps
              </th>
              <th className="r" style={{ width: 80 }}>
                Map Δ
              </th>
              <th className="c" style={{ width: 130 }}>
                Form
              </th>
            </tr>
          )}
        </thead>
        <tbody>
          {sortedStandings.map((standing, index) => {
            const position = is_groups ? standing.position : standing.overall_position;
            const history = sortStandingsMatches(standing.matches_history ?? []);
            const results = history.map((encounter) => resultOf(standing.team_id, encounter));
            const maps = computeMaps(standing.team_id, history);
            const total = maps.won + maps.lost;
            const wPct = total > 0 ? (maps.won / total) * 100 : 0;
            const advancing = is_groups && position <= advanceCount;
            const crowned = !is_groups && crownTop && position === 1;
            const rowClass = crowned ? "crown" : advancing ? "advance" : undefined;

            return (
              <React.Fragment key={`${standing.stage_item_id ?? standing.stage_id ?? "s"}-${standing.team_id}`}>
                <tr className={rowClass}>
                  <td>
                    <span className="st-rank">{position}</span>
                  </td>
                  <td>
                    <TeamCell standing={standing} showGroup={!is_groups} />
                  </td>

                  {is_groups ? (
                    <>
                      <td className="c">
                        <span className="st-record">
                          <span className="w">{standing.win}</span>
                          <span className="sep">·</span>
                          <span className="l">{standing.lose}</span>
                        </span>
                      </td>
                      <td className="c">
                        <FormChips results={results} />
                      </td>
                      <td className="r">
                        <MapDiff diff={maps.diff} />
                      </td>
                      <td className="c">
                        {advancing ? (
                          <span className="st-status adv">
                            <span className="arrow" />
                            Adv
                          </span>
                        ) : (
                          <span className="st-status out">Out</span>
                        )}
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="c">
                        <span className="st-record">
                          <span className="w">{standing.win}</span>
                          <span className="sep">·</span>
                          <span className="l">{standing.lose}</span>
                        </span>
                      </td>
                      <td className="r">
                        <span className="st-maps">
                          <span className="num">
                            {maps.won}–{maps.lost}
                          </span>
                          <span className="bar">
                            <span className="w" style={{ width: `${wPct}%` }} />
                            <span className="l" style={{ width: `${100 - wPct}%` }} />
                          </span>
                        </span>
                      </td>
                      <td className="r">
                        <MapDiff diff={maps.diff} />
                      </td>
                      <td className="c">
                        <FormChips results={results} />
                      </td>
                    </>
                  )}
                </tr>

                {showCut && index === advanceCount - 1 && (
                  <tr>
                    <td
                      colSpan={columnCount}
                      className="st-cut"
                      data-label={`top ${advanceCount} advance`}
                    />
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

export default StandingsTable;
