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
import type { BalanceVariant } from "@/components/balancer/workspace-helpers";

const INLINE_VARIANT_LIMIT = 8;

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

function VariantCard({ variant, isActive, onSelect, onDelete, className }: Readonly<VariantCardProps>) {
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
    // The delete control is a sibling of the card, not a child: a real
    // <button> nested inside another <button> is invalid HTML, and the old
    // role="button" span reimplemented Enter/Space by hand to dodge that.
    <div className={cn("group relative", className)}>
      <button
        type="button"
        onClick={onSelect}
        className={cn(
          "h-full w-full rounded-lg border px-3 py-2 text-left transition",
          isActive
            ? "border-primary/35 bg-primary/[0.12] text-[color:var(--aqt-fg)]"
            : "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]",
          onDelete ? "pr-9" : undefined
        )}
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{variant.label}</span>
        </div>
        {stats != null ? (
          <div className="mt-1.5 flex items-center gap-2.5">
            <span
              title={offRoleTooltip}
              className={cn(
                "flex items-center gap-1 text-label font-semibold tabular-nums",
                offRoles === 0
                  ? "text-[color:var(--aqt-fg-dim)]"
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
                "flex items-center gap-1 text-label font-semibold tabular-nums",
                collisions > 0 ? "text-primary/90" : "text-[color:var(--aqt-fg-dim)]"
              )}
            >
              <Shuffle className="h-3 w-3" />
              {collisions}
            </span>
            <span
              title="Benched"
              className={cn(
                "flex items-center gap-1 text-label font-semibold tabular-nums",
                benched > 0 ? "text-rose-300/90" : "text-[color:var(--aqt-fg-dim)]"
              )}
            >
              <UserX className="h-3 w-3" />
              {benched}
            </span>
            {stddev != null ? (
              <span
                title="StdDev"
                className="flex items-center gap-1 text-label font-semibold tabular-nums text-blue-300/70"
              >
                <BarChart2 className="h-3 w-3" />
                {stddev.toFixed(1)}
              </span>
            ) : null}
            {quality != null ? (
              <span
                title="Composite quality score (lower = better)"
                className="flex items-center gap-1 text-label font-semibold tabular-nums text-emerald-300/80"
              >
                <Sparkles className="h-3 w-3" />
                {quality.toFixed(2)}
              </span>
            ) : null}
          </div>
        ) : null}
      </button>
      {onDelete ? (
        <button
          type="button"
          onClick={onDelete}
          title="Delete variant"
          aria-label={`Delete ${variant.label}`}
          className="absolute right-2 top-2 rounded text-[color:var(--aqt-fg-muted)] opacity-0 transition-opacity hover:text-rose-400 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] group-hover:opacity-100"
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden />
        </button>
      ) : null}
    </div>
  );
}

export function VariantSelector({
  variants,
  activeVariantId,
  onSelectVariant,
  onDeleteVariant
}: Readonly<VariantSelectorProps>) {
  const [showAll, setShowAll] = useState(false);

  if (variants.length <= 1) return null;

  return (
    <>
      <div className="flex items-stretch gap-2">
        {/* Scrolls rather than `overflow-hidden`: a clipped half-card reads as a
            rendering bug, and the variants past the edge were unreachable
            without opening "Show all". */}
        <div className="flex min-w-0 flex-1 items-stretch gap-2 overflow-x-auto">
          {variants.slice(0, INLINE_VARIANT_LIMIT).map((variant) => (
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
          className="shrink-0 self-center border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
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
          <div className="grid max-h-[60vh] grid-cols-2 gap-2 overflow-y-auto pr-1 sm:grid-cols-3">
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
                className="w-full"
              />
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
