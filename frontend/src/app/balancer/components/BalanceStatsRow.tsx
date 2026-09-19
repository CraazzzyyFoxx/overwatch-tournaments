"use client";

import { AlertCircle, BarChart2, CheckCircle2, ChevronDown, Shuffle, Sparkles, UserX } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { FeasibilityReport } from "@/types/balancer.types";

export type VariantStats = {
  mmr_std_dev?: number | null;
  off_role_count?: number | null;
  sub_role_collision_count?: number | null;
  unbalanced_count?: number | null;
  composite_score?: number | null;
  balance_objective?: number | null;
  comfort_objective?: number | null;
  balance_objective_norm?: number | null;
  comfort_objective_norm?: number | null;
  off_role_rate?: number | null;
  off_role_above_minimum?: number | null;
  feasibility?: FeasibilityReport | null;
} | null;

const CHIP_CLASS = "rounded-full whitespace-nowrap tabular-nums";

/**
 * The bar carries up to ten stats. Past ~1536px of viewport the row wrapped and doubled the
 * toolbar's height, so only the stats you act on stay inline: how good the balance is, and
 * whether anyone was left out. The pool diagnostics that explain *why* the balancer could not do
 * better — per-role supply, the structural off-role floor, flex headroom — sit one click away.
 */
export function BalanceStatsRow({ stats }: Readonly<{ stats: VariantStats }>) {
  if (!stats) {
    return null;
  }

  const feasibility = stats.feasibility ?? null;
  const roles = feasibility?.roles ?? [];
  const shortfall = roles.reduce((total, role) => total + Math.max(0, role.demand - role.supply), 0);
  const collisions = stats.sub_role_collision_count;
  const benched = stats.unbalanced_count;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {stats.composite_score != null ? (
        <Badge
          title={`balance=${stats.balance_objective_norm?.toFixed(3) ?? stats.balance_objective?.toFixed(3) ?? "—"} comfort=${stats.comfort_objective_norm?.toFixed(3) ?? stats.comfort_objective?.toFixed(3) ?? "—"} (normalized 0..1)`}
          className={cn(CHIP_CLASS, "border-emerald-400/20 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/10")}
        >
          <Sparkles className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          Quality {stats.composite_score.toFixed(2)}
        </Badge>
      ) : null}

      {stats.mmr_std_dev != null ? (
        <Badge
          title="Standard deviation of team MMR — lower means the teams are closer together."
          className={cn(CHIP_CLASS, "border-blue-400/20 bg-blue-500/10 text-blue-200 hover:bg-blue-500/10")}
        >
          <BarChart2 className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          StdDev {stats.mmr_std_dev.toFixed(1)}
        </Badge>
      ) : null}

      <OffRoleChip stats={stats} />

      {benched != null && benched > 0 ? (
        <Badge
          title={`${benched} players did not make a team.`}
          className={cn(CHIP_CLASS, "border-rose-400/20 bg-rose-500/10 text-rose-200 hover:bg-rose-500/10")}
        >
          <UserX className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          Benched {benched}
        </Badge>
      ) : null}

      {collisions != null && collisions > 0 ? (
        <Badge
          title={`${collisions} teams pair players with the same sub-role.`}
          className={cn(CHIP_CLASS, "border-primary/30 bg-primary/10 text-primary hover:bg-primary/10")}
        >
          <Shuffle className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          Collisions {collisions}
        </Badge>
      ) : null}

      {feasibility ? (
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label="Pool diagnostics: role supply, off-role floor, flex headroom"
              className={cn(
                "inline-flex items-center whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-semibold tabular-nums transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                shortfall > 0
                  ? "border-rose-400/25 bg-rose-500/10 text-rose-200 hover:bg-rose-500/15"
                  : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]",
              )}
            >
              Pool{shortfall > 0 ? ` −${shortfall}` : ""}
              <ChevronDown className="ml-1 h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-72 p-0">
            <PoolDiagnostics stats={stats} feasibility={feasibility} />
          </PopoverContent>
        </Popover>
      ) : null}
    </div>
  );
}

