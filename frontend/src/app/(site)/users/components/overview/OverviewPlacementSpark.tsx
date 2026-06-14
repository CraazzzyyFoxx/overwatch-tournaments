import React from "react";
import { TrendingUp } from "lucide-react";
import { CardSurface, PlacementSpark } from "@/app/(site)/users/components/shared/atoms";
import { UserTournament } from "@/types/user.types";

interface Props {
  tournaments: UserTournament[];
  limit?: number;
}

const OverviewPlacementSpark = ({ tournaments, limit = 12 }: Props) => {
  const recent = [...tournaments]
    .filter((t) => t.placement && t.count_teams)
    .slice(0, limit)
    .reverse();

  if (recent.length === 0) return null;

  const points = recent.map((t) => ({
    label: t.number ? `${t.number}` : t.name.split(" | ")[1] ?? t.name.slice(0, 4),
    placement: t.placement
  }));

  const placements = recent.map((t) => t.placement);
  const fieldMax = Math.max(...recent.map((t) => t.count_teams), 1);
  const best = Math.min(...placements);
  const worst = Math.max(...placements);
  const median = [...placements].sort((a, b) => a - b)[Math.floor(placements.length / 2)];

  return (
    <CardSurface
      title="Placement trend"
      icon={<TrendingUp size={15} />}
      subtitle={`last ${recent.length} events · lower = better`}
    >
      <PlacementSpark data={points} max={fieldMax} />
      <div className="mt-2.5 flex justify-between border-t border-[color:var(--aqt-border)] pt-2.5 text-[12px] text-[color:var(--aqt-fg-muted)]">
        <span>
          Best <span className="aqt-mono font-semibold" style={{ color: "var(--aqt-amber)" }}>#{best}</span>
        </span>
        <span>
          Median <span className="aqt-mono font-semibold text-[color:var(--aqt-fg)]">#{median}</span>
        </span>
        <span>
          Worst <span className="aqt-mono font-semibold" style={{ color: "var(--aqt-rose)" }}>#{worst}</span>
        </span>
      </div>
    </CardSurface>
  );
};

export default OverviewPlacementSpark;
