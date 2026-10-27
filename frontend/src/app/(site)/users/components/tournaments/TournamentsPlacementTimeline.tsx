"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { CardSurface, ProfileStat } from "@/components/profile/atoms";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { UserTournament } from "@/types/user.types";

interface Props {
  tournaments: UserTournament[];
  /** The career Titles figure. */
  tournamentsWon: number;
  /** Tournament ids that belong to the currently-selected dossier event. */
  selectedIds?: number[];
  /** Selecting a point selects that event in the dossier (and scrolls to it). */
  onSelect?: (tournamentId: number) => void;
}

// A point's hue, shared by the plot and its legend.
const DOT_HUE = {
  gold: "[--dot:var(--aqt-medal-gold)]",
  silver: "[--dot:var(--aqt-medal-silver)]",
  bronze: "[--dot:var(--aqt-medal-bronze)]",
  mid: "[--dot:var(--aqt-teal)]",
  bottom: "[--dot:var(--aqt-rose)]"
} as const;

const SWATCH = "inline-block size-2.5 rounded-full bg-[color:var(--dot)]";
// `hover:bg` keeps the ghost button's own hover fill off the point.
const DOT =
  "absolute h-2.75 w-2.75 -translate-x-1/2 -translate-y-1/2 cursor-pointer rounded-full border-2 border-[color:var(--aqt-card)] bg-[color:var(--dot)] hover:z-5 hover:bg-[color:var(--dot)]";
const AXIS = "font-[family-name:var(--aqt-data)] text-label text-[color:var(--aqt-fg-faint)]";

const colorClass = (placement: number, field: number): keyof typeof DOT_HUE => {
  if (placement === 1) return "gold";
  if (placement <= 3) return "silver";
  if (placement <= 5) return "bronze";
  return placement / field < 0.5 ? "mid" : "bottom";
};

const TournamentsPlacementTimeline = ({ tournaments, tournamentsWon, selectedIds = [], onSelect }: Props) => {
  const tr = useTranslations();
  const valid = tournaments
    .filter((t) => t.placement && t.count_teams)
    .sort((a, b) => a.id - b.id);
  if (valid.length === 0) return null;

  const selected = new Set(selectedIds);
  const n = valid.length;

  const podiumCount = valid.filter((t) => t.placement <= 3).length;
  const podiumRate = Math.round((podiumCount / n) * 100);
  const bestPlacement = Math.min(...valid.map((t) => t.placement));

  return (
    <CardSurface
      title={tr("users.tournaments.timeline.title")}
      subtitle={
        <span title={tr("users.tournaments.timeline.subtitleHint")}>
          {tr("users.tournaments.timeline.subtitle", { count: n })}
        </span>
      }
    >
      <div className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-3">
        <ProfileStat
          label={tr("users.tournaments.kpi.titles")}
          value={String(tournamentsWon)}
          color={tournamentsWon > 0 ? "var(--aqt-gold)" : undefined}
        />
        <ProfileStat
          label={tr("users.tournaments.kpi.podiumRate")}
          value={`${podiumRate}%`}
          sub={tr("users.tournaments.kpi.ofEvents", { podium: String(podiumCount), total: String(n) })}
        />
        <ProfileStat label={tr("users.tournaments.kpi.best")} value={String(bestPlacement)} />
      </div>
      <div className="relative mt-5 h-50 overflow-hidden rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)]">
        <div className={cn(AXIS, "absolute top-2 bottom-7.5 left-2 flex w-9 flex-col justify-between pr-1.5 text-right")}>
          <span>{tr("users.tournaments.timeline.axisTop")}</span>
          <span>33%</span>
          <span>66%</span>
          <span>{tr("users.tournaments.timeline.axisLast")}</span>
        </div>
        <div className="absolute top-3.5 right-3.5 bottom-7.5 left-12.5">
          {valid.map((t, i) => {
            const ratio = t.placement / t.count_teams;
            const left = n > 1 ? (i / (n - 1)) * 100 : 50;
            const top = ratio * 100;
            const cls = colorClass(t.placement, t.count_teams);
            const isSelected = selected.has(t.id);
            const label = tr("users.tournaments.timeline.dotTitle", {
              name: t.name,
              placement: String(t.placement),
              count: String(t.count_teams)
            });
            const style: React.CSSProperties = {
              left: `${left}%`,
              top: `${top}%`,
              ...(isSelected ? { boxShadow: "0 0 0 3px var(--aqt-teal)", zIndex: 4 } : null)
            };
            if (onSelect) {
              return (
                <Button
                  key={t.id}
                  variant="ghost"
                  size="inline"
                  className={cn(DOT, DOT_HUE[cls])}
                  style={style}
                  title={label}
                  aria-label={label}
                  aria-pressed={isSelected}
                  onClick={() => onSelect(t.id)}
                />
              );
            }
            return <div key={t.id} className={cn(DOT, DOT_HUE[cls])} style={style} title={label} />;
          })}
        </div>
        <div className={cn(AXIS, "absolute right-3.5 bottom-1.5 left-12.5 flex justify-between")}>
          <span>{valid[0].name}</span>
          {n > 1 ? <span>{valid[n - 1].name}</span> : null}
        </div>
      </div>
      <div className="mt-3.5 flex flex-wrap gap-3.5 border-t border-[color:var(--aqt-border)] pt-3.5 text-label text-[color:var(--aqt-fg-muted)]">
        <span className="inline-flex items-center gap-1.5">
          <span className={cn(SWATCH, DOT_HUE.gold)} />
          {tr("users.tournaments.timeline.legend.first")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className={cn(SWATCH, DOT_HUE.silver)} />
          {tr("users.tournaments.timeline.legend.podium")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className={cn(SWATCH, DOT_HUE.mid)} />
          {tr("users.tournaments.timeline.legend.topHalf")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className={cn(SWATCH, DOT_HUE.bottom)} />
          {tr("users.tournaments.timeline.legend.bottomHalf")}
        </span>
      </div>
    </CardSurface>
  );
};

export default TournamentsPlacementTimeline;
