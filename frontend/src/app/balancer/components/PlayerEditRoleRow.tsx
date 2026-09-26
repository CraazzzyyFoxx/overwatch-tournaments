"use client";

import { Sparkles, Trash2 } from "lucide-react";
import { SortableGrip, useSortableRow } from "@/components/kit/SortableRows";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type {
  BalancerPlayerRoleEntry,
  BalancerRoleCode,
  BalancerRoleSubtype
} from "@/types/balancer-admin.types";

import { ROLE_DISPLAY } from "./playerEditSheet.model";
import { ROLE_RANK_ACCENTS, RoleRankControls } from "./RoleRankControls";

type SortableRoleEntryProps = {
  id: string;
  entry: BalancerPlayerRoleEntry;
  index: number;
  resolveDivision: (rankValue: number | null) => number | null;
  getDivisionName: (divisionNumber: number | null) => string | null;
  onUpdate: (index: number, next: BalancerPlayerRoleEntry) => void;
  onRemove: (index: number) => void;
  subtypeOptions: Record<BalancerRoleCode, Array<{ value: string; label: string }>>;
};

export function SortableRoleEntry({
  id,
  entry,
  index,
  resolveDivision,
  getDivisionName,
  onUpdate,
  onRemove,
  subtypeOptions
}: Readonly<SortableRoleEntryProps>) {
  const { ref, style, handleProps } = useSortableRow(id);

  const accent = ROLE_RANK_ACCENTS[entry.role];
  // This card is the organizer's EDITING view, so every visual here follows the
  // declared flag. `is_active` is the resolver's "in play" verdict and belongs
  // to the pool/validation views: dimming a declared-on role because its rank is
  // still missing would grey out exactly the field that fixes it.
  const declaredActive = entry.is_declared_active;

  const roleSubtypeOptions = subtypeOptions[entry.role] || [];
  const subtypeLabel = entry.subtype
    ? (roleSubtypeOptions.find((option) => option.value === entry.subtype)?.label ?? entry.subtype)
    : null;
  const hasSubtypeOptions = roleSubtypeOptions.length > 0;

  // Live OW rank (already mapped to the workspace grid) as a one-click suggestion.
  // Always shown for the role; actionable when an OW rank is available.
  const owRankValue = entry.ow_rank_value ?? null;
  const owSuggestionDivision = owRankValue != null ? resolveDivision(owRankValue) : null;
  const owSuggestionName = owSuggestionDivision != null ? getDivisionName(owSuggestionDivision) : null;
  const owMatchesCurrent = owRankValue != null && owRankValue === entry.rank_value;
  const owActionLabel = entry.rank_value == null ? "Use" : owMatchesCurrent ? "Matches" : "Apply";

  return (
    <div
      ref={ref}
      style={style}
      className={cn(
        "grid gap-2 rounded-xl border p-2.5 transition-colors md:grid-cols-[32px_minmax(0,1fr)]",
        declaredActive
          ? cn("border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)]", accent.row)
          : "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] opacity-80"
      )}
    >
      <div className="flex items-center justify-between md:flex-col md:items-center md:justify-center md:gap-1">
        <SortableGrip
          handleProps={handleProps}
          label={`Reorder ${ROLE_DISPLAY[entry.role]}`}
        />
        <span className="text-label font-semibold text-[color:var(--aqt-fg-dim)]">#{index + 1}</span>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <PlayerRoleIcon role={ROLE_DISPLAY[entry.role]} size={15} decorative />
            <span
              className={cn(
                "text-xs font-semibold",
                declaredActive ? accent.text : "text-[color:var(--aqt-fg-muted)]"
              )}
            >
              {ROLE_DISPLAY[entry.role]}
            </span>
            {subtypeLabel ? (
              <Badge className={cn("h-4 border px-1.5 text-label", accent.chip)}>
                {subtypeLabel}
              </Badge>
            ) : null}
          </div>

          <div className="flex items-center gap-1.5">
            <div className="flex h-6 items-center gap-1.5 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2">
              <Switch
                checked={declaredActive}
                className="h-4 w-7 [&>span]:h-3 [&>span]:w-3 data-[state=checked]:[&>span]:translate-x-3"
                onCheckedChange={(checked) =>
                  onUpdate(index, { ...entry, is_declared_active: checked })
                }
                aria-label={declaredActive ? "Disable role" : "Enable role"}
              />
              <span
                className={cn(
                  "text-label font-semibold uppercase tracking-label",
                  declaredActive ? accent.text : "text-[color:var(--aqt-fg-dim)]"
                )}
              >
                {declaredActive ? "Active" : "Off"}
              </span>
            </div>

            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 shrink-0 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-[color:var(--aqt-fg-dim)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
              aria-label={`Remove ${ROLE_DISPLAY[entry.role]}`}
              onClick={() => onRemove(index)}
            >
              <Trash2 className="h-3 w-3" aria-hidden="true" />
            </Button>
          </div>
        </div>

        <div className="grid gap-2 lg:grid-cols-[minmax(0,140px)_minmax(0,1fr)_130px]">
          <div className="space-y-1">
            <span className="text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
              Sub-role
            </span>
            <Select
              value={entry.subtype ?? "none"}
              disabled={!hasSubtypeOptions}
              onValueChange={(value) =>
                onUpdate(index, {
                  ...entry,
                  subtype: value === "none" ? null : (value as BalancerRoleSubtype)
                })
              }
            >
              <SelectTrigger
                className={cn(
                  "h-7 w-full border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2 text-xs text-[color:var(--aqt-fg)]",
                  !declaredActive && "text-[color:var(--aqt-fg-dim)]"
                )}
              >
                <SelectValue placeholder="Sub-role" />
              </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No sub-role</SelectItem>
              {roleSubtypeOptions.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
            </Select>
          </div>

          <RoleRankControls
            rankValue={entry.rank_value}
            sourceLabel={
              entry.rank_source && entry.rank_source !== "none" ? entry.rank_source : null
            }
            accent={accent}
            active={declaredActive}
            onClear={
              entry.rank_value == null
                ? null
                : () => onUpdate(index, { ...entry, rank_value: null, division_number: null })
            }
            onChange={(rankValue, divisionNumber) =>
              onUpdate(index, { ...entry, rank_value: rankValue, division_number: divisionNumber })
            }
          />
        </div>

        {owRankValue != null ? (
          <button
            type="button"
            onClick={() =>
              onUpdate(index, {
                ...entry,
                rank_value: owRankValue,
                division_number: owSuggestionDivision
              })
            }
            title={`Apply live OW rank${owSuggestionName ? `: ${owSuggestionName}` : ""} (${owRankValue})`}
            className="flex w-full items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2 py-1.5 text-left transition hover:border-[color:var(--aqt-border-2)] hover:bg-[color:var(--aqt-overlay-3)]"
          >
            <Sparkles className="h-3 w-3 shrink-0 text-amber-300/70" />
            <span className="text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">OW</span>
            {owSuggestionDivision != null ? (
              <DivisionIcon division={owSuggestionDivision} width={16} height={16} />
            ) : null}
            <span className="truncate text-label font-medium text-[color:var(--aqt-fg-muted)]">
              {owSuggestionName ?? `Division ${owSuggestionDivision}`}
            </span>
            <span className="text-label tabular-nums text-[color:var(--aqt-fg-dim)]">({owRankValue})</span>
            <span
              className={cn(
                "ml-auto shrink-0 rounded-md border px-1.5 py-0.5 text-label font-semibold",
                accent.chip
              )}
            >
              {owActionLabel}
            </span>
          </button>
        ) : (
          <div className="flex w-full items-center gap-1.5 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] px-2 py-1.5 text-left">
            <Sparkles className="h-3 w-3 shrink-0 text-[color:var(--aqt-fg-faint)]" />
            <span className="text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">OW</span>
            <span className="text-label text-[color:var(--aqt-fg-dim)]">No live OW rank</span>
          </div>
        )}
      </div>
    </div>
  );
}
