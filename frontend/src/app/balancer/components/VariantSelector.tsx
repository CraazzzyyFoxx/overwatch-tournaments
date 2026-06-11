import { AlertCircle, CheckCircle2, Sparkles, Trash2 } from "lucide-react";
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
    <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
      {variants.map((variant) => {
        const isActive = variant.id === activeVariantId;
        const stats = variant.payload.statistics;
        const offRoles = stats?.off_role_count ?? 0;
        const offRoleAboveMin = stats?.off_role_above_minimum ?? null;
        const offRoleOptimal = offRoles === 0 || offRoleAboveMin === 0;
        const collisions = stats?.sub_role_collision_count ?? 0;
        const benched = variant.payload.benched_players?.length ?? stats?.unbalanced_count ?? 0;
        const stddev = stats?.mmr_std_dev;
        const quality = stats?.composite_score;
        const isHealthy = offRoleOptimal && collisions === 0 && benched === 0;
        const shortLabel = variant.label.match(/\d+/)?.[0] ?? variant.label;

        const tooltip = (() => {
          if (stats == null) return variant.label;
          const offRolePart =
            offRoles === 0
              ? "Off-role 0"
              : offRoleAboveMin != null
                ? `Off-role ${offRoles} (+${offRoleAboveMin} above min)`
                : `Off-role ${offRoles}`;
          return [
            variant.label,
            offRolePart,
            `Collisions ${collisions}`,
            `Benched ${benched}`,
            stddev != null ? `StdDev ${stddev.toFixed(1)}` : null,
            quality != null ? `Quality ${quality.toFixed(2)}` : null
          ]
            .filter(Boolean)
            .join(" · ");
        })();

        return (
          <button
            key={variant.id}
            type="button"
            onClick={() => onSelectVariant(variant.id)}
            title={tooltip}
            className={cn(
              "group flex shrink-0 items-center gap-1.5 rounded-lg border px-2 py-1 text-xs transition",
              isActive
                ? "border-primary/35 bg-primary/[0.12] text-white"
                : "border-white/8 bg-white/[0.02] text-white/55 hover:bg-white/[0.05] hover:text-white"
            )}
          >
            {stats != null ? (
              isHealthy ? (
                <CheckCircle2 className="h-3 w-3 shrink-0 text-emerald-300/90" />
              ) : (
                <AlertCircle className="h-3 w-3 shrink-0 text-orange-300/90" />
              )
            ) : null}
            <span className="font-semibold tabular-nums">#{shortLabel}</span>
            {quality != null ? (
              <span className="flex items-center gap-0.5 text-[10px] font-semibold tabular-nums text-emerald-300/80">
                <Sparkles className="h-2.5 w-2.5" />
                {quality.toFixed(2)}
              </span>
            ) : null}
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
                className="opacity-0 transition-opacity group-hover:opacity-100 hover:text-rose-400"
              >
                <Trash2 className="h-3 w-3" />
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
