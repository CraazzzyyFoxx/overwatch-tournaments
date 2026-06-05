"use client";

import { useEffect, useMemo, useState } from "react";
import {
  GripVertical,
  History,
  Loader2,
  MoreHorizontal,
  Plus,
  Save,
  Trash2,
  X
} from "lucide-react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle
} from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import Cookies from "js-cookie";
import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { useCurrentWorkspaceId, useDivisionGrid, useDivisionGridVersion } from "@/hooks/useCurrentWorkspace";
import { useQuery } from "@tanstack/react-query";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import {
  getDivisionLabel,
  resolveExactRankFromDivision as resolveExactRankFromDivisionInGrid,
  resolveDivisionFromRank as resolveDivisionFromRankInGrid,
  resolveRankFromDivision as resolveRankFromDivisionInGrid,
  sortTiersAscending,
} from "@/lib/division-grid";
import { cn } from "@/lib/utils";
import type { DivisionGrid } from "@/types/workspace.types";
import {
  AdminRegistration,
  BalancerPlayerRecord,
  BalancerPlayerRoleEntry,
  BalancerRoleCode,
  BalancerRoleSubtype
} from "@/types/balancer-admin.types";
import {
  fetchPlayerRankHistoryPreview,
  type PlayerRankHistoryPreview,
  type PlayerRankHistoryPreviewEntry
} from "@/app/balancer/components/workspace-helpers";
import { getRegistrationBattleTags } from "./balancer-page-helpers";
import { BattleTagCopyButton, SmurfTagStrip } from "./BattleTagCopyControls";
import BattleTagRankHistory from "@/components/BattleTagRankHistory";

const ROLE_OPTIONS: Array<{ value: BalancerRoleCode; label: string }> = [
  { value: "tank", label: "Tank" },
  { value: "dps", label: "Damage" },
  { value: "support", label: "Support" }
];

// Dynamic subtype options are fetched from the workspace sub-roles catalog

const ROLE_DISPLAY: Record<BalancerRoleCode, string> = {
  tank: "Tank",
  dps: "Damage",
  support: "Support"
};

const ROLE_ACCENTS: Record<
  BalancerRoleCode,
  { row: string; text: string; chip: string; line: string; sliderColor: string }
> = {
  tank: {
    row: "border-sky-400/40 bg-sky-500/[0.07] shadow-[0_0_0_1px_rgba(56,189,248,0.08)]",
    text: "text-sky-200",
    chip: "border-sky-300/30 bg-sky-500/12 text-sky-200",
    line: "bg-sky-300",
    sliderColor: "#7dd3fc"
  },
  dps: {
    row: "border-orange-400/40 bg-orange-500/[0.07] shadow-[0_0_0_1px_rgba(251,146,60,0.08)]",
    text: "text-orange-200",
    chip: "border-orange-300/30 bg-orange-500/12 text-orange-200",
    line: "bg-orange-300",
    sliderColor: "#fdba74"
  },
  support: {
    row: "border-emerald-400/40 bg-emerald-500/[0.07] shadow-[0_0_0_1px_rgba(52,211,153,0.08)]",
    text: "text-emerald-200",
    chip: "border-emerald-300/30 bg-emerald-500/12 text-emerald-200",
    line: "bg-emerald-300",
    sliderColor: "#6ee7b7"
  }
};

function normalizeRoleEntries(entries: BalancerPlayerRoleEntry[]): BalancerPlayerRoleEntry[] {
  const seen = new Set<BalancerRoleCode>();
  const sorted = [...entries].sort((a, b) => a.priority - b.priority);
  const normalized: BalancerPlayerRoleEntry[] = [];

  for (const entry of sorted) {
    if (seen.has(entry.role)) continue;
    seen.add(entry.role);
    normalized.push({
      role: entry.role,
      subtype: entry.subtype ?? null,
      priority: normalized.length + 1,
      division_number: entry.division_number ?? null,
      rank_value: entry.rank_value,
      is_active: entry.is_active ?? true
    });
  }

  return normalized;
}

function applyHistoryToSelectedRoles(
  entries: BalancerPlayerRoleEntry[],
  history: Partial<Record<BalancerRoleCode, number>> | null,
  resolveDivision: (rankValue: number | null) => number | null
): BalancerPlayerRoleEntry[] {
  if (!history) {
    return entries;
  }

  return normalizeRoleEntries(
    entries.map((entry) => {
      const rankValue = history[entry.role];
      if (rankValue == null) {
        return entry;
      }

      return {
        ...entry,
        rank_value: rankValue,
        division_number: resolveDivision(rankValue)
      };
    })
  );
}

