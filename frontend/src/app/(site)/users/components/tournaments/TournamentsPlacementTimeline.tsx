import React from "react";
import { LineChart } from "lucide-react";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import { UserTournament } from "@/types/user.types";

interface Props {
  tournaments: UserTournament[];
}

const colorClass = (placement: number, field: number): "gold" | "silver" | "bronze" | "mid" | "bottom" => {
  if (placement === 1) return "gold";
  if (placement <= 3) return "silver";
  if (placement <= 5) return "bronze";
  return placement / field < 0.5 ? "mid" : "bottom";
};

const TournamentsPlacementTimeline = ({ tournaments }: Props) => {
  const valid = tournaments
    .filter((t) => t.number && t.placement && t.count_teams)
    .sort((a, b) => a.number - b.number);
  if (valid.length === 0) return null;

  const minN = valid[0].number;
  const maxN = valid[valid.length - 1].number;
  const range = maxN - minN || 1;

  // Build an x-axis label set (~7 ticks)
  const ticks: number[] = [];
  for (let i = 0; i <= 6; i++) {
    ticks.push(Math.round(minN + (range * i) / 6));
  }

  return (
    <CardSurface
      title="Placement timeline"
      icon={<LineChart size={15} />}
      subtitle={`${valid.length} tournaments · finish position vs field size`}
    >
      <div className="aqt-timeline">
        <div className="aqt-y-axis">
          <span>top</span>
          <span>33%</span>
          <span>66%</span>
          <span>last</span>
        </div>
        <div className="aqt-ln">
          {valid.map((t) => {
            const ratio = t.placement / t.count_teams;
            const left = ((t.number - minN) / range) * 100;
            const top = ratio * 100;
            const cls = colorClass(t.placement, t.count_teams);
            return (
              <div
                key={t.id}
                className={`aqt-dot ${cls}`}
                style={{ left: `${left}%`, top: `${top}%` }}
                title={`T#${t.number} · placed ${t.placement}/${t.count_teams}`}
              />
            );
          })}
        </div>
        <div className="aqt-x-axis">
          {ticks.map((n, i) => (
            <span key={i}>#{n}</span>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap gap-3.5 border-t border-[color:var(--aqt-border)] px-[18px] py-3.5 text-[11px] text-[color:var(--aqt-fg-muted)]">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "linear-gradient(135deg,#fcd34d,#d97706)" }} />
          1st place
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "linear-gradient(135deg,#e5e7eb,#9ca3af)" }} />
          Podium
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "var(--aqt-teal)" }} />
          Top half
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "var(--aqt-rose)" }} />
          Bottom half
        </span>
      </div>
    </CardSurface>
  );
};

export default TournamentsPlacementTimeline;
