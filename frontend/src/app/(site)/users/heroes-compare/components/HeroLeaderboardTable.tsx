import Image from "next/image";
import { Sword } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Hero, HeroLeaderboardEntry } from "@/types/hero.types";
import GlassGlow from "@/app/(site)/users/compare/components/GlassGlow";

import { COL, StatKey, ALL_STAT_OPTIONS, NUM_COLUMNS } from "../config/stat-columns";
import SelectableStatColumn from "./SelectableStatColumn";
import StatColumnSkeleton from "./StatColumnSkeleton";

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
}: HeroLeaderboardTableProps) => (
  <Card className="relative overflow-hidden">
    <GlassGlow />

    <div className="relative flex items-center gap-3 border-b border-border/50 px-5 py-3.5">
      {selectedHero && (
        <Image
          src={selectedHero.image_path}
          alt={selectedHero.name}
          width={36}
          height={36}
          className="h-9 w-9 rounded-full border border-border/60 object-cover shadow-md"
        />
      )}
      <div className="flex-1">
        <p className="text-sm font-semibold leading-tight">
          {selectedHero?.name ?? "Hero"}
        </p>
        <p className="mt-0.5 text-xs leading-none text-muted-foreground">
          {selectedTournamentName ?? "All tournaments"}
        </p>
      </div>
      {!isLoading && rows.length > 0 && (
        <span className="rounded-full bg-background/20 px-2.5 py-1 text-xs font-medium text-muted-foreground ring-1 ring-border/40">
          {rows.length} players
        </span>
      )}
    </div>

    <div className="relative overflow-x-auto">
      <div className="flex min-w-max divide-x divide-border/40">
        {isLoading ? (
          Array.from({ length: NUM_COLUMNS }).map((_, i) => <StatColumnSkeleton key={i} />)
        ) : rows.length === 0 ? (
          <div className="flex w-full min-w-[600px] items-center justify-center gap-2 py-20 text-sm text-muted-foreground">
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
              onSelect={(k) => onColumnSelect(i, k)}
              onToggleSort={() => onToggleSort(i)}
            />
          ))
        )}
      </div>
    </div>
  </Card>
);

export default HeroLeaderboardTable;