function applyHistoryPreviewToRoleEntries(
  entries: BalancerPlayerRoleEntry[],
  preview: PlayerRankHistoryPreview | null,
  resolveRankFromDivision: (divisionNumber: number | null) => number | null
): BalancerPlayerRoleEntry[] {
  if (!preview || preview.entries.length === 0) {
    return entries;
  }

  const byRole = new Map(entries.map((entry) => [entry.role, entry]));
  for (const historyEntry of preview.entries) {
    // Use the normalised division to derive a rank_value in the target grid,
    // so that the form's rank/division fields stay consistent.
    const normalizedRank =
      resolveRankFromDivision(historyEntry.division_number) ?? historyEntry.rank_value;
    const existingEntry = byRole.get(historyEntry.role);
    if (existingEntry) {
      byRole.set(historyEntry.role, {
        ...existingEntry,
        rank_value: normalizedRank,
        division_number: historyEntry.division_number,
        is_active: true
      });
      continue;
    }

    byRole.set(historyEntry.role, {
      role: historyEntry.role,
      subtype: null,
      priority: entries.length + byRole.size,
      division_number: historyEntry.division_number,
      rank_value: normalizedRank,
      is_active: true
    });
  }

  return normalizeRoleEntries(Array.from(byRole.values()));
}

// getSubtypeLabel has been inline-replaced using dynamic subtypeOptions

function getAverageRankValue(entries: BalancerPlayerRoleEntry[]): number | null {
  const rankedEntries = entries.filter((entry) => entry.is_active && entry.rank_value != null);
  if (rankedEntries.length === 0) {
    return null;
  }

  const total = rankedEntries.reduce((sum, entry) => sum + (entry.rank_value ?? 0), 0);
  return Math.round(total / rankedEntries.length);
}

function getDivisionGridBounds(grid: DivisionGrid): { min: number; max: number } {
  if (!grid.tiers.length) {
    return { min: 0, max: 5000 };
  }

  const mins = grid.tiers.map((tier) => tier.rank_min);
  const maxes = grid.tiers
    .map((tier) => tier.rank_max)
    .filter((value): value is number => value !== null);

  return {
    min: Math.min(...mins),
    max: Math.max(...maxes, ...mins)
  };
}

function getSliderDivisionTiers(grid: DivisionGrid) {
  return sortTiersAscending(grid);
}

function resolveRankFromDivisionHelper(
  divisionNumber: number | null,
  grid: DivisionGrid
): number | null {
  return resolveRankFromDivisionInGrid(grid, divisionNumber);
}

function resolveExactRankFromDivisionHelper(
  divisionNumber: number | null,
  grid: DivisionGrid
): number | null {
  return resolveExactRankFromDivisionInGrid(grid, divisionNumber);
}

function getDivisionSliderIndex(
  rankValue: number | null,
  divisionTiers: DivisionGrid["tiers"],
  resolveDivision: (rankValue: number | null) => number | null
): number {
  const divisionNumber = resolveDivision(rankValue);
  const index = divisionTiers.findIndex((tier) => tier.number === divisionNumber);
  return index >= 0 ? index : 0;
}

function getRankFillPercentFromDivisionIndex(
  divisionIndex: number,
  totalDivisions: number
): number {
  if (totalDivisions <= 1) {
    return 100;
  }

  return (divisionIndex / (totalDivisions - 1)) * 100;
}

function formatTournamentSource(entry: PlayerRankHistoryPreviewEntry): string {
  return `${entry.tournament_name}`;
}

function buildHistoryChangeText(
  currentEntry: BalancerPlayerRoleEntry | undefined,
  historyEntry: PlayerRankHistoryPreviewEntry
): string {
  if (!currentEntry) {
    return `Will add this role with ${historyEntry.rank_value}.`;
  }

  if (currentEntry.rank_value == null) {
    return `Will set ${historyEntry.rank_value} on the existing role.`;
  }

  if (currentEntry.rank_value === historyEntry.rank_value) {
    return `Matches the current SR (${currentEntry.rank_value}).`;
  }

  return `Current ${currentEntry.rank_value} -> new ${historyEntry.rank_value}.`;
}

type SortableRoleEntryProps = {
  id: string;
  entry: BalancerPlayerRoleEntry;
  index: number;
  resolveDivision: (rankValue: number | null) => number | null;
  resolveExactRankFromDivision: (divisionNumber: number | null) => number | null;
  getDivisionName: (divisionNumber: number | null) => string | null;
  divisionTiers: DivisionGrid["tiers"];
  sliderBounds: { min: number; max: number };
  onUpdate: (index: number, next: BalancerPlayerRoleEntry) => void;
  onRemove: (index: number) => void;
  subtypeOptions: Record<BalancerRoleCode, Array<{ value: string; label: string }>>;
};

