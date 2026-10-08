"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { CardSurface, ProfileStat } from "@/app/(site)/users/components/shared/atoms";
import { UserProfile, UserTournament } from "@/types/user.types";

interface Props {
  tournaments: UserTournament[];
  /** Career totals; the Titles figure prefers the profile count when present. */
  profile?: UserProfile | null;
  /** Tournament ids that belong to the currently-selected dossier event. */
  selectedIds?: number[];
  /** Selecting a point selects that event in the dossier (and scrolls to it). */
  onSelect?: (tournamentId: number) => void;
}

const colorClass = (placement: number, field: number): "gold" | "silver" | "bronze" | "mid" | "bottom" => {
  if (placement === 1) return "gold";
  if (placement <= 3) return "silver";
  if (placement <= 5) return "bronze";
  return placement / field < 0.5 ? "mid" : "bottom";
};

const TournamentsPlacementTimeline = ({ tournaments, profile = null, selectedIds = [], onSelect }: Props) => {
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
  const titles = profile?.tournaments_won ?? valid.filter((t) => t.placement === 1).length;

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
          value={String(titles)}
          color={titles > 0 ? "var(--aqt-gold)" : undefined}
        />
        <ProfileStat
          label={tr("users.tournaments.kpi.podiumRate")}
          value={`${podiumRate}%`}
          sub={tr("users.tournaments.kpi.ofEvents", { podium: String(podiumCount), total: String(n) })}
        />
        <ProfileStat label={tr("users.tournaments.kpi.best")} value={String(bestPlacement)} />
      </div>
      <div className="aqt-timeline mt-5">
        <div className="aqt-y-axis">
          <span>{tr("users.tournaments.timeline.axisTop")}</span>
          <span>33%</span>
          <span>66%</span>
          <span>{tr("users.tournaments.timeline.axisLast")}</span>
        </div>
        <div className="aqt-ln">
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
                <button
                  key={t.id}
                  type="button"
                  className={`aqt-dot ${cls} appearance-none p-0`}
                  style={style}
                  title={label}
                  aria-label={label}
                  aria-pressed={isSelected}
                  onClick={() => onSelect(t.id)}
                />
              );
            }
            return <div key={t.id} className={`aqt-dot ${cls}`} style={style} title={label} />;
          })}
        </div>
        <div className="aqt-x-axis">
          <span>{valid[0].name}</span>
          {n > 1 ? <span>{valid[n - 1].name}</span> : null}
        </div>
      </div>
      <div className="mt-3.5 flex flex-wrap gap-3.5 border-t border-[color:var(--aqt-border)] pt-3.5 text-label text-[color:var(--aqt-fg-muted)]">
        <span className="inline-flex items-center gap-1.5">
          {/* Must stay identical to `.aqt-timeline .aqt-dot.gold` in user-profile.css. */}
          <span
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{
              background:
                "linear-gradient(135deg, var(--aqt-medal-gold), color-mix(in srgb, var(--aqt-medal-gold) 65%, black))"
            }}
          />
          {tr("users.tournaments.timeline.legend.first")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          {/* Must stay identical to `.aqt-timeline .aqt-dot.silver` in user-profile.css. */}
          <span
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{
              background:
                "linear-gradient(135deg, var(--aqt-medal-silver), color-mix(in srgb, var(--aqt-medal-silver) 65%, black))"
            }}
          />
          {tr("users.tournaments.timeline.legend.podium")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "var(--aqt-teal)" }} />
          {tr("users.tournaments.timeline.legend.topHalf")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "var(--aqt-rose)" }} />
          {tr("users.tournaments.timeline.legend.bottomHalf")}
        </span>
      </div>
    </CardSurface>
  );
};

export default TournamentsPlacementTimeline;
