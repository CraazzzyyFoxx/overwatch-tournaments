import {
  AlertCircle,
  BarChart2,
  Camera,
  Check,
  CheckCircle2,
  Copy,
  Download,
  Info,
  Loader2,
  Shuffle,
  Sparkles,
  Upload,
  UserX
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { InternalBalancePayload } from "@/types/balancer-admin.types";
import type { FeasibilityReport } from "@/types/balancer.types";
import { MUTED_BUTTON_CLASS } from "./balancer-page-helpers";

type VariantStats = {
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

type BalanceActionsBarProps = {
  activeVariantStats: VariantStats;
  activeVariant: { payload: InternalBalancePayload } | null;
  canRunBalance: boolean;
  isSavePending: boolean;
  isExportPending: boolean;
  onRunBalance: () => void;
  onSaveBalance: () => void;
  onExportBalance: () => void;
  onDownloadJson: () => void;
  onCopyNames: () => void;
  onScreenshot: () => void;
};

export function BalanceActionsBar({
  activeVariantStats,
  activeVariant,
  canRunBalance,
  isSavePending,
  isExportPending,
  onRunBalance,
  onSaveBalance,
  onExportBalance,
  onDownloadJson,
  onCopyNames,
  onScreenshot
}: BalanceActionsBarProps) {
  return (
    <div className="flex flex-col gap-3 p-3 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex flex-wrap gap-2">
        {activeVariantStats?.mmr_std_dev != null ? (
          <Badge className="rounded-full border-blue-400/20 bg-blue-500/10 text-blue-200 hover:bg-blue-500/10">
            <BarChart2 className="mr-1.5 h-3.5 w-3.5" />
            StdDev {activeVariantStats.mmr_std_dev.toFixed(1)}
          </Badge>
        ) : null}
        {activeVariantStats?.off_role_count != null
          ? (() => {
              const count = activeVariantStats.off_role_count ?? 0;
              const aboveMin = activeVariantStats.off_role_above_minimum;
              const rate = activeVariantStats.off_role_rate;
              const structuralMin = activeVariantStats.feasibility?.structural_min_off_role;
              const ratePart = rate != null ? ` (${(rate * 100).toFixed(1)}%)` : "";
              const isOptimal = aboveMin === 0 && count > 0;
              const isPerfect = count === 0;
              const tooltip = (() => {
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
              const badgeClass =
                isPerfect || isOptimal
                  ? "rounded-full border-emerald-400/25 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/10"
                  : "rounded-full border-orange-400/20 bg-orange-500/10 text-orange-200 hover:bg-orange-500/10";
              const Icon = isPerfect || isOptimal ? CheckCircle2 : AlertCircle;
              const suffix = isOptimal
                ? " (optimal)"
                : aboveMin != null && aboveMin > 0
                  ? ` (+${aboveMin})`
                  : "";
              return (
                <Badge title={tooltip} className={badgeClass}>
                  <Icon className="mr-1.5 h-3.5 w-3.5" />
                  Off-role {count}
                  {ratePart}
                  {suffix}
                </Badge>
              );
            })()
          : null}
        {activeVariantStats?.feasibility?.roles?.map((role) => {
          const delta = role.supply - role.demand;
          const undersupply = delta < 0;
          const tooltip = `${role.role}: ${role.supply} supply / ${role.demand} demand${
            role.flex_supply > 0 ? ` (+${role.flex_supply} flex)` : ""
          }${undersupply ? ` — short by ${-delta}` : delta > 0 ? ` — surplus ${delta}` : ""}`;
          return (
            <Badge
              key={role.role}
              title={tooltip}
              className={cn(
                "rounded-full",
                undersupply
                  ? "border-rose-400/25 bg-rose-500/10 text-rose-200 hover:bg-rose-500/10"
                  : "border-sky-400/20 bg-sky-500/10 text-sky-200 hover:bg-sky-500/10"
              )}
            >
              {role.role} {role.supply}/{role.demand}
              {role.flex_supply > 0 ? ` +${role.flex_supply}f` : ""}
            </Badge>
          );
        }) ?? null}
        {activeVariantStats?.feasibility &&
        activeVariantStats.feasibility.structural_min_off_role > 0 ? (
          <Badge
            title={`At least ${activeVariantStats.feasibility.structural_min_off_role} off-role assignments are forced by the player pool — no balancer can do better.`}
            className="rounded-full border-amber-400/25 bg-amber-500/10 text-amber-200 hover:bg-amber-500/10"
          >
            <Info className="mr-1.5 h-3.5 w-3.5" />
            Min off-role {activeVariantStats.feasibility.structural_min_off_role}
          </Badge>
        ) : null}
        {activeVariantStats?.feasibility && activeVariantStats.feasibility.flex_player_count > 0 ? (
          <Badge
            title={`${activeVariantStats.feasibility.flex_player_count} flex players in the pool — they can fill any role they can play without counting as off-role.`}
            className="rounded-full border-primary/30 bg-primary/10 text-primary hover:bg-primary/10"
          >
            Flex {activeVariantStats.feasibility.flex_player_count}
          </Badge>
        ) : null}
        {activeVariantStats?.sub_role_collision_count != null ? (
          <Badge className="rounded-full border-primary/30 bg-primary/10 text-primary hover:bg-primary/10">
            <Shuffle className="mr-1.5 h-3.5 w-3.5" />
            Collisions {activeVariantStats.sub_role_collision_count}
          </Badge>
        ) : null}
        {activeVariantStats?.unbalanced_count != null ? (
          <Badge className="rounded-full border-rose-400/20 bg-rose-500/10 text-rose-200 hover:bg-rose-500/10">
            <UserX className="mr-1.5 h-3.5 w-3.5" />
            Benched {activeVariantStats.unbalanced_count}
          </Badge>
        ) : null}
        {activeVariantStats?.composite_score != null ? (
          <Badge
            title={`balance=${activeVariantStats.balance_objective_norm?.toFixed(3) ?? activeVariantStats.balance_objective?.toFixed(3) ?? "—"} comfort=${activeVariantStats.comfort_objective_norm?.toFixed(3) ?? activeVariantStats.comfort_objective?.toFixed(3) ?? "—"} (normalized 0..1)`}
            className="rounded-full border-emerald-400/20 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/10"
          >
            <Sparkles className="mr-1.5 h-3.5 w-3.5" />
            Quality {activeVariantStats.composite_score.toFixed(2)}
          </Badge>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          className={cn("rounded-xl", MUTED_BUTTON_CLASS)}
          onClick={onRunBalance}
          disabled={!canRunBalance || isExportPending}
        >
          <Sparkles className="mr-2 h-4 w-4" />
          Regenerate
        </Button>
        <Button
          type="button"
          className="rounded-xl bg-primary text-primary-foreground hover:bg-primary/90"
          onClick={onSaveBalance}
          disabled={!activeVariant || isSavePending || isExportPending}
        >
          {isSavePending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Check className="mr-2 h-4 w-4" />
          )}
          Save
        </Button>
        <Button
          type="button"
          variant="outline"
          className={cn("rounded-xl", MUTED_BUTTON_CLASS)}
          onClick={onExportBalance}
          disabled={!activeVariant || isExportPending || isSavePending}
        >
          {isExportPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Upload className="mr-2 h-4 w-4" />
          )}
          Export to Tournament
        </Button>
        <Button
          type="button"
          variant="outline"
          className={cn("rounded-xl", MUTED_BUTTON_CLASS)}
          onClick={onDownloadJson}
          disabled={!activeVariant}
        >
          <Download className="mr-2 h-4 w-4" />
          Download JSON
        </Button>
        <Button
          type="button"
          variant="outline"
          className={cn("rounded-xl", MUTED_BUTTON_CLASS)}
          onClick={onCopyNames}
          disabled={!activeVariant}
        >
          <Copy className="mr-2 h-4 w-4" />
          Copy
        </Button>
        <Button
          type="button"
          variant="outline"
          className={cn("rounded-xl", MUTED_BUTTON_CLASS)}
          onClick={onScreenshot}
          disabled={!activeVariant}
        >
          <Camera className="mr-2 h-4 w-4" />
          Image
        </Button>
      </div>
    </div>
  );
}
