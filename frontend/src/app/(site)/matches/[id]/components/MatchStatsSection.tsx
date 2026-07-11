"use client";

import React, { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { MatchWithStats } from "@/types/encounter.types";
import type { DivisionGridVersion } from "@/types/workspace.types";
import {
  COLUMN_PRESETS,
  PRESET_ORDER,
  PresetKey,
  availableRounds,
  columnMaxima
} from "@/utils/matchStats";
import MatchTeamTable from "@/app/(site)/matches/[id]/components/MatchTeamTable";
import MatchTeamComparison from "@/app/(site)/matches/[id]/components/MatchTeamComparison";
import MatchLeaders from "@/app/(site)/matches/[id]/components/MatchLeaders";
import MatchContributionChart from "@/app/(site)/matches/[id]/components/MatchContributionChart";
import MatchKillFeedTimeline from "@/app/(site)/matches/[id]/components/MatchKillFeedTimeline";

interface MatchStatsSectionProps {
  match: MatchWithStats;
  tournamentGrid?: DivisionGridVersion | null;
}

const Chip = ({
  active,
  onClick,
  children
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) => (
  <button
    type="button"
    onClick={onClick}
    className="rounded-md border px-2.5 py-1 text-[11.5px] font-semibold transition-colors"
    style={{
      borderColor: active ? "hsl(172 70% 49% / 0.35)" : "var(--aqt-border)",
      background: active ? "hsl(172 70% 49% / 0.12)" : "hsl(0 0% 100% / 0.02)",
      color: active ? "var(--aqt-teal)" : "var(--aqt-fg-muted)"
    }}
  >
    {children}
  </button>
);

const MatchStatsSection = ({ match, tournamentGrid }: MatchStatsSectionProps) => {
  const t = useTranslations<never>();
  const home = match.home_team;
  const away = match.away_team;

  const rounds = useMemo(() => availableRounds(home, away), [home, away]);
  const [round, setRound] = useState<number>(0);
  const [preset, setPreset] = useState<PresetKey>("overview");

  const columns = COLUMN_PRESETS[preset];
  const columnMax = useMemo(
    () => columnMaxima(home, away, round, columns),
    [home, away, round, columns]
  );

  const activeRound = rounds.includes(round) ? round : 0;

  return (
    <div className="flex flex-col gap-5">
      {/* Round selector */}
      {rounds.length > 1 ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="aqt-mono text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
            {t("matches.roundLabel")}
          </span>
          {rounds.map((value) => (
            <Chip key={value} active={value === activeRound} onClick={() => setRound(value)}>
              {value === 0 ? t("matches.allMatch") : t("matches.round", { round: value })}
            </Chip>
          ))}
        </div>
      ) : null}

      {/* Match leaders */}
      <MatchLeaders home={home} away={away} round={activeRound} />

      {/* Detailed per-player tables with column presets */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="aqt-mono mr-1 text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
            {t("matches.tableView")}
          </span>
          {PRESET_ORDER.map((key) => (
            <Chip key={key} active={key === preset} onClick={() => setPreset(key)}>
              {t(`matches.preset.${key}`)}
            </Chip>
          ))}
        </div>
        <div className="flex flex-col gap-4">
          <MatchTeamTable
            team={home}
            isHome={true}
            matchRound={activeRound}
            columns={columns}
            columnMax={columnMax}
            tournamentGrid={tournamentGrid}
          />
          <MatchTeamTable
            team={away}
            isHome={false}
            matchRound={activeRound}
            columns={columns}
            columnMax={columnMax}
            tournamentGrid={tournamentGrid}
          />
        </div>
      </div>

      {/* Charts — head-to-head + per-player contribution (page end) */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <MatchTeamComparison home={home} away={away} round={activeRound} />
        <MatchContributionChart home={home} away={away} round={activeRound} />
      </div>

      {/* Kill / event timeline — lazily fetched from the kill_feed table */}
      <MatchKillFeedTimeline matchId={match.id} home={home} away={away} />
    </div>
  );
};

export default MatchStatsSection;
