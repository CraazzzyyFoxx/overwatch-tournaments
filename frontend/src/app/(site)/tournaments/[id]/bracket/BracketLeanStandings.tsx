"use client";

import { useTranslations } from "next-intl";

import type { Standings } from "@/types/tournament.types";

export interface BracketStandingRow {
  key: string;
  placement: number;
  teamLabel: string;
  groupLabel?: string;
}

export function toBracketStandingRows(
  standings: readonly Standings[],
  isGroups: boolean
): BracketStandingRow[] {
  return standings
    .map((standing) => ({
      key: `${standing.stage_item_id ?? standing.stage_id ?? "stage"}-${standing.team_id}`,
      placement: isGroups ? standing.position : standing.overall_position,
      teamLabel: standing.team?.name ?? "—",
      groupLabel: standing.team?.group?.name
    }))
    .sort((left, right) => left.placement - right.placement);
}

export function BracketLeanStandings({
  standings,
  isGroups
}: {
  standings: readonly Standings[];
  isGroups: boolean;
}) {
  const t = useTranslations();
  const rows = toBracketStandingRows(standings, isGroups);

  return (
    <div className="st-scroll">
      <table className="st">
        <thead>
          <tr>
            <th style={{ width: 56 }}>#</th>
            <th>{t("standings.colTeam")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td>
                <span className="st-rank">{row.placement}</span>
              </td>
              <td>
                <div className="st-team">
                  <div className="stack">
                    <span className="nm">{row.teamLabel}</span>
                    {!isGroups && row.groupLabel ? (
                      <span className="sub">
                        {t("common.group")} {row.groupLabel}
                      </span>
                    ) : null}
                  </div>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
