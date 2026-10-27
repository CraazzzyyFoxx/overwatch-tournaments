"use client";

import { AlertCircle, BarChart2, CheckCircle2, ChevronDown, Shuffle, Sparkles, UserX } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
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

/**
 * The bar carries up to ten stats. Past ~1536px of viewport the row wrapped and doubled the
 * toolbar's height, so only the stats you act on stay inline: how good the balance is, and
 * whether anyone was left out. The pool diagnostics that explain *why* the balancer could not do
 * better — per-role supply, the structural off-role floor, flex headroom — sit one click away.
 */
export function BalanceStatsRow({ stats }: Readonly<{ stats: VariantStats }>) {
  const t = useTranslations("balancerTool.page.stats");
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
          shape="pill"
          tone="success"
          title={t("objectives", {
            balance: stats.balance_objective_norm?.toFixed(3) ?? stats.balance_objective?.toFixed(3) ?? "—",
            comfort: stats.comfort_objective_norm?.toFixed(3) ?? stats.comfort_objective?.toFixed(3) ?? "—"
          })}
          className="tabular-nums"
        >
          <Sparkles className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          {t("quality", { score: stats.composite_score.toFixed(2) })}
        </Badge>
      ) : null}

      {stats.mmr_std_dev != null ? (
        <Badge shape="pill" tone="info" title={t("stdDevHint")} className="tabular-nums">
          <BarChart2 className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          {t("stdDev", { value: stats.mmr_std_dev.toFixed(1) })}
        </Badge>
      ) : null}

      <OffRoleChip stats={stats} />

      {benched != null && benched > 0 ? (
        <Badge shape="pill" tone="danger" title={t("benchedHint", { count: benched })} className="tabular-nums">
          <UserX className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          {t("benched", { count: benched })}
        </Badge>
      ) : null}

      {collisions != null && collisions > 0 ? (
        <Badge shape="pill" tone="accent" title={t("collisionsHint", { count: collisions })} className="tabular-nums">
          <Shuffle className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          {t("collisions", { count: collisions })}
        </Badge>
      ) : null}

      {feasibility ? (
        <Popover>
          <PopoverTrigger asChild>
            <Button
              type="button"
              variant={shortfall > 0 ? "destructive" : "outline"}
              size="xs"
              aria-label={t("poolAria")}
              className={cn(
                "rounded-full tabular-nums",
                shortfall === 0 && "text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]",
              )}
            >
              {t("pool")}
              {shortfall > 0 ? ` −${shortfall}` : ""}
              <ChevronDown aria-hidden="true" />
            </Button>
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
  const t = useTranslations("balancerTool.page.stats");
  const count = stats.off_role_count;
  if (count == null) {
    return null;
  }

  const aboveMin = stats.off_role_above_minimum;
  const structuralMin = stats.feasibility?.structural_min_off_role;
  const isPerfect = count === 0;
  const isOptimal = aboveMin === 0 && count > 0;
  const ratePart = stats.off_role_rate != null ? ` (${(stats.off_role_rate * 100).toFixed(1)}%)` : "";
  const suffix = isOptimal ? ` (${t("optimal")})` : aboveMin != null && aboveMin > 0 ? ` (+${aboveMin})` : "";

  const title = (() => {
    if (isPerfect) return t("offRolePerfect");
    if (isOptimal) {
      return structuralMin != null ? t("offRoleMinimum", { count }) : t("offRoleCount", { count });
    }
    if (aboveMin != null && structuralMin != null) {
      return t("offRoleAboveMin", { count, above: aboveMin, min: structuralMin });
    }
    return t("offRoleCount", { count });
  })();

  const Icon = isPerfect || isOptimal ? CheckCircle2 : AlertCircle;

  return (
    <Badge shape="pill" tone={isPerfect || isOptimal ? "success" : "warning"} title={title} className="tabular-nums">
      <Icon className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
      {t("offRole", { count })}
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
  const t = useTranslations("balancerTool.page.stats");
  const rows: Array<{ label: string; value: string; hint?: string; tone?: "warn" }> = [];

  if (feasibility.structural_min_off_role > 0) {
    rows.push({
      label: t("offRoleFloor"),
      value: String(feasibility.structural_min_off_role),
      hint: t("offRoleFloorHint"),
    });
  }
  rows.push({ label: t("flexPlayers"), value: String(feasibility.flex_player_count) });
  if (stats.sub_role_collision_count === 0) {
    rows.push({ label: t("collisionsLabel"), value: "0" });
  }
  if (stats.unbalanced_count === 0) {
    rows.push({ label: t("benchedLabel"), value: "0" });
  }

  return (
    <div className="text-xs">
      <Eyebrow as="div" tone="muted" className="border-b border-border/60 px-3 py-2">
        {t("roleSupply")}
      </Eyebrow>
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
                  {role.flex_supply > 0 ? t("flexSupply", { count: role.flex_supply }) : ""}
                </td>
                <td
                  className={cn(
                    "px-3 py-1.5 text-right font-medium tabular-nums",
                    delta < 0 ? "text-rose-300" : "text-emerald-300",
                  )}
                >
                  {delta < 0 ? t("short", { count: -delta }) : delta > 0 ? `+${delta}` : t("even")}
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
