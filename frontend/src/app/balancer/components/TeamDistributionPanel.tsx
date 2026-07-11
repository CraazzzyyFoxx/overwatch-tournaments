import { useMemo, type ReactNode } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";
import { PANEL_CLASS, TEAM_BADGE_ACCENTS } from "./balancer-page-helpers";
import { calculateTeamAverageFromPayload } from "./balancer-page-helpers";
import type { BalanceVariant } from "./workspace-helpers";

type TeamDistributionPanelProps = {
  variant: BalanceVariant;
  variantSelector?: ReactNode;
};

type DistributionPoint = {
  id: number;
  average: number;
  position: number;
  accent: string;
};

type DistributionBucket = {
  key: number;
  position: number;
  points: DistributionPoint[];
};

export function TeamDistributionPanel({ variant, variantSelector }: TeamDistributionPanelProps) {
  const [collapsed, setCollapsed] = useLocalStorageState<boolean>(
    "balancer:distribution-collapsed",
    true
  );

  const teamAverages = useMemo(
    () => variant.payload.teams.map(calculateTeamAverageFromPayload),
    [variant.payload.teams]
  );

  const average =
    teamAverages.length > 0
      ? Math.round(teamAverages.reduce((s, v) => s + v, 0) / teamAverages.length)
      : null;
  const min = teamAverages.length > 0 ? Math.min(...teamAverages) : null;
  const max = teamAverages.length > 0 ? Math.max(...teamAverages) : null;
  const spread = min != null && max != null ? max - min : null;
  const stats = variant.payload.statistics ?? null;

  const distributionPoints = useMemo<DistributionPoint[]>(
    () =>
      variant.payload.teams.map((team, teamIndex) => {
        const teamAvg = teamAverages[teamIndex] ?? calculateTeamAverageFromPayload(team);
        const position =
          min == null || max == null || min === max ? 50 : ((teamAvg - min) / (max - min)) * 100;
        return {
          id: team.id,
          average: teamAvg,
          position,
          accent: TEAM_BADGE_ACCENTS[teamIndex % TEAM_BADGE_ACCENTS.length]
        };
      }),
    [variant.payload.teams, teamAverages, min, max]
  );

  const buckets = useMemo<DistributionBucket[]>(() => {
    const map = new Map<number, DistributionPoint[]>();
    for (const point of distributionPoints) {
      const key = Math.round(point.position * 2) / 2;
      const arr = map.get(key) ?? [];
      arr.push(point);
      map.set(key, arr);
    }
    return [...map.entries()]
      .map(([key, points]) => ({
        key,
        position: points.reduce((sum, p) => sum + p.position, 0) / points.length,
        points: [...points].sort((a, b) => a.id - b.id)
      }))
      .sort((a, b) => a.position - b.position);
  }, [distributionPoints]);

  return (
    <div className={cn(PANEL_CLASS, "px-3 py-2")}>
      {variantSelector ? <div className="mb-2">{variantSelector}</div> : null}
      <div className="flex items-center gap-3">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-[11px] uppercase tracking-[0.16em] text-[color:var(--aqt-fg-faint)]">
            Team distribution
          </span>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs tabular-nums text-[color:var(--aqt-fg-muted)]">
            <span>
              <span className="text-[color:var(--aqt-fg-dim)]">Avg</span>{" "}
              <span className="font-semibold text-cyan-300">
                {average ?? stats?.average_mmr ?? "-"}
              </span>
            </span>
            <span>
              <span className="text-[color:var(--aqt-fg-dim)]">Spread</span>{" "}
              <span className="font-semibold text-amber-300">{spread ?? "-"}</span>
            </span>
            <span>
              <span className="text-[color:var(--aqt-fg-dim)]">Range</span> {min ?? "-"}
              {min != null && max != null ? `–${max}` : ""}
            </span>
            <span>
              <span className="text-[color:var(--aqt-fg-dim)]">σ</span>{" "}
              {stats?.mmr_std_dev != null ? stats.mmr_std_dev.toFixed(1) : "-"}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          aria-expanded={!collapsed}
          aria-label={collapsed ? "Expand team distribution chart" : "Collapse team distribution chart"}
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[color:var(--aqt-fg-dim)] transition hover:bg-white/5 hover:text-[color:var(--aqt-fg-muted)]"
        >
          {collapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
        </button>
      </div>

      {collapsed ? null : (
      <div className="mt-2 rounded-xl border border-[color:var(--aqt-border)] bg-black/15 px-3 py-2">
        <div className="relative min-h-8">
          <div className="absolute inset-x-0 top-1/2 h-3 -translate-y-1/2 rounded-full bg-white/4" />
          {buckets.map((bucket) => {
            const clampedLeft = Math.max(4, Math.min(bucket.position, 96));
            const isGroup = bucket.points.length > 1;
            const bucketTitle = isGroup
              ? `Teams ${bucket.points.map((p) => p.id).join(", ")} — avg ${Math.round(bucket.points[0].average)}`
              : `Team ${bucket.points[0].id} — avg ${Math.round(bucket.points[0].average)}`;

            // Adaptive anchor: pin to left/right edge when bucket is near the
            // corresponding side, so wide groups stay inside the track.
            const anchorClass =
              bucket.position < 15
                ? "translate-x-0"
                : bucket.position > 85
                  ? "-translate-x-full"
                  : "-translate-x-1/2";
            const wrapJustifyClass =
              bucket.position < 15
                ? "justify-start"
                : bucket.position > 85
                  ? "justify-end"
                  : "justify-center";

            return (
              <div
                key={bucket.key}
                className={cn("absolute top-1/2 -translate-y-1/2 max-w-[42%]", anchorClass)}
                style={{ left: `${clampedLeft}%` }}
                title={bucketTitle}
              >
                {isGroup ? (
                  <div
                    className={cn(
                      "relative flex flex-row flex-wrap items-center gap-y-0.5 rounded-lg bg-white/4 p-0.5 ring-1 ring-[color:var(--aqt-border-2)] backdrop-blur-sm",
                      wrapJustifyClass
                    )}
                  >
                    {bucket.points.map((point, stackIndex) => (
                      <span
                        key={point.id}
                        className={cn(
                          "inline-flex h-6 min-w-6 items-center justify-center rounded-md border px-1.5 text-[10px] font-semibold shadow-[0_1px_3px_rgba(0,0,0,0.35)]",
                          point.accent,
                          stackIndex === 0 ? "" : "-ml-1"
                        )}
                        style={{ zIndex: bucket.points.length - stackIndex }}
                      >
                        {point.id}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span
                    className={cn(
                      "inline-flex h-7 min-w-7 items-center justify-center rounded-lg border px-2 text-[11px] font-semibold",
                      bucket.points[0].accent
                    )}
                  >
                    {bucket.points[0].id}
                  </span>
                )}
              </div>
            );
          })}
        </div>
        <div className="mt-2 flex items-center justify-between text-[10px] text-[color:var(--aqt-fg-faint)]">
          <span>{min ?? "-"}</span>
          <span>{max ?? "-"}</span>
        </div>
      </div>
      )}
    </div>
  );
}
