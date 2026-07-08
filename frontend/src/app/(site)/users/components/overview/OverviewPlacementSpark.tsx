import React from "react";
import { getTranslations } from "next-intl/server";
import { TrendingUp } from "lucide-react";
import { CardSurface, PlacementSpark } from "@/app/(site)/users/components/shared/atoms";
import { UserTournament } from "@/types/user.types";

interface Props {
  tournaments: UserTournament[];
  limit?: number;
}

const OverviewPlacementSpark = async ({ tournaments, limit = 12 }: Props) => {
  const recent = [...tournaments]
    .filter((tour) => tour.placement && tour.count_teams)
    .slice(0, limit)
    .reverse();

  if (recent.length === 0) return null;

  const t = await getTranslations();

  const points = recent.map((tour) => ({
    label: tour.number ? `${tour.number}` : tour.name.split(" | ")[1] ?? tour.name.slice(0, 4),
    placement: tour.placement
  }));

  const placements = recent.map((tour) => tour.placement);
  const fieldMax = Math.max(...recent.map((tour) => tour.count_teams), 1);
  const best = Math.min(...placements);
  const worst = Math.max(...placements);
  const median = [...placements].sort((a, b) => a - b)[Math.floor(placements.length / 2)];

  return (
    <CardSurface
      title={t("users.overview.placement.title")}
      icon={<TrendingUp size={15} />}
      subtitle={t("users.overview.placement.subtitle", { count: recent.length })}
    >
      <PlacementSpark data={points} max={fieldMax} />
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