function SortableRoleEntry({
  id,
  entry,
  index,
  resolveDivision,
  resolveExactRankFromDivision,
  getDivisionName,
  divisionTiers,
  sliderBounds,
  onUpdate,
  onRemove,
  subtypeOptions
}: SortableRoleEntryProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id
  });

  const style = {
    transform: CSS.Translate.toString(transform),
    transition,
    zIndex: isDragging ? 50 : undefined,
    position: isDragging ? ("relative" as const) : undefined,
    boxShadow: isDragging ? "0 22px 56px rgba(0,0,0,0.34)" : undefined
  };

  const divisionNumber = resolveDivision(entry.rank_value);
  const divisionName = getDivisionName(divisionNumber);
  const accent = ROLE_ACCENTS[entry.role];

  const roleSubtypeOptions = subtypeOptions[entry.role] || [];
  const subtypeLabel = entry.subtype
    ? (roleSubtypeOptions.find((option) => option.value === entry.subtype)?.label ?? entry.subtype)
    : null;
  const hasSubtypeOptions = roleSubtypeOptions.length > 0;
  const divisionSliderIndex = getDivisionSliderIndex(
    entry.rank_value,
    divisionTiers,
    resolveDivision
  );
  const rankFillPercent = getRankFillPercentFromDivisionIndex(
    divisionSliderIndex,
    divisionTiers.length
  );

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "grid gap-2 rounded-xl border p-2.5 transition-colors md:grid-cols-[32px_minmax(0,1fr)]",
        entry.is_active
          ? cn("border-white/10 bg-white/3", accent.row)
          : "border-white/8 bg-white/2 opacity-80"
      )}
    >
      <div className="flex items-center justify-between md:flex-col md:items-center md:justify-center md:gap-1">
        <button
          type="button"
          className="flex h-6 w-6 shrink-0 cursor-grab touch-none items-center justify-center rounded-md border border-white/10 bg-black/15 text-white/45 hover:text-white/80 active:cursor-grabbing"
          {...attributes}
          {...listeners}
        >
          <GripVertical className="h-3 w-3" />
        </button>
        <span className="text-[10px] font-semibold text-white/30">#{index + 1}</span>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <PlayerRoleIcon role={ROLE_DISPLAY[entry.role]} size={15} />
            <span
              className={cn(
                "text-xs font-semibold",
                entry.is_active ? accent.text : "text-white/70"
              )}
            >
              {ROLE_DISPLAY[entry.role]}
            </span>
            {subtypeLabel ? (
              <Badge className={cn("h-4 border px-1.5 text-[9px]", accent.chip)}>
                {subtypeLabel}
              </Badge>
            ) : null}
          </div>

          <div className="flex items-center gap-1.5">
            <div className="flex h-6 items-center gap-1.5 rounded-md border border-white/10 bg-black/15 px-2">
              <Switch
                checked={entry.is_active}
                className="h-4 w-7 [&>span]:h-3 [&>span]:w-3 data-[state=checked]:[&>span]:translate-x-3"
                onCheckedChange={(checked) => onUpdate(index, { ...entry, is_active: checked })}
                aria-label={entry.is_active ? "Disable role" : "Enable role"}
              />
              <span
                className={cn(
                  "text-[10px] font-semibold uppercase tracking-wide",
                  entry.is_active ? accent.text : "text-white/45"
                )}
              >
                {entry.is_active ? "Active" : "Off"}
              </span>
            </div>

            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 shrink-0 rounded-md border border-white/10 bg-black/15 text-white/45 hover:bg-white/5 hover:text-white"
              onClick={() => onRemove(index)}
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        </div>

        <div className="grid gap-2 lg:grid-cols-[minmax(0,140px)_minmax(0,1fr)_130px]">
          <div className="space-y-1">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-white/35">
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
                  "h-7 w-full border-white/12 bg-black/15 px-2 text-xs text-white",
                  !entry.is_active && "text-white/45"
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

          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-white/35">
                Skill rating
              </span>
              {entry.rank_value != null ? (
                <span
                  className={cn(
                    "text-[10px] font-semibold",
                    entry.is_active ? accent.text : "text-white/45"
                  )}
                >
                  {entry.rank_value}
                </span>
              ) : null}
            </div>
            <Input
              type="number"
              min={sliderBounds.min}
              max={sliderBounds.max}
              className={cn(
                "h-7 border-white/12 bg-black/15 px-2 text-xs text-white shadow-none focus-visible:ring-1 focus-visible:ring-violet-400/40",
                !entry.is_active && "text-white/45"
              )}
              value={entry.rank_value ?? ""}
              onChange={(event) => {
                const rankValue = event.target.value ? Number(event.target.value) : null;
                onUpdate(index, {
                  ...entry,
                  rank_value: rankValue,
                  division_number: resolveDivision(rankValue)
                });
              }}
            />
            <input
              type="range"
              min={0}
              max={Math.max(divisionTiers.length - 1, 0)}
              step={1}
              disabled={!entry.is_active}
              value={divisionSliderIndex}
              onChange={(event) => {
                const nextIndex = Number(event.target.value);
                const nextDivision = divisionTiers[nextIndex]?.number ?? null;
                const rankValue = resolveExactRankFromDivision(nextDivision);
                onUpdate(index, {
                  ...entry,
                  rank_value: rankValue,
                  division_number: nextDivision
                });
              }}
              className={cn(
                "h-1 w-full cursor-pointer appearance-none rounded-full bg-white/8",
                !entry.is_active && "cursor-not-allowed opacity-50"
              )}
              style={{
                accentColor: accent.sliderColor,
                background: `linear-gradient(90deg, ${accent.sliderColor} 0%, ${accent.sliderColor} ${rankFillPercent}%, rgba(255,255,255,0.08) ${rankFillPercent}%, rgba(255,255,255,0.08) 100%)`
              }}
            />
          </div>

          <div className="space-y-1">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-white/35">
              Rank
            </span>
            <div
              className={cn(
                "flex min-h-[36px] items-center gap-1.5 rounded-md border border-white/10 bg-black/15 px-2 py-1",
                !entry.is_active && "text-white/45"
              )}
              title={divisionName ?? undefined}
            >
              {divisionNumber != null ? (
                <>
                  <PlayerDivisionIcon division={divisionNumber} width={20} height={20} />
                  <div className="min-w-0">
                    <div className="truncate text-[12px] font-medium text-white/75">
                      {divisionName ?? `Division ${divisionNumber}`}
                    </div>
                  </div>
                </>
              ) : (
                <span className="text-[10px] text-white/40">No rank yet</span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

type HistoryPreviewCardProps = {
  entry: PlayerRankHistoryPreviewEntry;
  currentEntry: BalancerPlayerRoleEntry | undefined;
  getDivisionName: (divisionNumber: number | null) => string | null;
  getOriginalDivisionName: (
    divisionNumber: number | null,
    entry: PlayerRankHistoryPreviewEntry
  ) => string | null;
};

function HistoryPreviewCard({
  entry,
  currentEntry,
  getDivisionName,
  getOriginalDivisionName
}: HistoryPreviewCardProps) {
  const accent = ROLE_ACCENTS[entry.role];
  // Normalised name (target/workspace grid)
  const divisionName =
    getDivisionName(entry.division_number) ??
    (entry.division_number != null ? `Division ${entry.division_number}` : null);
  // Original name (source tournament grid)
  const originalDivisionName =
    getOriginalDivisionName(entry.original_division_number, entry) ??
    (entry.original_division_number != null ? `Division ${entry.original_division_number}` : null);
  // Show the arrow only when the two differ (cross-version normalisation changed the number)
  const showNormalisedArrow =
    entry.original_division_number !== entry.division_number && entry.division_number != null;
  const changeText = buildHistoryChangeText(currentEntry, entry);

  return (
    <div
      className={cn(
        "grid gap-2.5 rounded-xl border p-3 sm:grid-cols-[minmax(0,1fr)_auto]",
        "border-white/10 bg-white/[0.03]",
        accent.row
      )}
    >
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-2">
            <PlayerRoleIcon role={ROLE_DISPLAY[entry.role]} size={18} />
            <span className={cn("text-sm font-semibold", accent.text)}>
              {ROLE_DISPLAY[entry.role]}
            </span>
          </div>
          <Badge className={cn("h-5 border px-2 text-[10px]", accent.chip)}>
            {entry.rank_value} SR
          </Badge>
          {/* Original division (source tournament grid) */}
          {originalDivisionName ? (
            <div className="flex items-center gap-1.5 rounded-full border border-white/12 bg-black/15 px-2 py-1 text-white/80">
              {entry.original_division_number != null ? (
                <PlayerDivisionIcon
                  division={entry.original_division_number}
                  width={16}
                  height={16}
                  tournamentGrid={entry.tournament_grid_version}
                />
              ) : null}
              <span className="text-[11px] font-medium">{originalDivisionName}</span>
            </div>
          ) : null}
          {/* Normalised division (workspace target grid) — only when different */}
          {showNormalisedArrow && divisionName ? (
            <>
              <span className="text-[11px] text-white/40">→</span>
              <div className="flex items-center gap-1.5 rounded-full border border-white/20 bg-white/5 px-2 py-1 text-white/90">
                {entry.division_number != null ? (
                  <PlayerDivisionIcon division={entry.division_number} width={16} height={16} />
                ) : null}
                <span className="text-[11px] font-medium">{divisionName}</span>
              </div>
            </>
          ) : null}
        </div>
        <p className="text-xs leading-relaxed text-white/65">{changeText}</p>
      </div>
      <div className="space-y-1 text-xs text-white/55 sm:text-right">
        <div className="font-medium text-white/80">{`${entry.tournament_name}`}</div>
        <div>Source role: {entry.source_role}</div>
      </div>
    </div>
  );
}

const MULTIPLE_WORKSPACES_COOKIE = "aqt-history-multiple-workspaces";

type PlayerEditModalProps = {
  player: BalancerPlayerRecord;
  registration?: AdminRegistration | null;
  statusOptions?: {
    registration: {
      system: Array<{ value: string; name: string }>;
      custom: Array<{ value: string; name: string }>;
    };
    balancer: {
      system: Array<{ value: string; name: string }>;
      custom: Array<{ value: string; name: string }>;
    };
  };
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (
    playerId: number,
    payload: {
      role_entries_json: BalancerPlayerRoleEntry[];
      is_in_pool?: boolean;
      is_flex: boolean;
      admin_notes: string | null;
      registration_status?: string | null;
      registration_balancer_status?: string | null;
    }
  ) => void;
  onRemove?: (playerId: number) => void;
  saving?: boolean;
  rankHistory?: Partial<Record<BalancerRoleCode, number>> | null;
};

export function PlayerEditModal({
  player,
  registration = null,
  statusOptions,
  open,
  onOpenChange,
  onSave,
  onRemove,
  saving = false,
  rankHistory = null
}: PlayerEditModalProps) {
  const divisionGrid = useDivisionGrid();
  const divisionGridVersion = useDivisionGridVersion();

  const workspaceId = useCurrentWorkspaceId();
  const { data: subRoles } = useQuery({
    queryKey: ["admin", "player-sub-roles", workspaceId],
    queryFn: () => adminService.getPlayerSubRoles({ workspace_id: workspaceId! }),
    enabled: Boolean(workspaceId && open)
  });

  const subtypeOptions = useMemo(() => {
    const options: Record<BalancerRoleCode, Array<{ value: string; label: string }>> = {
      tank: [],
      dps: [],
      support: []
    };

    if (subRoles) {
      for (const sr of subRoles) {
        const roleKey = sr.role === "damage" ? "dps" : (sr.role as BalancerRoleCode);
        if (options[roleKey]) {
          options[roleKey].push({
            value: sr.slug,
            label: sr.label
          });
        }
      }
    } else {
      // Fallback defaults
      options.dps = [
        { value: "hitscan", label: "Hitscan" },
        { value: "projectile", label: "Projectile" }
      ];
      options.support = [
        { value: "main_heal", label: "Main Heal" },
        { value: "light_heal", label: "Light Heal" }
      ];
    }
    return options;
  }, [subRoles]);
  const resolveDivision = (rankValue: number | null) =>
    resolveDivisionFromRankInGrid(divisionGrid, rankValue);
  const resolveRankFromDivision = (divisionNumber: number | null) =>
    resolveRankFromDivisionHelper(divisionNumber, divisionGrid);
  const resolveExactRankFromDivision = (divisionNumber: number | null) =>
    resolveExactRankFromDivisionHelper(divisionNumber, divisionGrid);
  const getDivisionName = (divisionNumber: number | null) =>
    getDivisionLabel(divisionGrid, divisionNumber);

  // Normalised division name: always look up in the workspace (target) grid.
  const getHistoryDivisionName = (divisionNumber: number | null) => {
    return getDivisionLabel(divisionGrid, divisionNumber);
  };

  // Original division name: look up in the source tournament's own grid first,
  // then fall back to the workspace grid.
  const getOriginalDivisionName = (
    divisionNumber: number | null,
    entry: PlayerRankHistoryPreviewEntry
  ) => {
    if (divisionNumber == null) return null;
    if (entry.tournament_grid_version) {
      const tierName = getDivisionLabel(entry.tournament_grid_version, divisionNumber);
      if (tierName) return tierName;
    }
    return getDivisionLabel(divisionGrid, divisionNumber);
  };
  const sliderBounds = useMemo(() => getDivisionGridBounds(divisionGrid), [divisionGrid]);
  const divisionTiers = useMemo(() => getSliderDivisionTiers(divisionGrid), [divisionGrid]);

  const [roleEntries, setRoleEntries] = useState<BalancerPlayerRoleEntry[]>(
    normalizeRoleEntries(player.role_entries_json)
  );
  const [isInPool, setIsInPool] = useState(player.is_in_pool);
  const [isFlex, setIsFlex] = useState(player.is_flex);
  const [notes, setNotes] = useState(player.admin_notes ?? "");
  const [registrationStatus, setRegistrationStatus] = useState(registration?.status ?? "approved");
  const [registrationBalancerStatus, setRegistrationBalancerStatus] = useState(
    registration?.balancer_status ?? "not_in_balancer"
  );
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [historyPreview, setHistoryPreview] = useState<PlayerRankHistoryPreview | null>(null);
  const [historyPreviewRequested, setHistoryPreviewRequested] = useState(false);
  const [historyLoadError, setHistoryLoadError] = useState<string | null>(null);

  const { workspaces } = useWorkspaceStore();
  const [historyWorkspaceValue, setHistoryWorkspaceValue] = useState<string>(() => {
    const saved = Cookies.get(MULTIPLE_WORKSPACES_COOKIE);
    return saved || "current";
  });

  const getHistoryWorkspaceIdParam = (val: string) => {
    if (val === "all") return null;
    if (val === "current") return undefined;
    return Number(val);
  };

  useEffect(() => {
    const normalized = normalizeRoleEntries(player.role_entries_json);
    setIsInPool(player.is_in_pool);
    setIsFlex(player.is_flex);
    setNotes(player.admin_notes ?? "");
    setRegistrationStatus(registration?.status ?? "approved");
    setRegistrationBalancerStatus(registration?.balancer_status ?? "not_in_balancer");
    setHistoryPreview(null);
    setHistoryPreviewRequested(false);
    setHistoryLoadError(null);
    setRoleEntries(applyHistoryToSelectedRoles(normalized, rankHistory, resolveDivision));
  }, [player, registration, rankHistory, divisionGrid]);

  const averageRankValue = useMemo(() => getAverageRankValue(roleEntries), [roleEntries]);
  const historyPreviewEntries = historyPreview?.entries ?? [];
  const historyPreviewAverage = historyPreview?.average_rank_value ?? null;
  const hasHistoryPreview = historyPreviewEntries.length > 0;
  const battleTags = getRegistrationBattleTags(registration, player.battle_tag);
  const primaryBattleTag = battleTags[0] ?? player.battle_tag;
  const smurfTags = battleTags.slice(1);

  const checkRanksAndAutoUpdateStatus = (nextEntries: BalancerPlayerRoleEntry[]) => {
    const activeRoles = nextEntries.filter((e) => e.is_active);
    const allRanked =
      activeRoles.length > 0 &&
      activeRoles.every((e) => e.rank_value !== null && e.rank_value !== undefined && String(e.rank_value).trim() !== "");

    if (allRanked) {
      setRegistrationBalancerStatus((current) => {
        if (current === "not_in_balancer" || current === "incomplete") {
          setIsInPool(true);
          return "ready";
        }
        return current;
      });
    } else {
      setRegistrationBalancerStatus((current) => {
        if (current === "ready") {
          setIsInPool(false);
          return "incomplete";
        }
        return current;
      });
    }
  };

  const handleLoadFromHistory = async () => {
    setLoadingHistory(true);
    setHistoryPreviewRequested(true);
    setHistoryLoadError(null);

    try {
      const preview = await fetchPlayerRankHistoryPreview(
        player.battle_tag,
        divisionGridVersion,
        divisionGrid,
        getHistoryWorkspaceIdParam(historyWorkspaceValue)
      );
      setHistoryPreview(preview);
    } catch (error) {
      setHistoryPreview(null);
      setHistoryLoadError(
        error instanceof Error ? error.message : "Failed to load player history."
      );
    } finally {
      setLoadingHistory(false);
    }
  };

  const handleHistoryWorkspaceChange = async (value: string) => {
    setHistoryWorkspaceValue(value);
    Cookies.set(MULTIPLE_WORKSPACES_COOKIE, value, { path: "/", sameSite: "lax" });

    if (historyPreviewRequested) {
      setLoadingHistory(true);
      setHistoryLoadError(null);
      try {
        const preview = await fetchPlayerRankHistoryPreview(
          player.battle_tag,
          divisionGridVersion,
          divisionGrid,
          getHistoryWorkspaceIdParam(value)
        );
        setHistoryPreview(preview);
      } catch (error) {
        setHistoryPreview(null);
        setHistoryLoadError(
          error instanceof Error ? error.message : "Failed to load player history."
        );
      } finally {
        setLoadingHistory(false);
      }
    }
  };

  const handleDismissHistoryPreview = () => {
    setHistoryPreviewRequested(false);
    setHistoryPreview(null);
    setHistoryLoadError(null);
  };

  const handleApplyHistoryPreview = () => {
    const next = applyHistoryPreviewToRoleEntries(roleEntries, historyPreview, resolveRankFromDivision);
    setRoleEntries(next);
    checkRanksAndAutoUpdateStatus(next);
    handleDismissHistoryPreview();
  };

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates
    })
  );

  const sortableIds = roleEntries.map((entry, index) => `${entry.role}-${index}`);

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIndex = sortableIds.indexOf(active.id as string);
    const newIndex = sortableIds.indexOf(over.id as string);
    if (oldIndex === -1 || newIndex === -1) return;

    setRoleEntries((current) => {
      const moved = arrayMove(current, oldIndex, newIndex);
      return moved.map((entry, i) => ({ ...entry, priority: i + 1 }));
    });
  };

  const addRole = () => {
    const availableRole = ROLE_OPTIONS.find(
      (option) => !roleEntries.some((entry) => entry.role === option.value)
    );
    if (!availableRole) return;

    const next = [
      ...roleEntries,
      {
        role: availableRole.value,
        subtype: null,
        priority: roleEntries.length + 1,
        division_number: null,
        rank_value: null,
        is_active: true
      }
    ];
    setRoleEntries(next);
    checkRanksAndAutoUpdateStatus(next);
  };

  const updateEntry = (index: number, nextEntry: BalancerPlayerRoleEntry) => {
    const next = normalizeRoleEntries(
      roleEntries.map((entry, currentIndex) => (currentIndex === index ? nextEntry : entry))
    );
    setRoleEntries(next);
    checkRanksAndAutoUpdateStatus(next);
  };

  const removeEntry = (index: number) => {
    const next = normalizeRoleEntries(roleEntries.filter((_, currentIndex) => currentIndex !== index));
    setRoleEntries(next);
    checkRanksAndAutoUpdateStatus(next);
  };

  const handleSave = () => {
    onSave(player.id, {
      role_entries_json: normalizeRoleEntries(roleEntries),
      is_in_pool: isInPool === player.is_in_pool ? undefined : isInPool,
      is_flex: isFlex,
      admin_notes: notes || null,
      registration_status: registration ? registrationStatus : null,
      registration_balancer_status: registration ? registrationBalancerStatus : null
    });
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col overflow-hidden border-white/10 bg-[#12111d]/95 p-0 text-white shadow-2xl shadow-black/50 backdrop-blur-xl sm:max-w-[640px] [&>button:last-child]:right-4 [&>button:last-child]:top-4 [&>button:last-child]:z-20 [&>button:last-child]:flex [&>button:last-child]:h-8 [&>button:last-child]:w-8 [&>button:last-child]:items-center [&>button:last-child]:justify-center [&>button:last-child]:rounded-lg [&>button:last-child]:border [&>button:last-child]:border-white/10 [&>button:last-child]:bg-black/30 [&>button:last-child]:p-0 [&>button:last-child]:text-white/60 [&>button:last-child]:backdrop-blur-sm [&>button:last-child]:hover:bg-white/8 [&>button:last-child]:hover:text-white [&>button:last-child]:data-[state=open]:bg-black/30 [&>button:last-child]:data-[state=open]:text-white/60"
      >
        <SheetHeader
          className={cn(
            "shrink-0 border-b border-white/8 px-4 pb-2.5 pt-3 sm:px-5 sm:pb-3 sm:pt-3.5",
            onRemove ? "pr-20 sm:pr-24" : "pr-14 sm:pr-16"
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <SheetTitle className="text-base font-semibold tracking-tight text-white">
              {primaryBattleTag}
            </SheetTitle>
            <BattleTagCopyButton battleTag={primaryBattleTag} className="h-6 w-6" />
            {isFlex ? (
              <Badge className="h-5 border-emerald-400/25 bg-emerald-400/10 px-2 text-[10px] text-emerald-200 hover:bg-emerald-400/10">
                Flex
              </Badge>
            ) : null}
          </div>
          <SmurfTagStrip smurfTags={smurfTags} className="mt-1.5" />
          <SheetDescription className="text-xs text-white/45">
            Roles, ratings, and balancer participation.
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3 sm:px-5">
          <div className="grid gap-2.5 lg:grid-cols-2">
            <div
              className={cn(
                "rounded-lg border px-3 py-2",
                isInPool
                  ? "border-violet-400/20 bg-violet-500/[0.08]"
                  : "border-white/10 bg-white/[0.03]"
              )}
            >
              <div className="flex items-center justify-between gap-3">
                <Label
                  htmlFor="is-in-pool"
                  className="cursor-pointer text-xs font-medium text-white"
                >
                  Include in balancer
                </Label>
                <Switch
                  id="is-in-pool"
                  checked={isInPool}
                  onCheckedChange={setIsInPool}
                  aria-label="Include in balancer"
                />
              </div>
            </div>

            <div
              className={cn(
                "rounded-lg border px-3 py-2",
                isFlex
                  ? "border-emerald-400/20 bg-emerald-500/[0.08]"
                  : "border-white/10 bg-white/[0.03]"
              )}
            >
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="is-flex" className="cursor-pointer text-xs font-medium text-white">
                  Flex player
                </Label>
                <Switch
                  id="is-flex"
                  checked={isFlex}
                  onCheckedChange={setIsFlex}
                  aria-label="Flex player"
                />
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Label className="text-xs font-medium text-white">Roles</Label>
              <div className="flex flex-nowrap items-center gap-1.5">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 whitespace-nowrap border-white/12 bg-black/20 px-2.5 text-[11px] text-white/85 hover:bg-white/5 hover:text-white"
                  onClick={addRole}
                  disabled={roleEntries.length >= ROLE_OPTIONS.length}
                >
                  <Plus className="mr-1 h-3 w-3" />
                  Add role
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 whitespace-nowrap border-white/12 bg-black/20 px-2.5 text-[11px] text-white/85 hover:bg-white/5 hover:text-white"
                  onClick={handleLoadFromHistory}
                  disabled={loadingHistory}
                >
                  {loadingHistory ? (
                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  ) : (
                    <History className="mr-1 h-3 w-3" />
                  )}
                  Load from history
                </Button>
              </div>
            </div>

            {historyPreviewRequested ? (
              <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-white">History preview</span>
                    {historyPreviewAverage != null ? (
                      <Badge className="h-5 border-violet-400/20 bg-violet-400/10 px-2 text-[10px] text-violet-200 hover:bg-violet-400/10">
                        Avg {historyPreviewAverage}
                      </Badge>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2">
                    {hasHistoryPreview ? (
                      <Button
                        type="button"
                        size="sm"
                        className="h-7 bg-violet-500/90 px-2.5 text-[11px] text-white hover:bg-violet-400"
                        onClick={handleApplyHistoryPreview}
                      >
                        Apply history values
                      </Button>
                    ) : null}
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 rounded-lg border border-white/10 bg-black/15 text-white/55 hover:bg-white/5 hover:text-white"
                      onClick={handleDismissHistoryPreview}
                      aria-label="Close history preview"
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>

                <div className="mt-2 space-y-1.5">
                  {historyLoadError ? (
                    <div className="rounded-lg border border-rose-400/20 bg-rose-500/[0.08] px-2.5 py-2 text-xs text-rose-100">
                      {historyLoadError}
                    </div>
                  ) : null}

                  {!historyLoadError && !loadingHistory && !hasHistoryPreview ? (
                    <div className="rounded-lg border border-white/10 bg-black/15 px-2.5 py-2 text-xs text-white/55">
                      No ranked tournament history was found for this BattleTag.
                    </div>
                  ) : null}

                  {historyPreviewEntries.map((entry) => (
                    <HistoryPreviewCard
                      key={`${entry.role}-${entry.tournament_id}`}
                      entry={entry}
                      currentEntry={roleEntries.find((roleEntry) => roleEntry.role === entry.role)}
                      getDivisionName={getHistoryDivisionName}
                      getOriginalDivisionName={getOriginalDivisionName}
                    />
                  ))}
                </div>

                <div className="mt-3 flex items-center justify-between gap-3 border-t border-white/8 pt-2.5">
                  <Label className="text-[11px] text-white/50 select-none">
                    Load history from:
                  </Label>
                  <Select
                    value={historyWorkspaceValue}
                    onValueChange={handleHistoryWorkspaceChange}
                  >
                    <SelectTrigger className="h-6 w-[180px] border-white/10 bg-black/20 text-[10px] text-white px-2">
                      <SelectValue placeholder="Select workspace" />
                    </SelectTrigger>
                    <SelectContent className="border-white/10 bg-zinc-950 text-white text-[11px]">
                      <SelectItem value="current" className="text-[11px]">
                        Current Workspace (Текущий)
                      </SelectItem>
                      <SelectItem value="all" className="text-[11px]">
                        All Workspaces (Все)
                      </SelectItem>
                      {workspaces.map((ws) => (
                        <SelectItem key={ws.id} value={String(ws.id)} className="text-[11px]">
                          {ws.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            ) : null}

            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <SortableContext items={sortableIds} strategy={verticalListSortingStrategy}>
                <div className="space-y-2">
                  {roleEntries.map((entry, index) => (
                    <SortableRoleEntry
                      key={sortableIds[index]}
                      id={sortableIds[index]}
                      entry={entry}
                      index={index}
                      resolveDivision={resolveDivision}
                      resolveExactRankFromDivision={resolveExactRankFromDivision}
                      getDivisionName={getDivisionName}
                      divisionTiers={divisionTiers}
                      sliderBounds={sliderBounds}
                      onUpdate={updateEntry}
                      onRemove={removeEntry}
                      subtypeOptions={subtypeOptions}
                    />
                  ))}
                </div>
              </SortableContext>
            </DndContext>
          </div>

          <div className="space-y-2">
            <Label className="text-xs font-medium text-white">Live rank (OverFast)</Label>
            <div className="rounded-lg border border-white/10 bg-white/[0.03] p-2.5">
              <BattleTagRankHistory userId={player.user_id} battleTag={primaryBattleTag} />
            </div>
          </div>

          <div className="space-y-1">
            <Label className="text-xs font-medium text-white">Admin notes</Label>
            <Textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              className="min-h-14 border-white/10 bg-black/20 px-2.5 py-1.5 text-xs text-white placeholder:text-white/25"
              placeholder="Notes about availability, role comfort, or balancing caveats."
            />
          </div>
          {registration && statusOptions ? (
            <div className="grid gap-2 md:grid-cols-2">
              <div className="space-y-1">
                <Label className="text-xs font-medium text-white">Registration status</Label>
                <Select value={registrationStatus} onValueChange={setRegistrationStatus}>
                  <SelectTrigger className="h-8 border-white/10 bg-black/20 text-xs text-white">
                    <SelectValue placeholder="Select registration status" />
                  </SelectTrigger>
                  <SelectContent>
                    {statusOptions.registration.system.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.name} · System
                      </SelectItem>
                    ))}
                    {statusOptions.registration.custom.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.name} · Custom
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs font-medium text-white">Balancer status</Label>
                <Select
                  value={registrationBalancerStatus}
                  onValueChange={setRegistrationBalancerStatus}
                >
                  <SelectTrigger className="h-8 border-white/10 bg-black/20 text-xs text-white">
                    <SelectValue placeholder="Select balancer status" />
                  </SelectTrigger>
                  <SelectContent>
                    {statusOptions.balancer.system.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.name} · System
                      </SelectItem>
                    ))}
                    {statusOptions.balancer.custom.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.name} · Custom
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          ) : null}
        </div>

        <SheetFooter className="shrink-0 border-t border-white/8 px-4 py-2.5 sm:justify-between sm:space-x-0 sm:px-5">
          <div className="text-[11px] text-white/30">
            Manual edits always win until you explicitly load and apply new history values.
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              className="h-8 border-white/12 bg-black/20 px-3 text-xs text-white/80 hover:bg-white/5 hover:text-white"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSave}
              disabled={saving}
              className="h-8 bg-violet-500 px-3 text-xs text-white hover:bg-violet-400"
            >
              <Save className="mr-1 h-3.5 w-3.5" />
              Save
            </Button>
          </div>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
