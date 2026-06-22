"use client";

import { useMemo, useState } from "react";
import { Sword } from "lucide-react";

import { Hero, HeroLeaderboardEntry } from "@/types/hero.types";
import HeroImage from "@/components/hero/HeroImage";
import { heroVariantFromRole } from "@/components/hero/heroRole";

import { COL, StatKey, ALL_STAT_OPTIONS, NUM_COLUMNS } from "../config/stat-columns";
import { teamDotBackground } from "../utils/teamColor";
import SelectableStatColumn from "./SelectableStatColumn";
import StatColumnSkeleton from "./StatColumnSkeleton";

const MAX_LEGEND_TEAMS = 12;

interface HeroLeaderboardTableProps {
  selectedHero: Hero | undefined;
  selectedTournamentName: string | undefined;
  tournamentId: number | undefined;
  rows: HeroLeaderboardEntry[];
  isLoading: boolean;
  columnKeys: StatKey[];
  sortDirs: ("asc" | "desc")[];
  onColumnSelect: (colIndex: number, key: StatKey) => void;
  onToggleSort: (colIndex: number) => void;
}

const HeroLeaderboardTable = ({
  selectedHero,
  selectedTournamentName,
  tournamentId,
  rows,
  isLoading,
  columnKeys,
  sortDirs,
  onColumnSelect,
  onToggleSort,
}: HeroLeaderboardTableProps) => {
  const [hoveredUserId, setHoveredUserId] = useState<number | null>(null);
  const variant = heroVariantFromRole(selectedHero?.type ?? selectedHero?.role);

  const legendTeams = useMemo(() => {
    const seen = new Map<string, { team: string; teamId: number | null }>();
    for (const r of rows) {
      if (r.team && !seen.has(r.team)) seen.set(r.team, { team: r.team, teamId: r.team_id });
    }
    return Array.from(seen.values());
  }, [rows]);

  return (
    <section className="overflow-hidden rounded-[var(--aqt-radius)] border border-[var(--aqt-border)] bg-[var(--aqt-card)]">
      {/* Board head */}
      <div className="flex items-center gap-3.5 border-b border-[var(--aqt-border)] bg-white/[0.012] px-5 py-4">
        {selectedHero && <HeroImage hero={selectedHero} size={44} rounded="lg" />}
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <span className="font-[family-name:var(--aqt-display)] text-2xl font-bold uppercase leading-none tracking-[0.03em]">
              {selectedHero?.name ?? "Hero"}
            </span>
            {selectedHero && (
              <span
                className="rounded-[5px] px-1.5 py-0.5 text-[10px] font-bold uppercase leading-none tracking-[0.08em]"
                style={{
                  color: `var(--aqt-${variant})`,
                  background: `color-mix(in srgb, var(--aqt-${variant}) 15%, transparent)`,
                }}
              >
                {selectedHero.type ?? selectedHero.role}
              </span>
            )}
          </div>
          <p className="mt-1 font-[family-name:var(--aqt-mono)] text-[11.5px] text-[var(--aqt-fg-dim)]">
            {selectedTournamentName ?? "All tournaments"}
            {tournamentId ? ` · scope #${tournamentId}` : ""}
          </p>
        </div>
        {!isLoading && rows.length > 0 && (
          <span className="ml-auto rounded-full border border-[var(--aqt-border-2)] bg-white/[0.03] px-[11px] py-[5px] font-[family-name:var(--aqt-mono)] text-[11px] text-[var(--aqt-fg-muted)]">
            <em className="not-italic font-semibold text-[var(--aqt-teal)]">{rows.length}</em> players
          </span>
        )}
      </div>

      {/* Columns */}
      <div className="overflow-x-auto">
        <div className="flex min-w-max divide-x divide-[var(--aqt-border)]">
          {isLoading ? (
            Array.from({ length: NUM_COLUMNS }).map((_, i) => <StatColumnSkeleton key={i} />)
          ) : rows.length === 0 ? (
            <div className="flex w-full min-w-[600px] items-center justify-center gap-2 py-[90px] text-sm text-[var(--aqt-fg-dim)]">
              <Sword className="h-4 w-4 opacity-40" />
              No data found for this hero{tournamentId ? " in this tournament" : ""}.
            </div>
          ) : (
            columnKeys.map((key, i) => (
              <SelectableStatColumn
                key={i}
                def={COL[key]}
                sortDir={sortDirs[i]}
                options={ALL_STAT_OPTIONS}
                data={rows}
                hoveredUserId={hoveredUserId}
                onHoverUser={setHoveredUserId}
                onSelect={(k) => onColumnSelect(i, k)}
                onToggleSort={() => onToggleSort(i)}
              />
            ))
          )}
        </div>
      </div>

      {/* Teams legend */}
      {!isLoading && legendTeams.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t border-[var(--aqt-border)] bg-white/[0.008] px-5 py-3 text-[11px] text-[var(--aqt-fg-dim)]">
          <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--aqt-fg-faint)]">
            Teams
          </span>
          {legendTeams.slice(0, MAX_LEGEND_TEAMS).map(({ team, teamId }) => (
            <span key={team} className="inline-flex items-center gap-1.5 font-[family-name:var(--aqt-mono)] text-[var(--aqt-fg-muted)]">
              <span
                className="h-[9px] w-[9px] rounded-[2px]"
                style={{ background: teamDotBackground(team, teamId) }}
              />
              {team}
            </span>
          ))}
          {legendTeams.length > MAX_LEGEND_TEAMS && (
            <span className="text-[var(--aqt-fg-faint)]">+{legendTeams.length - MAX_LEGEND_TEAMS} more</span>
          )}
        </div>
      )}
    </section>
  );
};

export default HeroLeaderboardTable;
