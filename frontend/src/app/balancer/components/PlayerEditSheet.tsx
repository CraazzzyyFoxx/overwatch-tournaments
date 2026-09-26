"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  History,
  Plus,
  Save,
  Sparkles,
  Trash2,
  X
} from "lucide-react";
import { SortableGrip, SortableRows, useSortableRow } from "@/components/kit/SortableRows";

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
import DivisionIcon from "@/components/DivisionIcon";
import StatusMetaBadge from "@/components/status/StatusMetaBadge";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { useCurrentWorkspaceId, useDivisionGrid, useDivisionGridVersion } from "@/hooks/useCurrentWorkspace";
import { useQuery } from "@tanstack/react-query";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import {
  getDivisionLabel,
  resolveDivisionFromRank as resolveDivisionFromRankInGrid,
  resolveRankFromDivision as resolveRankFromDivisionInGrid,
} from "@/lib/divisions/grid";
import { cn } from "@/lib/utils";
import type { DivisionGrid } from "@/types/workspace.types";
import {
  AdminRegistration,
  BalancerPlayerRecord,
  BalancerPlayerRoleEntry,
  BalancerPlayerUpdateInput,
  BalancerRoleCode,
  BalancerRoleSubtype
} from "@/types/balancer-admin.types";
import {
  fetchPlayerRankHistoryPreview,
  type PlayerRankHistoryPreview,
  type PlayerRankHistoryPreviewEntry
} from "@/components/balancer/workspace-helpers";
import { getRegistrationBattleTags } from "@/components/balancer/balancer-page-helpers";
import { BattleTagCopyButton, SmurfTagStrip } from "./BattleTagCopyControls";
import RankHistory from "@/components/RankHistory";
import { Spinner } from "@/components/ui/spinner";
import { ROLE_RANK_ACCENTS, RoleRankControls } from "./RoleRankControls";
import { adminQueryKeys } from "@/lib/admin/query-keys";

const ROLE_OPTIONS: Array<{ value: BalancerRoleCode; label: string }> = [
  { value: "tank", label: "Tank" },
  { value: "damage", label: "Damage" },
  { value: "support", label: "Support" }
];

// Dynamic subtype options are fetched from the workspace sub-roles catalog

const ROLE_DISPLAY: Record<BalancerRoleCode, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support"
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
      is_active: entry.is_active ?? false,
      is_declared_active: entry.is_declared_active ?? true,
      ow_rank_value: entry.ow_rank_value ?? null,
      rank_source: entry.rank_source
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
    const existingEntry = byRole.get(historyEntry.role);
    // Only fill ranks for roles the player already has in the balancer; never add
    // new roles from history — applying history must not change the player's roles.
    if (!existingEntry) {
      continue;
    }

    // Use the normalised division to derive a rank_value in the target grid,
    // so that the form's rank/division fields stay consistent.
    const normalizedRank =
      resolveRankFromDivision(historyEntry.division_number) ?? historyEntry.rank_value;
    byRole.set(historyEntry.role, {
      ...existingEntry,
      rank_value: normalizedRank,
      division_number: historyEntry.division_number,
      // Applying history both enables the role and gives it a rank, so it is
      // declared on AND in play.
      is_active: true,
      is_declared_active: true
    });
  }

  return normalizeRoleEntries(Array.from(byRole.values()));
}

// getSubtypeLabel has been inline-replaced using dynamic subtypeOptions

function resolveRankFromDivisionHelper(
  divisionNumber: number | null,
  grid: DivisionGrid
): number | null {
  return resolveRankFromDivisionInGrid(grid, divisionNumber);
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
  getDivisionName: (divisionNumber: number | null) => string | null;
  onUpdate: (index: number, next: BalancerPlayerRoleEntry) => void;
  onRemove: (index: number) => void;
  subtypeOptions: Record<BalancerRoleCode, Array<{ value: string; label: string }>>;
};

