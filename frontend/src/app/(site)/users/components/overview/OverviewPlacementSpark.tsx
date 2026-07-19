import React from "react";
import { getTranslations } from "next-intl/server";
import { TrendingUp } from "lucide-react";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import { UserTournament } from "@/types/user.types";

interface Props {
  tournaments: UserTournament[];
  limit?: number;
}

type Shape = "podium" | "mid" | "bottom";

interface TrendPoint {
  label: string;
  placement: number;
  countTeams: number;
  xFrac: number;
  yPct: number;
  shape: Shape;
  color: string;
}

// Chart drawing band inside the track (percent of height); leaves head-room for
// the "#N" value labels above the top-most dot and clearance at the bottom.
const Y_TOP = 16;
const Y_BOTTOM = 86;

const podiumColor = (placement: number): string =>
  placement === 1 ? "var(--aqt-gold)" : placement === 2 ? "var(--aqt-silver)" : "var(--aqt-bronze)";

const OverviewPlacementSpark = async ({ tournaments, limit = 12 }: Props) => {
  const recent = [...tournaments]
    .filter((tour) => tour.placement && tour.count_teams)
    .slice(0, limit)
    .reverse();

  if (recent.length === 0) return null;

  const t = await getTranslations();

  const placements = recent.map((tour) => tour.placement);
  const fieldMax = Math.max(...recent.map((tour) => tour.count_teams), 1);
  const best = Math.min(...placements);
  const worst = Math.max(...placements);
  const median = [...placements].sort((a, b) => a - b)[Math.floor(placements.length / 2)];

  const n = recent.length;
  const points: TrendPoint[] = recent.map((tour, i) => {
    const placement = tour.placement;
    const yFrac = fieldMax > 1 ? Math.min(1, Math.max(0, (placement - 1) / (fieldMax - 1))) : 0;
    const shape: Shape =
      placement <= 3 ? "podium" : placement > Math.ceil(tour.count_teams / 2) ? "bottom" : "mid";
    return {
      label: tour.number ? `${tour.number}` : tour.name.split(" | ")[1] ?? tour.name.slice(0, 4),
      placement,
      countTeams: tour.count_teams,
      xFrac: n > 1 ? i / (n - 1) : 0.5,
      yPct: Y_TOP + yFrac * (Y_BOTTOM - Y_TOP),
      shape,
      color: shape === "podium" ? podiumColor(placement) : shape === "mid" ? "var(--aqt-teal)" : "var(--aqt-rose)"
    };
  });

  const polyPoints = points.map((p) => `${(p.xFrac * 100).toFixed(2)},${p.yPct.toFixed(2)}`).join(" ");

  const renderDot = (p: TrendPoint) => {
    if (p.shape === "podium") {
      return (
        <span
          className="block rounded-full"
          style={{ width: 11, height: 11, background: p.color, boxShadow: "0 0 0 2px hsl(0 0% 100% / 0.3)" }}
        />
      );
    }
    if (p.shape === "bottom") {
      return (
        <span
          className="block rounded-full"
          style={{ width: 10, height: 10, background: "var(--aqt-bg)", border: "2px solid var(--aqt-rose)" }}
        />
      );
    }
    return <span className="block rounded-full" style={{ width: 9, height: 9, background: "var(--aqt-teal)" }} />;
  };

  return (
    <CardSurface
      title={t("users.overview.placement.title")}
      icon={<TrendingUp size={15} />}
      subtitle={t("users.overview.placement.subtitle", { count: recent.length })}
    >
      <div className="px-4">
        <div className="relative h-[112px] overflow-visible">
          <svg
            className="absolute inset-0 h-full w-full overflow-visible"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            {n > 1 ? (
              <polyline
                points={polyPoints}
                fill="none"
                stroke="var(--aqt-teal)"
                strokeOpacity={0.6}
                strokeWidth={1.5}
                strokeLinejoin="round"
                strokeLinecap="round"
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
          </svg>
          {points.map((p, i) => (
            <div
              key={i}
              className="absolute"
              style={{ left: `${(p.xFrac * 100).toFixed(2)}%`, top: `${p.yPct.toFixed(2)}%`, transform: "translate(-50%, -50%)" }}
              title={`#${p.placement} · ${p.label}`}
            >
              <div className="relative flex items-center justify-center">
                <span className="aqt-mono absolute bottom-full left-1/2 mb-[3px] -translate-x-1/2 whitespace-nowrap text-[9.5px] text-[color:var(--aqt-fg-muted)]">
                  #{p.placement}
                </span>
                {renderDot(p)}
              </div>
            </div>
          ))}
        </div>
        <div className="relative mt-1 h-[13px]">
          {points.map((p, i) => (
            <span
              key={i}
              className="aqt-mono absolute -translate-x-1/2 whitespace-nowrap text-[9px] text-[color:var(--aqt-fg-faint)]"
              style={{ left: `${(p.xFrac * 100).toFixed(2)}%` }}
            >
              {p.label}
            </span>
          ))}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 text-[10.5px] text-[color:var(--aqt-fg-muted)]">
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block rounded-full"
            style={{ width: 10, height: 10, background: "var(--aqt-gold)", boxShadow: "0 0 0 1.5px hsl(0 0% 100% / 0.3)" }}
          />
          {t("users.overview.placement.legend.podium")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block rounded-full" style={{ width: 9, height: 9, background: "var(--aqt-teal)" }} />
          {t("users.overview.placement.legend.mid")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block rounded-full"
            style={{ width: 9, height: 9, background: "var(--aqt-bg)", border: "2px solid var(--aqt-rose)" }}
          />
          {t("users.overview.placement.legend.bottom")}
        </span>
      </div>

      <div className="mt-2.5 flex justify-between border-t border-[color:var(--aqt-border)] pt-2.5 text-[12px] text-[color:var(--aqt-fg-muted)]">
        <span>
          {t("users.overview.placement.best")} <span className="aqt-mono font-semibold" style={{ color: "var(--aqt-amber)" }}>#{best}</span>
        </span>
        <span>
          {t("users.overview.placement.median")} <span className="aqt-mono font-semibold text-[color:var(--aqt-fg)]">#{median}</span>
        </span>
        <span>
          {t("users.overview.placement.worst")} <span className="aqt-mono font-semibold" style={{ color: "var(--aqt-rose)" }}>#{worst}</span>
        </span>
      </div>
    </CardSurface>
  );
};

export default OverviewPlacementSpark;
