import { useState } from "react";
import {
  AlertCircle,
  BarChart2,
  CheckCircle2,
  LayoutGrid,
  Shuffle,
  Sparkles,
  Trash2,
  UserX
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import type { BalanceVariant } from "./workspace-helpers";

type VariantSelectorProps = {
  variants: BalanceVariant[];
  activeVariantId: string | null;
  onSelectVariant: (id: string) => void;
  onDeleteVariant?: (id: string) => void;
};

type VariantCardProps = {
  variant: BalanceVariant;
  isActive: boolean;
  onSelect: () => void;
  onDelete?: () => void;
  className?: string;
};

function VariantCard({ variant, isActive, onSelect, onDelete, className }: VariantCardProps) {
  const stats = variant.payload.statistics;
  const offRoles = stats?.off_role_count ?? 0;
  const offRoleAboveMin = stats?.off_role_above_minimum ?? null;
  const offRoleOptimal = offRoles === 0 || offRoleAboveMin === 0;
  const offRoleTooltip = (() => {
    if (offRoles === 0) return "All players on first preference";
    if (offRoleAboveMin === 0) return `Off-role ${offRoles} (structural minimum)`;
    if (offRoleAboveMin != null) return `Off-role ${offRoles} (+${offRoleAboveMin} above min)`;
    return `Off-role ${offRoles}`;
  })();
  const collisions = stats?.sub_role_collision_count ?? 0;
  const benched = variant.payload.benched_players?.length ?? stats?.unbalanced_count ?? 0;
  const stddev = stats?.mmr_std_dev;
  const quality = stats?.composite_score;

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "group rounded-xl border px-3 py-2 text-left transition",
        isActive
          ? "border-primary/35 bg-primary/[0.12] text-white"
          : "border-white/8 bg-white/[0.02] text-white/55 hover:bg-white/[0.05] hover:text-white",
        className
      )}
    >
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">{variant.label}</span>
        {onDelete ? (
          <span
            role="button"
            tabIndex={0}
            title="Delete variant"
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                e.stopPropagation();
                onDelete();
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
              benched > 0 ? "text-rose-300/90" : "text-white/30"
            )}
          >
            <UserX className="h-3 w-3" />
            {benched}
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
}

export function VariantSelector({
  variants,
  activeVariantId,
  onSelectVariant,
  onDeleteVariant
}: VariantSelectorProps) {
  const [showAll, setShowAll] = useState(false);

  if (variants.length <= 1) return null;

  return (
    <>
      <div className="flex items-stretch gap-2">
        <div className="flex min-w-0 flex-1 items-stretch gap-2 overflow-x-auto pb-1">
          {variants.map((variant) => (
            <VariantCard
              key={variant.id}
              variant={variant}
              isActive={variant.id === activeVariantId}
              onSelect={() => onSelectVariant(variant.id)}
              onDelete={onDeleteVariant ? () => onDeleteVariant(variant.id) : undefined}
              className="shrink-0"
            />
          ))}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setShowAll(true)}
          className="shrink-0 self-center border border-white/8 bg-white/[0.02] text-white/70 hover:bg-white/[0.05] hover:text-white"
        >
          <LayoutGrid className="h-3.5 w-3.5" />
          Show all
        </Button>
      </div>

      <Dialog open={showAll} onOpenChange={setShowAll}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>All balances</DialogTitle>
            <DialogDescription>
              Compare every generated variant and select one to load it into the editor.
            </DialogDescription>
          </DialogHeader>
          <div className="flex max-h-[60vh] flex-wrap gap-2 overflow-y-auto pr-1">
            {variants.map((variant) => (
              <VariantCard
                key={variant.id}
                variant={variant}
                isActive={variant.id === activeVariantId}
                onSelect={() => {
                  onSelectVariant(variant.id);
                  setShowAll(false);
                }}
                onDelete={onDeleteVariant ? () => onDeleteVariant(variant.id) : undefined}
              />
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
