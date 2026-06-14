"use client";

import { forwardRef, useImperativeHandle, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  Columns3,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  PlusCircle,
  Settings2,
  ShieldX,
  Tag,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { AdminRegistration, BalancerApplication, StatusMeta, WorkspaceBalancerConfig } from "@/types/balancer-admin.types";
import type { PlayerValidationState, PoolView, PoolSortValue } from "./balancer-page-helpers";
import { PANEL_CLASS, hasBlockingIssues, sortPlayerStates } from "./balancer-page-helpers";
import { buildPlayerSearchIndex } from "./workspace-helpers";
import { PoolSearchCombobox } from "./PoolSearchCombobox";
import { PoolPlayerCompactList } from "./PoolPlayerCompactList";
import { PoolTriageBoard } from "./PoolTriageBoard";
import { WorkspaceBalancerConfigDialog } from "./WorkspaceBalancerConfigDialog";

export type BalancingPoolSidebarHandle = {
  focusNeedsFixView: () => void;
  focusBrowseAvailable: () => void;
};

type PoolFilterOption = { value: PoolView; label: string; count: number };
type StatusOptionGroups = { system: StatusMeta[]; custom: StatusMeta[] };

type BalancingPoolSidebarProps = {
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  allPlayerValidationStates: PlayerValidationState[];
  applications: BalancerApplication[];
  addableApplications: BalancerApplication[];
  registrationsById?: Map<number, AdminRegistration>;
  balancerStatusOptions?: StatusOptionGroups;
  selectedPlayerId: number | null;
  onSelectPlayer: (playerId: number | null) => void;
  onAddFromApplication: (application: BalancerApplication) => void;
  onSetPoolMembership?: (playerId: number, isInPool: boolean) => unknown;
  onSetBalancerStatus?: (playerId: number, balancerStatus: string) => unknown;
  onBulkPoolMembership?: (playerIds: number[], isInPool: boolean) => unknown;
  onBulkBalancerStatus?: (playerIds: number[], balancerStatus: string) => unknown;
  isAddingPlayer: boolean;
  actionsDisabled?: boolean;
  missingRankCount?: number;
  workspaceId?: number;
  workspaceBalancerConfig?: WorkspaceBalancerConfig | null;
};

function flattenStatusOptions(statusOptions?: StatusOptionGroups): StatusMeta[] {
  return statusOptions ? [...statusOptions.system, ...statusOptions.custom] : [];
}

function BulkStatusMenu({
  statusOptions,
  disabled,
  onChange,
}: {
  statusOptions?: StatusOptionGroups;
  disabled?: boolean;
  onChange: (status: string) => void;
}) {
  if (!statusOptions) {
    return null;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          className="h-7 rounded-lg border-white/10 bg-black/15 px-2 text-[11px] text-white/70 hover:bg-white/5 hover:text-white"
        >
          <Tag className="mr-1 h-3 w-3" />
          Status
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>Set balancer status</DropdownMenuLabel>
        {statusOptions.system.map((option) => (
          <DropdownMenuItem key={option.value} onClick={() => onChange(option.value)}>
            {option.name}
          </DropdownMenuItem>
        ))}
        {statusOptions.custom.length > 0 ? <DropdownMenuSeparator /> : null}
        {statusOptions.custom.map((option) => (
          <DropdownMenuItem key={option.value} onClick={() => onChange(option.value)}>
            {option.name}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export const BalancingPoolSidebar = forwardRef<BalancingPoolSidebarHandle, BalancingPoolSidebarProps>(
  function BalancingPoolSidebar(
    {
      collapsed = false,
      onToggleCollapsed,
      allPlayerValidationStates,
      applications,
      addableApplications,
      registrationsById,
      balancerStatusOptions,
      selectedPlayerId,
      onSelectPlayer,
      onAddFromApplication,
      onSetPoolMembership,
      onSetBalancerStatus,
      onBulkPoolMembership,
      onBulkBalancerStatus,
      isAddingPlayer,
      actionsDisabled = false,
      missingRankCount = 0,
      workspaceId,
      workspaceBalancerConfig,
    },
    ref,
  ) {
    const [poolView, setPoolView] = useState<PoolView>("all");
    const [configDialogOpen, setConfigDialogOpen] = useState(false);
    const [poolSort, setPoolSort] = useState<PoolSortValue>("added_asc");
    const [sidebarSearchQuery, setSidebarSearchQuery] = useState("");
    const [sidebarSearchMode, setSidebarSearchMode] = useState<"default" | "applications">("default");
    const [showSidebarFilters, setShowSidebarFilters] = useState(false);
    const [isTriageBoardOpen, setIsTriageBoardOpen] = useState(false);
    const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set());

    useImperativeHandle(ref, () => ({
      focusNeedsFixView: () => {
        setPoolView("needs_fix");
        setSidebarSearchMode("default");
      },
      focusBrowseAvailable: () => {
        setPoolView("all");
        setSidebarSearchQuery("");
        setSidebarSearchMode("applications");
      },
    }));

    const applicationsById = useMemo(
      () => new Map(applications.map((a) => [a.id, a])),
      [applications],
    );

    const poolPlayers = useMemo(
      () => allPlayerValidationStates.filter((s) => s.player.is_in_pool),
      [allPlayerValidationStates],
    );
    const excludedPlayers = useMemo(
      () => allPlayerValidationStates.filter((s) => !s.player.is_in_pool),
      [allPlayerValidationStates],
    );
    const readyPlayers = useMemo(
      () => poolPlayers.filter((s) => !hasBlockingIssues(s.issues)),
      [poolPlayers],
    );
    const invalidPlayers = useMemo(
      () => poolPlayers.filter((s) => hasBlockingIssues(s.issues)),
      [poolPlayers],
    );
    const rankDeltaPlayers = useMemo(
      () => poolPlayers.filter((s) => s.issues.some((i) => i.code === "rank_delta_warning")),
      [poolPlayers],
    );

    const normalizedSearchQuery = sidebarSearchQuery.trim().toLowerCase();

    const filteredPoolPlayerStates = useMemo(() => {
      const hideFromPool =
        workspaceBalancerConfig?.rank_delta_threshold != null &&
        workspaceBalancerConfig.rank_delta_hide_from_pool;

      const nextStates = allPlayerValidationStates.filter((state) => {
        if (poolView === "rank_delta") {
          return state.issues.some((i) => i.code === "rank_delta_warning");
        }
        if (poolView === "excluded") {
          if (state.player.is_in_pool) return false;
        } else {
          if (!state.player.is_in_pool) return false;
          if (hideFromPool && state.issues.some((i) => i.code === "rank_delta_warning")) return false;
        }
        if (poolView === "ready" && hasBlockingIssues(state.issues)) return false;
        if (poolView === "needs_fix" && !hasBlockingIssues(state.issues)) return false;
        if (!normalizedSearchQuery) return true;
        return buildPlayerSearchIndex(
          state.player,
          applicationsById.get(state.player.application_id) ?? null,
        ).includes(normalizedSearchQuery);
      });
      return sortPlayerStates(nextStates, poolSort);
    }, [allPlayerValidationStates, applicationsById, normalizedSearchQuery, poolSort, poolView, workspaceBalancerConfig]);

    const sidebarPlayerCount = poolView === "excluded" ? excludedPlayers.length : poolPlayers.length;

    const poolFilterOptions: PoolFilterOption[] = [
      { value: "all", label: "All", count: poolPlayers.length },
      { value: "excluded", label: "Excluded", count: excludedPlayers.length },
      { value: "needs_fix", label: "Need Fix", count: invalidPlayers.length },
      { value: "ready", label: "Ready", count: readyPlayers.length },
      ...(workspaceBalancerConfig?.rank_delta_threshold != null
        ? [{ value: "rank_delta" as PoolView, label: "Rank Δ", count: rankDeltaPlayers.length }]
        : []),
    ];

    const filteredPoolEmptyState = useMemo(() => {
      if (normalizedSearchQuery.length > 0) {
        return { title: "No players match this search", description: "Try another BattleTag, role, or division." };
      }
      if (poolView === "needs_fix") {
        return { title: "No players need fixes right now", description: "Every player in the pool is ready for the balancer." };
      }
      if (poolView === "ready") {
        return { title: "No ready players yet", description: "Fix player conflicts or add ranked roles to start balancing." };
      }
      if (poolView === "excluded") {
        return { title: "No excluded players", description: "Every player is currently included in the Balancing Pool." };
      }
      return { title: "No players in the pool", description: "Use the search above to include approved registrations in the Balancing Pool." };
    }, [normalizedSearchQuery, poolView]);

    const validPlayerIds = useMemo(
      () => new Set(allPlayerValidationStates.map((state) => state.player.id)),
      [allPlayerValidationStates],
    );
    const effectiveSelectedIds = useMemo(
      () => new Set([...selectedIds].filter((id) => validPlayerIds.has(id))),
      [selectedIds, validPlayerIds],
    );
    const selectedPlayerIds = useMemo(() => Array.from(effectiveSelectedIds), [effectiveSelectedIds]);
    const selectedCount = effectiveSelectedIds.size;
    const hasStatusActions = flattenStatusOptions(balancerStatusOptions).length > 0;
    const quickActionsDisabled = actionsDisabled || isAddingPlayer;

    const toggleSelectedPlayer = (playerId: number) => {
      setSelectedIds((current) => {
        const next = new Set(current);
        if (next.has(playerId)) {
          next.delete(playerId);
        } else {
          next.add(playerId);
        }
        return next;
      });
    };

    const selectVisiblePlayers = () => {
      setSelectedIds((current) => {
        const next = new Set(current);
        filteredPoolPlayerStates.forEach(({ player }) => next.add(player.id));
        return next;
      });
    };

    const clearSelection = () => setSelectedIds(new Set());

    const runBulkPoolMembership = async (isInPool: boolean) => {
      if (!onBulkPoolMembership || selectedPlayerIds.length === 0) return;
      try {
        await onBulkPoolMembership(selectedPlayerIds, isInPool);
        clearSelection();
      } catch {
        // Mutation callbacks own the user-facing error toast.
      }
    };

    const runBulkBalancerStatus = async (balancerStatus: string) => {
      if (!onBulkBalancerStatus || selectedPlayerIds.length === 0) return;
      try {
        await onBulkBalancerStatus(selectedPlayerIds, balancerStatus);
        clearSelection();
      } catch {
        // Mutation callbacks own the user-facing error toast.
      }
    };

    if (collapsed) {
      return (
        <div
          className={cn(
            PANEL_CLASS,
            "flex min-h-0 flex-col items-center gap-3 p-2",
          )}
        >
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-9 w-9 rounded-xl border border-white/8 bg-black/15 text-white/60 hover:bg-white/5 hover:text-white"
            onClick={onToggleCollapsed}
          >
            <PanelLeftOpen className="h-4 w-4" />
            <span className="sr-only">Expand Balancing Pool sidebar</span>
          </Button>
          <div className="flex flex-1 flex-col items-center gap-2 pt-1">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/8 bg-black/15 text-white/70">
              <Columns3 className="h-4 w-4" />
            </div>
            <div className="text-center text-[10px] uppercase tracking-[0.16em] text-white/30 [writing-mode:vertical-rl]">
              Pool
            </div>
          </div>
          <div className="flex flex-col items-center gap-1.5">
            <div className="rounded-lg border border-white/8 bg-black/15 px-2 py-1 text-[10px] text-white/55">
              {poolPlayers.length}
            </div>
            {invalidPlayers.length > 0 ? (
              <div className="rounded-lg border border-amber-400/20 bg-amber-500/8 px-2 py-1 text-[10px] text-amber-100/80">
                {invalidPlayers.length}
              </div>
            ) : null}
          </div>
        </div>
      );
    }

    return (
      <div className={cn(PANEL_CLASS, "flex min-h-0 flex-col p-4")}>
        <div className="mb-2 flex items-center justify-between gap-2">
          <div>
            <div className="text-[11px] uppercase tracking-[0.16em] text-white/28">
              Balancing Pool
            </div>
            <div className="mt-1 text-sm text-white/72">
              {poolPlayers.length} players
            </div>
          </div>
          <div className="flex items-center gap-1">
            {workspaceId != null ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-lg border border-white/8 bg-black/15 text-white/55 hover:bg-white/5 hover:text-white"
                title="Pool rank-delta settings"
                onClick={() => setConfigDialogOpen(true)}
              >
                <Settings2 className="h-3.5 w-3.5" />
                <span className="sr-only">Pool rank-delta settings</span>
              </Button>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 rounded-lg border border-white/8 bg-black/15 px-2 text-[11px] text-white/60 hover:bg-white/5 hover:text-white"
              onClick={onToggleCollapsed}
            >
              <PanelLeftClose className="mr-1 h-3.5 w-3.5" />
              Collapse
              <ChevronLeft className="ml-1 h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
        <div className="space-y-2.5">
          {/* Missing rank alert */}
          {missingRankCount > 0 ? (
            <button
              type="button"
              onClick={() => {
                setPoolView("needs_fix");
                setSidebarSearchMode("default");
              }}
              className="flex w-full items-center gap-2 rounded-lg border border-amber-400/20 bg-amber-500/8 px-3 py-2 text-left transition hover:bg-amber-500/12"
            >
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-300" />
              <span className="text-xs text-amber-100/80">
                {missingRankCount} player{missingRankCount !== 1 ? "s" : ""} need ranked roles
              </span>
            </button>
          ) : null}

          {/* Search */}
          <PoolSearchCombobox
            playerStates={allPlayerValidationStates}
            applications={applications}
            value={sidebarSearchQuery}
            onValueChange={(nextValue) => {
              setSidebarSearchQuery(nextValue);
              if (nextValue.trim().length > 0) {
                setSidebarSearchMode("default");
              }
            }}
            sortValue={poolSort}
            onSortValueChange={(value) => setPoolSort(value as PoolSortValue)}
            showFilters={showSidebarFilters}
            onShowFiltersChange={setShowSidebarFilters}
            onSelectPlayer={(playerId) => {
              onSelectPlayer(playerId);
              setSidebarSearchMode("default");
            }}
            onAddFromApplication={onAddFromApplication}
            disabled={isAddingPlayer}
            suggestionsMode={sidebarSearchMode}
          />

          {/* Pool / Add mode toggle */}
          <div className="flex items-center justify-between">
            <div className="flex rounded-lg border border-white/8 bg-black/15 p-0.5">
              <button
                type="button"
                onClick={() => {
                  setSidebarSearchQuery("");
                  setSidebarSearchMode("default");
                }}
                className={cn(
                  "rounded-md px-2.5 py-1 text-[11px] font-medium transition",
                  sidebarSearchMode === "default"
                    ? "bg-white/10 text-white"
                    : "text-white/45 hover:text-white/70",
                )}
              >
                Pool
              </button>
              <button
                type="button"
                onClick={() => {
                  setSidebarSearchQuery("");
                  setSidebarSearchMode("applications");
                }}
                className={cn(
                  "rounded-md px-2.5 py-1 text-[11px] font-medium transition",
                  sidebarSearchMode === "applications"
                    ? "bg-white/10 text-white"
                    : "text-white/45 hover:text-white/70",
                )}
              >
                Add{addableApplications.length > 0 ? ` (${addableApplications.length})` : ""}
              </button>
            </div>
            <div className="flex items-center gap-1.5">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={allPlayerValidationStates.length === 0}
                className="h-7 rounded-lg border border-white/8 bg-black/15 px-2 text-[11px] text-white/55 hover:bg-white/5 hover:text-white"
                onClick={() => setIsTriageBoardOpen(true)}
              >
                <Columns3 className="mr-1 h-3 w-3" />
                Board
              </Button>
              <span className="text-[10px] text-white/30">
                {addableApplications.length} available
              </span>
            </div>
          </div>

          {/* Filter pills + count */}
          <div className="flex flex-wrap items-center gap-1.5">
            {poolFilterOptions.map((option) => {
              const isActive = option.value === poolView;
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => {
                    setPoolView(option.value);
                    setSidebarSearchMode("default");
                  }}
                  className={cn(
                    "rounded-lg px-2.5 py-1.5 text-xs font-medium transition",
                    isActive
                      ? "bg-white/10 text-white"
                      : "bg-white/3 text-white/45 hover:bg-white/6 hover:text-white/80",
                  )}
                >
                  {option.label}
                  <span className="ml-1 text-[10px] text-white/30">{option.count}</span>
                </button>
              );
            })}
            <span className="ml-auto text-[10px] text-white/30">
              {filteredPoolPlayerStates.length} / {sidebarPlayerCount}
            </span>
          </div>

          {sidebarSearchMode === "default" ? (
            <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-white/8 bg-black/15 p-1.5">
              {selectedCount > 0 ? (
                <>
                  <div className="flex items-center gap-1.5 px-1.5 text-[11px] font-medium text-white/75">
                    <Check className="h-3.5 w-3.5 text-cyan-200" />
                    {selectedCount} selected
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={quickActionsDisabled || !onBulkPoolMembership}
                    className="h-7 rounded-lg border-white/10 bg-black/15 px-2 text-[11px] text-white/70 hover:bg-white/5 hover:text-white"
                    onClick={() => runBulkPoolMembership(true)}
                  >
                    <PlusCircle className="mr-1 h-3 w-3" />
                    Include
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={quickActionsDisabled || !onBulkPoolMembership}
                    className="h-7 rounded-lg border-white/10 bg-black/15 px-2 text-[11px] text-white/70 hover:bg-white/5 hover:text-white"
                    onClick={() => runBulkPoolMembership(false)}
                  >
                    <ShieldX className="mr-1 h-3 w-3" />
                    Exclude
                  </Button>
                  <BulkStatusMenu
                    statusOptions={balancerStatusOptions}
                    disabled={quickActionsDisabled || !onBulkBalancerStatus || !hasStatusActions}
                    onChange={runBulkBalancerStatus}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="ml-auto h-7 w-7 rounded-lg border border-white/8 bg-black/15 text-white/45 hover:bg-white/5 hover:text-white"
                    onClick={clearSelection}
                  >
                    <X className="h-3.5 w-3.5" />
                    <span className="sr-only">Clear selection</span>
                  </Button>
                </>
              ) : (
                <>
                  <span className="px-1.5 text-[11px] text-white/35">Select players for bulk actions</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={filteredPoolPlayerStates.length === 0}
                    className="ml-auto h-7 rounded-lg border border-white/8 bg-black/15 px-2 text-[11px] text-white/45 hover:bg-white/5 hover:text-white"
                    onClick={selectVisiblePlayers}
                  >
                    Select visible
                  </Button>
                </>
              )}
            </div>
          ) : null}
        </div>

        <div className="mt-2.5 min-h-0 flex-1">
          {sidebarSearchMode === "applications" ? (
            <ScrollArea className="h-full">
              <div className="space-y-1 pr-1">
                {addableApplications.length > 0 ? (
                  addableApplications.map((application) => (
                    <button
                      key={application.id}
                      type="button"
                      disabled={isAddingPlayer}
                      onClick={() => onAddFromApplication(application)}
                      className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition hover:bg-white/5 disabled:opacity-50"
                    >
                      <Plus className="h-3.5 w-3.5 shrink-0 text-primary" />
                      <span className="min-w-0 flex-1 truncate text-sm text-white/80">{application.battle_tag}</span>
                      <span className="shrink-0 text-[10px] text-white/30">Include</span>
                    </button>
                  ))
                ) : (
                  <div className="flex flex-col items-center justify-center gap-1.5 py-10 text-center">
                    <p className="text-sm font-medium text-white/50">No available registrations</p>
                    <p className="text-xs text-white/30">All approved registrations are already in the pool.</p>
                  </div>
                )}
              </div>
            </ScrollArea>
          ) : (
            <PoolPlayerCompactList
              playerStates={filteredPoolPlayerStates}
              registrationsById={registrationsById}
              statusOptions={balancerStatusOptions}
              selectedPlayerId={selectedPlayerId}
              selectedBulkIds={effectiveSelectedIds}
              onToggleBulkSelection={toggleSelectedPlayer}
              onSelectPlayer={(playerId) => {
                onSelectPlayer(playerId);
                if (playerId !== null) {
                  setSidebarSearchMode("default");
                }
              }}
              onSetPoolMembership={onSetPoolMembership}
              onSetBalancerStatus={onSetBalancerStatus}
              actionsDisabled={quickActionsDisabled}
              maxHeightClassName="h-full"
              emptyTitle={filteredPoolEmptyState.title}
              emptyDescription={filteredPoolEmptyState.description}
            />
          )}
        </div>

        <PoolTriageBoard
          open={isTriageBoardOpen}
          onOpenChange={setIsTriageBoardOpen}
          playerStates={allPlayerValidationStates}
          registrationsById={registrationsById}
          statusOptions={balancerStatusOptions}
          selectedPlayerId={selectedPlayerId}
          onSelectPlayer={(playerId) => {
            onSelectPlayer(playerId);
            if (playerId !== null) {
              setSidebarSearchMode("default");
              setIsTriageBoardOpen(false);
            }
          }}
          onSetPoolMembership={onSetPoolMembership}
          onSetBalancerStatus={onSetBalancerStatus}
          actionsDisabled={quickActionsDisabled}
        />

        {workspaceId != null ? (
          <WorkspaceBalancerConfigDialog
            workspaceId={workspaceId}
            config={workspaceBalancerConfig}
            open={configDialogOpen}
            onOpenChange={setConfigDialogOpen}
          />
        ) : null}
      </div>
    );
  },
);
