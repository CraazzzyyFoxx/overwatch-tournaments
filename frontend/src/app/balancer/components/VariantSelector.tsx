import {
  AlertCircle,
  BarChart2,
  CheckCircle2,
  Shuffle,
  Sparkles,
  Trash2,
  UserX
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { BalanceVariant } from "./workspace-helpers";

type VariantSelectorProps = {
  variants: BalanceVariant[];
  activeVariantId: string | null;
  onSelectVariant: (id: string) => void;
  onDeleteVariant?: (id: string) => void;
};

export function VariantSelector({
  variants,
  activeVariantId,
  onSelectVariant,
  onDeleteVariant
}: VariantSelectorProps) {
  if (variants.length <= 1) return null;

  return (
    <div className="flex flex-wrap gap-2">
      {variants.map((variant) => {
        const isActive = variant.id === activeVariantId;
        const stats = variant.payload.statistics;
        const offRoles = stats?.off_role_count ?? 0;
        const offRoleAboveMin = stats?.off_role_above_minimum ?? null;
        const offRoleOptimal = offRoles === 0 || offRoleAboveMin === 0;
        const offRoleTooltip = (() => {
          if (offRoles === 0) return "All players on first preference";
          if (offRoleAboveMin === 0) return `Off-role ${offRoles} (structural minimum)`;
          if (offRoleAboveMin != null)
            return `Off-role ${offRoles} (+${offRoleAboveMin} above min)`;
          return `Off-role ${offRoles}`;
        })();
        const collisions = stats?.sub_role_collision_count ?? 0;
        const unbalanced = variant.payload.benched_players?.length ?? stats?.unbalanced_count ?? 0;
        const stddev = stats?.mmr_std_dev;
        const quality = stats?.composite_score;
        return (
          <button
            key={variant.id}
            type="button"
            onClick={() => onSelectVariant(variant.id)}
            className={cn(
              "group rounded-xl border px-3 py-2 text-left transition",
              isActive
                ? "border-primary/35 bg-primary/[0.12] text-white"
                : "border-white/8 bg-white/[0.02] text-white/55 hover:bg-white/[0.05] hover:text-white"
            )}
          >
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">{variant.label}</span>
              {onDeleteVariant ? (
                <span
                  role="button"
                  tabIndex={0}
                  title="Delete variant"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteVariant(variant.id);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      e.stopPropagation();
                      onDeleteVariant(variant.id);
                    }
                  }}
                  className="ml-auto opacity-0 transition-opacity group-hover:opacity-100 hover:text-rose-400"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </span>
              ) : null}
            </div>
            {stats != null ? (
              <div className="mt-1.5 flex items-center gap-2.5">
                <span
                  title={offRoleTooltip}
                  className={cn(
                    "flex items-center gap-1 text-[10px] font-semibold tabular-nums",
                    offRoles === 0
                      ? "text-white/30"
                      : offRoleOptimal
                        ? "text-emerald-300/90"
                        : "text-orange-300/90"
                  )}
                >
                  {offRoleOptimal && offRoles > 0 ? (
                    <CheckCircle2 className="h-3 w-3" />
                  ) : (
                    <AlertCircle className="h-3 w-3" />
                  )}
                  {offRoles}
                </span>
                <span
                  title="Sub-role collisions"
                  className={cn(
                    "flex items-center gap-1 text-[10px] font-semibold tabular-nums",
                    collisions > 0 ? "text-primary/90" : "text-white/30"
                  )}
                >
                  <Shuffle className="h-3 w-3" />
                  {collisions}
                </span>
                <span
                  title="Benched"
                  className={cn(
                    "flex items-center gap-1 text-[10px] font-semibold tabular-nums",
                    unbalanced > 0 ? "text-rose-300/90" : "text-white/30"
                  )}
                >
                  <UserX className="h-3 w-3" />
                  {unbalanced}
                </span>
                {stddev != null ? (
                  <span
                    title="StdDev"
                    className="flex items-center gap-1 text-[10px] font-semibold tabular-nums text-blue-300/70"
                  >
                    <BarChart2 className="h-3 w-3" />
                    {stddev.toFixed(1)}
                  </span>
                ) : null}
                {quality != null ? (
                  <span
                    title="Composite quality score (lower = better)"
                    className="flex items-center gap-1 text-[10px] font-semibold tabular-nums text-emerald-300/80"
                  >
                    <Sparkles className="h-3 w-3" />
                    {quality.toFixed(2)}
                  </span>
                ) : null}
              </div>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
