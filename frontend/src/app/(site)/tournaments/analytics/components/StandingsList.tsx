"use client";

import React, { useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import { TeamVM } from "@/app/(site)/tournaments/analytics/useAnalyticsViewModel";
import DeltaPill from "@/app/(site)/tournaments/analytics/components/DeltaPill";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

type StandingsMode = "standings" | "movers" | "watch";

interface StandingsListProps {
  teams: TeamVM[];
  algorithmName?: string | null;
  selectedTeamId: number | null;
  onSelectTeam: (teamId: number) => void;
}

const MODES: StandingsMode[] = ["standings", "movers", "watch"];

function placementRank(placement: number | null): number {
  return placement == null ? Number.MAX_SAFE_INTEGER : placement;
}

function sortTeams(teams: TeamVM[], mode: StandingsMode): TeamVM[] {
  if (mode === "movers") {
    return [...teams].sort(
      (a, b) => Math.abs(b.placement_delta ?? 0) - Math.abs(a.placement_delta ?? 0),
    );
  }
  if (mode === "watch") {
    return teams.filter((team) => team.flagCount > 0);
  }
  return [...teams].sort((a, b) => placementRank(a.placement) - placementRank(b.placement));
}

/**
 * The community standings: a sortable list (Standings / Biggest movers / Watch
 * list) where each row selects a team for the detail panel. Replaces the dense
 * organizer table as the primary read surface.
 */
export default function StandingsList({
  teams,
  algorithmName,
  selectedTeamId,
  onSelectTeam,
}: StandingsListProps) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<StandingsMode>("standings");
  const rows = useMemo(() => sortTeams(teams, mode), [teams, mode]);

  const modeLabel: Record<StandingsMode, string> = {
    standings: t("analytics.community.standings.sortStandings"),
    movers: t("analytics.community.standings.sortMovers"),
    watch: t("analytics.community.standings.sortWatch"),
  };

  return (
    <div className={styles.cStandings}>
      <div className={styles.cStandingsHead}>
        <span className={styles.cStandingsTitle}>{t("analytics.community.standings.title")}</span>
        {algorithmName ? (
          <span className={styles.cStandingsBy}>
            {t("analytics.community.standings.rankedBy", { algorithm: algorithmName })}
          </span>
        ) : null}
      </div>

      <div className={styles.cSeg} role="tablist">
        {MODES.map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={mode === value}
            data-on={mode === value}
            className={styles.cSegBtn}
            onClick={() => setMode(value)}
          >
            {modeLabel[value]}
          </button>
        ))}
      </div>

      <div className={styles.cTeamRows}>
        {rows.length === 0 ? (
          <div className={styles.cStandingsEmpty}>
            {t("analytics.community.standings.watchEmpty")}
          </div>
        ) : (
          rows.map((team) => {
            const groupName = team.group?.name ?? "—";
            return (
              <button
                key={team.id}
                type="button"
                className={styles.cTeamRow}
                data-sel={selectedTeamId === team.id}
                onClick={() => onSelectTeam(team.id)}
              >
                <span className={cn(styles.cRank, team.placement === 1 && styles.cRank1)}>
                  {team.placement ?? "—"}
                </span>
                <span className={styles.cTeamId}>
                  <span className={styles.cTeamName}>{team.name}</span>
                  <span className={styles.cTeamMeta}>
                    <span>
                      {team.wins}–{team.losses}
                    </span>
                    <span>·</span>
                    <span>{t("analytics.community.standings.group", { group: groupName })}</span>
                    {team.flagCount > 0 ? (
                      <>
                        <span>·</span>
                        <span className={styles.cFlagText}>
                          {t(
                            team.flagCount === 1
                              ? "analytics.community.standings.flagCountOne"
                              : "analytics.community.standings.flagCount",
                            { count: team.flagCount },
                          )}
                        </span>
                      </>
                    ) : null}
                  </span>
                </span>
                <DeltaPill delta={team.placement_delta} />
                <ChevronRight className={styles.cChevron} size={16} aria-hidden="true" />
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