function SortableRoleEntry({
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
}: Readonly<HistoryPreviewCardProps>) {
  const accent = ROLE_RANK_ACCENTS[entry.role];
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
        "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)]",
        accent.row
      )}
    >
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-2">
            <PlayerRoleIcon role={ROLE_DISPLAY[entry.role]} size={18} decorative />
            <span className={cn("text-sm font-semibold", accent.text)}>
              {ROLE_DISPLAY[entry.role]}
            </span>
          </div>
          <Badge className={cn("h-5 border px-2 text-label", accent.chip)}>
            {entry.rank_value} SR
          </Badge>
          {/* Original division (source tournament grid) */}
          {originalDivisionName ? (
            <div className="flex items-center gap-1.5 rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2 py-1 text-[color:var(--aqt-fg)]">
              {entry.original_division_number != null ? (
                <DivisionIcon
                  division={entry.original_division_number}
                  width={16}
                  height={16}
                  tournamentGrid={entry.tournament_grid_version}
                />
              ) : null}
              <span className="text-label font-medium">{originalDivisionName}</span>
            </div>
          ) : null}
          {/* Normalised division (workspace target grid) — only when different */}
          {showNormalisedArrow && divisionName ? (
            <>
              <ArrowRight className="size-4 shrink-0 text-[color:var(--aqt-fg-dim)]" aria-hidden />
              <div className="flex items-center gap-1.5 rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] px-2 py-1 text-[color:var(--aqt-fg)]">
                {entry.division_number != null ? (
                  <DivisionIcon division={entry.division_number} width={16} height={16} />
                ) : null}
                <span className="text-label font-medium">{divisionName}</span>
              </div>
            </>
          ) : null}
        </div>
        <p className="text-xs leading-relaxed text-[color:var(--aqt-fg-muted)]">{changeText}</p>
      </div>
      <div className="space-y-1 text-xs text-[color:var(--aqt-fg-muted)] sm:text-right">
        <div className="flex items-center justify-end gap-1.5">
          <span
            className={cn(
              "rounded border px-1.5 py-0.5 text-label font-semibold uppercase tracking-label",
              entry.source === "balancer"
                ? "border-indigo-400/25 bg-indigo-500/10 text-indigo-200"
                : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg-muted)]"
            )}
          >
            {entry.source === "balancer" ? "Balancer" : "Analytics"}
          </span>
        </div>
        {entry.tournament_name ? (
          <div className="font-medium text-[color:var(--aqt-fg)]">{entry.tournament_name}</div>
        ) : null}
        {entry.source_role ? <div>Source role: {entry.source_role}</div> : null}
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
  onSave: (playerId: number, payload: BalancerPlayerUpdateInput) => void;
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
}: Readonly<PlayerEditModalProps>) {
  const divisionGrid = useDivisionGrid();
  const divisionGridVersion = useDivisionGridVersion();

  const workspaceId = useCurrentWorkspaceId();
  const { data: subRoles } = useQuery({
    queryKey: adminQueryKeys.playerSubRoles(workspaceId),
    queryFn: () => adminService.getPlayerSubRoles({ workspace_id: workspaceId! }),
    enabled: Boolean(workspaceId && open)
  });

  const subtypeOptions = useMemo(() => {
    const options: Record<BalancerRoleCode, Array<{ value: string; label: string }>> = {
      tank: [],
      damage: [],
      support: []
    };

    if (subRoles) {
      for (const sr of subRoles) {
        const roleKey = sr.role as BalancerRoleCode;
        if (options[roleKey]) {
          options[roleKey].push({
            value: sr.slug,
            label: sr.label
          });
        }
      }
    }
    return options;
  }, [subRoles]);
  const resolveDivision = (rankValue: number | null) =>
    resolveDivisionFromRankInGrid(divisionGrid, rankValue);
  const resolveRankFromDivision = (divisionNumber: number | null) =>
    resolveRankFromDivisionHelper(divisionNumber, divisionGrid);
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

  const [roleEntries, setRoleEntries] = useState<BalancerPlayerRoleEntry[]>(
    normalizeRoleEntries(player.role_entries_json)
  );
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
  const [pinToTournament, setPinToTournament] = useState(false);

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
    setIsFlex(player.is_flex);
    setNotes(player.admin_notes ?? "");
    setRegistrationStatus(registration?.status ?? "approved");
    setRegistrationBalancerStatus(registration?.balancer_status ?? "not_in_balancer");
    setHistoryPreview(null);
    setHistoryPreviewRequested(false);
    setHistoryLoadError(null);
    setPinToTournament(false);
    setRoleEntries(applyHistoryToSelectedRoles(normalized, rankHistory, resolveDivision));
  }, [player, registration, rankHistory, divisionGrid]);

  const historyPreviewEntries = historyPreview?.entries ?? [];
  const historyPreviewAverage = historyPreview?.average_rank_value ?? null;
  const hasHistoryPreview = historyPreviewEntries.length > 0;
  const battleTags = getRegistrationBattleTags(registration, player.battle_tag);
  const primaryBattleTag = battleTags[0] ?? player.battle_tag;
  const smurfTags = battleTags.slice(1);

  // `ready`/`incomplete` are computed server-side from role ranks the moment
  // roles are saved (see sync_included_balancer_status) -- nothing here needs
  // to mirror that locally. This only drives the read-only "computed" preview
  // badge below the Roles header.
  const activeRoles = roleEntries.filter((e) => e.is_active);
  const isComputedReady =
    activeRoles.length > 0 &&
    activeRoles.every((e) => e.rank_value !== null && e.rank_value !== undefined && String(e.rank_value).trim() !== "");

  const handleLoadFromHistory = async () => {
    setLoadingHistory(true);
    setHistoryPreviewRequested(true);
    setHistoryLoadError(null);

    try {
      const preview = await fetchPlayerRankHistoryPreview(
        player.battle_tag,
        divisionGridVersion,
        divisionGrid,
        getHistoryWorkspaceIdParam(historyWorkspaceValue),
        workspaceId
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
          getHistoryWorkspaceIdParam(value),
          workspaceId
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
    handleDismissHistoryPreview();
  };

  // Reordering IS the priority: the array position is what the balancer reads,
  // so `priority` is renumbered from the new order rather than edited directly.
  const handleReorderRoles = (next: BalancerPlayerRoleEntry[]) => {
    setRoleEntries(next.map((entry, index) => ({ ...entry, priority: index + 1 })));
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
        // Declared on by the organizer's action, but not in play until it is
        // ranked — which is the server's call, not ours.
        is_active: false,
        is_declared_active: true,
        ow_rank_value: null
      }
    ];
    setRoleEntries(next);
  };

  const updateEntry = (index: number, nextEntry: BalancerPlayerRoleEntry) => {
    const next = normalizeRoleEntries(
      roleEntries.map((entry, currentIndex) => (currentIndex === index ? nextEntry : entry))
    );
    setRoleEntries(next);
  };

  const removeEntry = (index: number) => {
    const next = normalizeRoleEntries(roleEntries.filter((_, currentIndex) => currentIndex !== index));
    setRoleEntries(next);
  };

  const handleSave = () => {
    onSave(player.id, {
      role_entries_json: normalizeRoleEntries(roleEntries),
      is_flex: isFlex,
      admin_notes: notes || null,
      registration_status: registration && registrationStatus !== registration.status ? registrationStatus : null,
      // Only send an explicit override when it actually changed -- the current
      // value may be a server-computed "ready"/"incomplete" the backend
      // rejects as a literal write (see AUTO_MANAGED_BALANCER_STATUSES).
      registration_balancer_status:
        registration && registrationBalancerStatus !== registration.balancer_status
          ? registrationBalancerStatus
          : null,
      ...(pinToTournament ? { pin: true } : {})
    });
  };

  // Saves every pending edit (roles, notes, registration status) exactly like
  // handleSave, then recomputes balancer_status from those roles via
  // add_to_balancer (is_in_pool: true's server-side effect -- see
  // updatePlayerMutation) instead of writing a literal override. That
  // recompute always runs last and wins, so no explicit balancer-status
  // override is sent here -- it would just be overwritten.
  const handleMoveToReady = () => {
    onSave(player.id, {
      role_entries_json: normalizeRoleEntries(roleEntries),
      is_flex: isFlex,
      admin_notes: notes || null,
      registration_status: registration && registrationStatus !== registration.status ? registrationStatus : null,
      is_in_pool: true,
      ...(pinToTournament ? { pin: true } : {})
    });
  };

  const handleClearPin = () => {
    onSave(player.id, {
      role_entries_json: normalizeRoleEntries(roleEntries),
      is_flex: isFlex,
      admin_notes: notes || null,
      registration_status: registration && registrationStatus !== registration.status ? registrationStatus : null,
      registration_balancer_status:
        registration && registrationBalancerStatus !== registration.balancer_status
          ? registrationBalancerStatus
          : null,
      clear_pin: true
    });
  };

  const hasOverride = roleEntries.some((entry) => entry.rank_source === "registration");

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col overflow-hidden border-border bg-popover/95 p-0 text-[color:var(--aqt-fg)] shadow-2xl shadow-black/50 backdrop-blur-xl sm:max-w-[640px] [&>button:last-child]:right-4 [&>button:last-child]:top-4 [&>button:last-child]:z-20 [&>button:last-child]:flex [&>button:last-child]:h-8 [&>button:last-child]:w-8 [&>button:last-child]:items-center [&>button:last-child]:justify-center [&>button:last-child]:rounded-lg [&>button:last-child]:border [&>button:last-child]:border-[color:var(--aqt-border-2)] [&>button:last-child]:bg-[color:var(--aqt-bg-2)] [&>button:last-child]:p-0 [&>button:last-child]:text-[color:var(--aqt-fg-muted)] [&>button:last-child]:backdrop-blur-sm [&>button:last-child]:hover:bg-[color:var(--aqt-overlay-3)] [&>button:last-child]:hover:text-[color:var(--aqt-fg)] [&>button:last-child]:data-[state=open]:bg-[color:var(--aqt-bg-2)] [&>button:last-child]:data-[state=open]:text-[color:var(--aqt-fg-muted)]"
      >
        <SheetHeader
          className={cn(
            "shrink-0 border-b border-[color:var(--aqt-border)] px-4 pb-2.5 pt-3 sm:px-5 sm:pb-3 sm:pt-3.5",
            onRemove ? "pr-20 sm:pr-24" : "pr-14 sm:pr-16"
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <SheetTitle className="text-base font-semibold tracking-tight text-[color:var(--aqt-fg)]">
              {primaryBattleTag}
            </SheetTitle>
            <BattleTagCopyButton battleTag={primaryBattleTag} className="h-6 w-6" />
            {isFlex ? (
              <Badge className="h-5 border-emerald-400/25 bg-emerald-400/10 px-2 text-label text-emerald-200 hover:bg-emerald-400/10">
                Flex
              </Badge>
            ) : null}
          </div>
          <SmurfTagStrip smurfTags={smurfTags} className="mt-1.5" />
          <SheetDescription className="text-xs text-[color:var(--aqt-fg-dim)]">
            Roles, ratings, and balancer participation.
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3 sm:px-5">
          <div className="grid gap-2.5 lg:grid-cols-2">
            <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-3 py-2">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-medium text-[color:var(--aqt-fg)]">Balancer status</span>
                {registration ? (
                  <StatusMetaBadge meta={registration.balancer_status_meta} className="h-5 text-label" />
                ) : (
                  <Badge
                    className={cn(
                      "h-5 px-2 text-label",
                      isComputedReady
                        ? "border-emerald-400/25 bg-emerald-400/10 text-emerald-200"
                        : "border-orange-400/25 bg-orange-400/10 text-orange-200"
                    )}
                  >
                    {isComputedReady ? "Ready" : "Incomplete"}
                  </Badge>
                )}
              </div>
            </div>
            <div
              className={cn(
                "rounded-lg border px-3 py-2",
                isFlex
                  ? "border-emerald-400/20 bg-emerald-500/[0.08]"
                  : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)]"
              )}
            >
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="is-flex" className="cursor-pointer text-xs font-medium text-[color:var(--aqt-fg)]">
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
              <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">Roles</Label>
              <div className="flex flex-nowrap items-center gap-1.5">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 whitespace-nowrap border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2.5 text-label text-[color:var(--aqt-fg)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
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
                  className="h-7 whitespace-nowrap border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2.5 text-label text-[color:var(--aqt-fg)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
                  onClick={handleLoadFromHistory}
                  disabled={loadingHistory}
                >
                  {loadingHistory ? (
                    <Spinner className="mr-1 size-3" />
                  ) : (
                    <History className="mr-1 h-3 w-3" />
                  )}
                  Load from history
                </Button>
              </div>
            </div>

            {historyPreviewRequested ? (
              <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-[color:var(--aqt-fg)]">History preview</span>
                    {historyPreviewAverage != null ? (
                      <Badge className="h-5 border-primary/20 bg-primary/10 px-2 text-label text-[color:var(--aqt-fg)] hover:bg-primary/10">
                        Avg {historyPreviewAverage}
                      </Badge>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2">
                    {hasHistoryPreview ? (
                      <Button
                        type="button"
                        size="sm"
                        className="h-7 bg-primary px-2.5 text-label text-primary-foreground hover:bg-primary/90"
                        onClick={handleApplyHistoryPreview}
                      >
                        Apply history values
                      </Button>
                    ) : null}
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
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
                    <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2.5 py-2 text-xs text-[color:var(--aqt-fg-muted)]">
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

                <div className="mt-3 flex items-center justify-between gap-3 border-t border-[color:var(--aqt-border)] pt-2.5">
                  <Label className="text-label text-[color:var(--aqt-fg-muted)] select-none">
                    Load history from:
                  </Label>
                  <Select
                    value={historyWorkspaceValue}
                    onValueChange={handleHistoryWorkspaceChange}
                  >
                    <SelectTrigger className="h-6 w-[180px] border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-label text-[color:var(--aqt-fg)] px-2">
                      <SelectValue placeholder="Select workspace" />
                    </SelectTrigger>
                    <SelectContent className="border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card)] text-[color:var(--aqt-fg)] text-label">
                      <SelectItem value="current" className="text-label">
                        Current Workspace
                      </SelectItem>
                      <SelectItem value="all" className="text-label">
                        All Workspaces
                      </SelectItem>
                      {workspaces.map((ws) => (
                        <SelectItem key={ws.id} value={String(ws.id)} className="text-label">
                          {ws.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            ) : null}

            <div className="flex items-center justify-between gap-2 rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-3 py-2">
              <Label htmlFor="pin-tournament" className="cursor-pointer text-xs font-medium text-[color:var(--aqt-fg)]">
                Only this tournament
              </Label>
              <div className="flex items-center gap-2">
                {hasOverride ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-6 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2 text-label text-[color:var(--aqt-fg)] hover:bg-[color:var(--aqt-overlay-3)]"
                    disabled={saving}
                    onClick={handleClearPin}
                  >
                    Use workspace rank
                  </Button>
                ) : null}
                <Switch
                  id="pin-tournament"
                  checked={pinToTournament}
                  onCheckedChange={setPinToTournament}
                  aria-label="Only this tournament"
                />
              </div>
            </div>

            <SortableRows
              items={roleEntries}
              getId={(entry, index) => `${entry.role}-${index}`}
              onReorder={handleReorderRoles}
              className="space-y-2"
            >
              {(entry, index) => (
                <SortableRoleEntry
                  key={`${entry.role}-${index}`}
                  id={`${entry.role}-${index}`}
                  entry={entry}
                  index={index}
                  resolveDivision={resolveDivision}
                  getDivisionName={getDivisionName}
                  onUpdate={updateEntry}
                  onRemove={removeEntry}
                  subtypeOptions={subtypeOptions}
                />
              )}
            </SortableRows>
          </div>

          <div className="space-y-2">
            <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">Live rank (OverFast)</Label>
            <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-2.5">
              {player.user_id != null ? (
                <RankHistory userId={player.user_id} />
              ) : (
                <RankHistory battleTag={primaryBattleTag} />
              )}
            </div>
          </div>

          <div className="space-y-1">
            <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">Admin notes</Label>
            <Textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              className="min-h-14 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-2.5 py-1.5 text-xs text-[color:var(--aqt-fg)] placeholder:text-[color:var(--aqt-fg-faint)]"
              placeholder="Notes about availability, role comfort, or balancing caveats."
            />
          </div>
          {registration && statusOptions ? (
            <div className="grid gap-2 md:grid-cols-2">
              <div className="space-y-1">
                <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">Registration status</Label>
                <Select value={registrationStatus} onValueChange={setRegistrationStatus}>
                  <SelectTrigger className="h-8 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-xs text-[color:var(--aqt-fg)]">
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
                <Label className="text-xs font-medium text-[color:var(--aqt-fg)]">Balancer status</Label>
                <Select
                  value={registrationBalancerStatus}
                  onValueChange={setRegistrationBalancerStatus}
                >
                  <SelectTrigger className="h-8 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-xs text-[color:var(--aqt-fg)]">
                    <SelectValue placeholder="Select balancer status" />
                  </SelectTrigger>
                  <SelectContent>
                    {registrationBalancerStatus === "ready" || registrationBalancerStatus === "incomplete" ? (
                      <SelectItem value={registrationBalancerStatus} disabled>
                        {registrationBalancerStatus === "ready" ? "Ready" : "Incomplete"} · Computed
                      </SelectItem>
                    ) : null}
                    {statusOptions.balancer.system
                      .filter((option) => option.value !== "ready" && option.value !== "incomplete")
                      .map((option) => (
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
                <div className="flex items-start justify-between gap-2">
                  <p className="text-label text-[color:var(--aqt-fg-dim)]">
                    Ready/Incomplete are computed from role ranks. Pick Excluded to pull this player from the pool.
                  </p>
                  {registrationBalancerStatus !== "ready" ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-6 shrink-0 gap-1 whitespace-nowrap border-emerald-500/30 bg-emerald-500/10 px-2 text-label text-emerald-200 hover:bg-emerald-500/20 hover:text-emerald-100"
                      disabled={saving}
                      onClick={handleMoveToReady}
                      title="Saves your pending edits, then recomputes this player's balancer status from their current role ranks"
                    >
                      <CheckCircle2 className="h-3 w-3" />
                      Move to ready
                    </Button>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
        </div>

        <SheetFooter className="shrink-0 border-t border-[color:var(--aqt-border)] px-4 py-2.5 sm:justify-between sm:space-x-0 sm:px-5">
          <div className="text-label text-[color:var(--aqt-fg-dim)]">
            Manual edits always win until you explicitly load and apply new history values.
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              className="h-8 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] px-3 text-xs text-[color:var(--aqt-fg)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSave}
              disabled={saving}
              className="h-8 bg-primary px-3 text-xs text-primary-foreground hover:bg-primary/90"
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