function OffRoleChip({ stats }: Readonly<{ stats: NonNullable<VariantStats> }>) {
  const count = stats.off_role_count;
  if (count == null) {
    return null;
  }

  const aboveMin = stats.off_role_above_minimum;
  const structuralMin = stats.feasibility?.structural_min_off_role;
  const isPerfect = count === 0;
  const isOptimal = aboveMin === 0 && count > 0;
  const ratePart = stats.off_role_rate != null ? ` (${(stats.off_role_rate * 100).toFixed(1)}%)` : "";
  const suffix = isOptimal ? " (optimal)" : aboveMin != null && aboveMin > 0 ? ` (+${aboveMin})` : "";

  const title = (() => {
    if (isPerfect) return "All players assigned to their first preference.";
    if (isOptimal) {
      return structuralMin != null
        ? `${count} off-role assignments — structural minimum for this dataset (no balancer can do better).`
        : `${count} off-role assignments.`;
    }
    if (aboveMin != null && structuralMin != null) {
      return `${count} off-role assignments — ${aboveMin} above the structural minimum of ${structuralMin}.`;
    }
    return `${count} off-role assignments.`;
  })();

  const Icon = isPerfect || isOptimal ? CheckCircle2 : AlertCircle;

  return (
    <Badge
      title={title}
      className={cn(
        CHIP_CLASS,
        isPerfect || isOptimal
          ? "border-emerald-400/25 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/10"
          : "border-orange-400/20 bg-orange-500/10 text-orange-200 hover:bg-orange-500/10",
      )}
    >
      <Icon className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
      Off-role {count}
      {ratePart}
      {suffix}
    </Badge>
  );
}

function PoolDiagnostics({
  stats,
  feasibility,
}: Readonly<{
  stats: NonNullable<VariantStats>;
  feasibility: FeasibilityReport;
}>) {
  const rows: Array<{ label: string; value: string; hint?: string; tone?: "warn" }> = [];

  if (feasibility.structural_min_off_role > 0) {
    rows.push({
      label: "Off-role floor",
      value: String(feasibility.structural_min_off_role),
      hint: "Forced by the pool — no balancer can go below this.",
    });
  }
  rows.push({ label: "Flex players", value: String(feasibility.flex_player_count) });
  if (stats.sub_role_collision_count === 0) {
    rows.push({ label: "Sub-role collisions", value: "0" });
  }
  if (stats.unbalanced_count === 0) {
    rows.push({ label: "Benched", value: "0" });
  }

  return (
    <div className="text-xs">
      <div className="border-b border-border/60 px-3 py-2 text-label font-medium uppercase tracking-label text-muted-foreground">
        Role supply
      </div>
      <table className="w-full">
        <tbody>
          {feasibility.roles.map((role) => {
            const delta = role.supply - role.demand;

            return (
              <tr key={role.role} className="border-b border-border/40 last:border-0">
                <th scope="row" className="px-3 py-1.5 text-left font-medium text-foreground">
                  {role.role}
                </th>
                <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                  {role.supply}/{role.demand}
                </td>
                <td className="py-1.5 pl-2 text-right tabular-nums text-muted-foreground">
                  {role.flex_supply > 0 ? `+${role.flex_supply}f` : ""}
                </td>
                <td
                  className={cn(
                    "px-3 py-1.5 text-right font-medium tabular-nums",
                    delta < 0 ? "text-rose-300" : "text-emerald-300",
                  )}
                >
                  {delta < 0 ? `short ${-delta}` : delta > 0 ? `+${delta}` : "even"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <dl className="border-t border-border/60">
        {rows.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-3 px-3 py-1.5">
            <dt className="text-muted-foreground">
              {row.label}
              {row.hint ? <p className="mt-0.5 text-label text-muted-foreground/70">{row.hint}</p> : null}
            </dt>
            <dd className="shrink-0 font-medium tabular-nums text-foreground">{row.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
