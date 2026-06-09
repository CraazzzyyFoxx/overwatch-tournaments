"use client";

import { useMemo } from "react";
import { DndContext, PointerSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { Check, Circle, GripVertical, Pencil, PlusCircle, ShieldX } from "lucide-react";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { AdminRegistration, BalancerPlayerRecord, BalancerRoleCode, StatusMeta } from "@/types/balancer-admin.types";
import {
  POOL_LANES,
  POOL_LANE_LABELS,
  derivePoolLane,
  getPoolDropPatch,
  getRegistrationBattleTags,
  type PlayerValidationState,
  type PoolLane,
} from "./balancer-page-helpers";
import { BattleTagContextMenuItems, BattleTagCopyButton, SmurfTagStrip } from "./BattleTagCopyControls";
import { ROLE_LABELS, isRoleEntryActive, type PlayerValidationIssue } from "./workspace-helpers";

type StatusOptionGroups = {
  system: StatusMeta[];
  custom: StatusMeta[];
};

type PoolTriageBoardProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  playerStates: PlayerValidationState[];
  registrationsById?: Map<number, AdminRegistration>;
  statusOptions?: StatusOptionGroups;
  selectedPlayerId?: number | null;
  onSelectPlayer: (playerId: number | null) => void;
  onSetPoolMembership?: (playerId: number, isInPool: boolean) => unknown;
  onSetBalancerStatus?: (playerId: number, balancerStatus: string) => unknown;
  actionsDisabled?: boolean;
};

const LANE_ACCENTS: Record<PoolLane, string> = {
  excluded: "border-slate-300/15 bg-slate-500/[0.06]",
  needs_fix: "border-amber-300/20 bg-amber-500/[0.07]",
  ready: "border-emerald-300/20 bg-emerald-500/[0.07]",
};

const LANE_COPY: Record<PoolLane, string> = {
  excluded: "Drop here to remove from the run.",
  needs_fix: "Included, but validation still needs attention.",
  ready: "Included and ready for balancing.",
};

const ROLE_TEXT_ACCENTS: Record<BalancerRoleCode, string> = {
  tank: "text-sky-300",
  dps: "text-orange-300",
  support: "text-emerald-300",
};

function sortRoleEntries(player: BalancerPlayerRecord) {
  return [...player.role_entries_json].sort((left, right) => left.priority - right.priority);
}

function uniqueRoleCodes(roleCodes: BalancerRoleCode[]): BalancerRoleCode[] {
  return roleCodes.filter((roleCode, index) => roleCodes.indexOf(roleCode) === index);
}

function splitBattleTag(battleTag: string): { name: string; suffix: string | null } {
  const hashIndex = battleTag.indexOf("#");
  if (hashIndex < 0) {
    return { name: battleTag, suffix: null };
  }
  return { name: battleTag.slice(0, hashIndex), suffix: battleTag.slice(hashIndex) };
}

function getIssueChipLabel(issue: PlayerValidationIssue): string {
  return issue.code === "missing_ranked_role" ? "No ranked roles" : "Role mismatch";
}

function flattenStatusOptions(statusOptions?: StatusOptionGroups): StatusMeta[] {
  return statusOptions ? [...statusOptions.system, ...statusOptions.custom] : [];
}

function getStatusName(statusOptions: StatusOptionGroups | undefined, value: string | null | undefined): string {
  if (!value) {
    return "No status";
  }
  return flattenStatusOptions(statusOptions).find((option) => option.value === value)?.name ?? value;
}

function CompactStatusMenu({
  value,
  statusOptions,
  disabled,
  onChange,
}: {
  value: string | null | undefined;
  statusOptions?: StatusOptionGroups;
  disabled?: boolean;
  onChange?: (status: string) => void;
}) {
  if (!statusOptions || !onChange) {
    return null;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          className="h-7 max-w-[128px] justify-start rounded-lg border border-white/8 bg-black/15 px-2 text-[11px] text-white/60 hover:bg-white/5 hover:text-white"
        >
          <span className="truncate">{getStatusName(statusOptions, value)}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>Balancer status</DropdownMenuLabel>
        {statusOptions.system.map((option) => (
          <DropdownMenuItem key={option.value} onClick={() => onChange(option.value)}>
            {option.value === value ? <Check className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
            {option.name}
          </DropdownMenuItem>
        ))}
        {statusOptions.custom.length > 0 ? <DropdownMenuSeparator /> : null}
        {statusOptions.custom.map((option) => (
          <DropdownMenuItem key={option.value} onClick={() => onChange(option.value)}>
            {option.value === value ? <Check className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
            {option.name}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function StatusContextMenuItems({
  value,
  statusOptions,
  disabled,
  onChange,
}: {
  value: string | null | undefined;
  statusOptions?: StatusOptionGroups;
  disabled?: boolean;
  onChange?: (status: string) => void;
}) {
  if (!statusOptions || !onChange) {
    return null;
  }

  return (
    <ContextMenuSub>
      <ContextMenuSubTrigger disabled={disabled}>Set balancer status</ContextMenuSubTrigger>
      <ContextMenuSubContent className="w-52">
        {statusOptions.system.map((option) => (
          <ContextMenuItem key={option.value} onClick={() => onChange(option.value)}>
            {option.value === value ? <Check className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
            {option.name}
          </ContextMenuItem>
        ))}
        {statusOptions.custom.length > 0 ? <ContextMenuSeparator /> : null}
        {statusOptions.custom.map((option) => (
          <ContextMenuItem key={option.value} onClick={() => onChange(option.value)}>
            {option.value === value ? <Check className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
            {option.name}
          </ContextMenuItem>
        ))}
      </ContextMenuSubContent>
    </ContextMenuSub>
  );
}

function isCardActionTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.closest("[data-card-action]") !== null;
}

function TriagePlayerCard({
  state,
  registration,
  statusOptions,
  selectedPlayerId,
  actionsDisabled,
  onSelectPlayer,
  onSetPoolMembership,
  onSetBalancerStatus,
}: {
  state: PlayerValidationState;
  registration: AdminRegistration | null;
  statusOptions?: StatusOptionGroups;
  selectedPlayerId?: number | null;
  actionsDisabled?: boolean;
  onSelectPlayer: (playerId: number | null) => void;
  onSetPoolMembership?: (playerId: number, isInPool: boolean) => unknown;
  onSetBalancerStatus?: (playerId: number, balancerStatus: string) => unknown;
}) {
  const lane = derivePoolLane(state);
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `pool-player:${state.player.id}`,
    data: { playerId: state.player.id, lane },
    disabled: actionsDisabled || !onSetPoolMembership,
  });
  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` }
    : undefined;
  const sortedEntries = sortRoleEntries(state.player);
  const rankedEntries = sortedEntries.filter((entry) => isRoleEntryActive(entry) && entry.rank_value !== null);
  const rankedRoleCodes = uniqueRoleCodes(rankedEntries.map((entry) => entry.role));
  const primaryEntry = rankedEntries[0] ?? sortedEntries[0] ?? null;
  const primaryRole = primaryEntry?.role ?? null;
  const { name, suffix } = splitBattleTag(state.player.battle_tag);
  const isSelected = selectedPlayerId === state.player.id;
  const battleTags = getRegistrationBattleTags(registration, state.player.battle_tag);
  const primaryBattleTag = battleTags[0] ?? state.player.battle_tag;
  const smurfTags = battleTags.slice(1);
  const isReady = state.player.is_in_pool && state.issues.length === 0;

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <div
          ref={setNodeRef}
          style={style}
          onDoubleClick={(event) => {
            if (isCardActionTarget(event.target)) {
              return;
            }
            onSelectPlayer(state.player.id);
          }}
          className={cn(
            "cursor-pointer rounded-xl border border-border bg-card p-2.5 transition",
            isSelected && "border-violet-300/45 bg-violet-500/[0.08]",
            isDragging && "z-50 scale-[1.02] opacity-80 shadow-[0_22px_56px_rgba(0,0,0,0.34)]",
          )}
          title="Double-click to edit player"
        >
          <div className="flex items-start gap-2">
            <button
              type="button"
              data-card-action
              className="mt-0.5 flex h-6 w-6 shrink-0 cursor-grab touch-none items-center justify-center rounded-lg border border-white/10 bg-black/20 text-white/45 hover:text-white active:cursor-grabbing"
              {...attributes}
              {...listeners}
            >
              <GripVertical className="h-3.5 w-3.5" />
              <span className="sr-only">Drag player</span>
            </button>

            <div className="min-w-0 flex-1">
              <div className="w-full min-w-0 text-left">
                <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                  {rankedRoleCodes.length > 0 ? (
                    rankedRoleCodes.map((roleCode) => (
                      <PlayerRoleIcon key={roleCode} role={ROLE_LABELS[roleCode]} size={15} />
                    ))
                  ) : (
                    <span className="text-[11px] text-white/28">No roles</span>
                  )}
                  <span className="truncate text-[13px] font-semibold text-white/88">{name}</span>
                  {suffix ? <span className="shrink-0 text-[12px] text-white/30">{suffix}</span> : null}
                </div>
              </div>
              {state.player.is_flex || isReady || state.issues.length > 0 || smurfTags.length > 0 ? (
                <div className="mt-1 flex min-w-0 items-center gap-1 overflow-x-auto whitespace-nowrap pb-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                  {state.player.is_flex ? (
                    <span className="shrink-0 rounded-full border border-violet-300/20 bg-violet-500/12 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-violet-200">
                      Flex
                    </span>
                  ) : null}
                  {isReady ? (
                    <span className="shrink-0 rounded-full border border-emerald-300/20 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-200">
                      Ready
                    </span>
                  ) : null}
                  {state.issues.map((issue) => (
                    <span
                      key={`${state.player.id}-${issue.code}`}
                      className="shrink-0 rounded-full border border-amber-300/20 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-100/80"
                      title={issue.message}
                    >
                      {getIssueChipLabel(issue)}
                    </span>
                  ))}
                  <SmurfTagStrip smurfTags={smurfTags} compact />
                </div>
              ) : null}
            </div>

            <div className="flex shrink-0 items-center gap-1">
              {primaryEntry?.division_number != null ? (
                <PlayerDivisionIcon division={primaryEntry.division_number} width={20} height={20} />
              ) : null}
              {primaryEntry?.rank_value != null ? (
                <span className={cn("min-w-10 text-right text-[13px] font-semibold tabular-nums text-cyan-300", primaryRole && ROLE_TEXT_ACCENTS[primaryRole])}>
                  {primaryEntry.rank_value}
                </span>
              ) : (
                <span className="text-[12px] text-white/24">-</span>
              )}
            </div>
          </div>

          <div className="mt-2 flex items-center justify-between gap-2" data-card-action>
            <CompactStatusMenu
              value={registration?.balancer_status}
              statusOptions={statusOptions}
              disabled={actionsDisabled}
              onChange={registration ? (status) => onSetBalancerStatus?.(state.player.id, status) : undefined}
            />
            <div className="flex items-center gap-1">
              <BattleTagCopyButton battleTag={primaryBattleTag} className="h-7 w-7" />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={actionsDisabled || !onSetPoolMembership}
                className="h-7 rounded-lg border border-white/8 bg-black/15 px-2 text-[11px] text-white/60 hover:bg-white/5 hover:text-white"
                onClick={() => onSetPoolMembership?.(state.player.id, !state.player.is_in_pool)}
              >
                {state.player.is_in_pool ? <ShieldX className="mr-1 h-3 w-3" /> : <PlusCircle className="mr-1 h-3 w-3" />}
                {state.player.is_in_pool ? "Exclude" : "Include"}
              </Button>
            </div>
          </div>
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent className="w-56">
        <ContextMenuLabel>Player actions</ContextMenuLabel>
        <ContextMenuItem onClick={() => onSelectPlayer(state.player.id)}>
          <Pencil className="h-4 w-4" />
          Edit full profile
        </ContextMenuItem>
        <BattleTagContextMenuItems battleTags={battleTags} />
        {onSetPoolMembership ? (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem disabled={actionsDisabled} onClick={() => onSetPoolMembership(state.player.id, !state.player.is_in_pool)}>
              {state.player.is_in_pool ? <ShieldX className="h-4 w-4" /> : <PlusCircle className="h-4 w-4" />}
              {state.player.is_in_pool ? "Exclude from balancer" : "Include in balancer"}
            </ContextMenuItem>
          </>
        ) : null}
        <StatusContextMenuItems
          value={registration?.balancer_status}
          statusOptions={statusOptions}
          disabled={actionsDisabled}
          onChange={registration ? (status) => onSetBalancerStatus?.(state.player.id, status) : undefined}
        />
      </ContextMenuContent>
    </ContextMenu>
  );
}

function TriageLaneColumn({
  lane,
  states,
  registrationsById,
  statusOptions,
  selectedPlayerId,
  actionsDisabled,
  onSelectPlayer,
  onSetPoolMembership,
  onSetBalancerStatus,
}: {
  lane: PoolLane;
  states: PlayerValidationState[];
  registrationsById?: Map<number, AdminRegistration>;
  statusOptions?: StatusOptionGroups;
  selectedPlayerId?: number | null;
  actionsDisabled?: boolean;
  onSelectPlayer: (playerId: number | null) => void;
  onSetPoolMembership?: (playerId: number, isInPool: boolean) => unknown;
  onSetBalancerStatus?: (playerId: number, balancerStatus: string) => unknown;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: `pool-lane:${lane}`,
    data: { lane },
    disabled: actionsDisabled || !onSetPoolMembership,
  });

  return (
    <section
      ref={setNodeRef}
      className={cn(
        "flex min-h-0 flex-col rounded-2xl border p-3 transition",
        LANE_ACCENTS[lane],
        isOver && "border-violet-300/60 bg-violet-500/[0.12]",
      )}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-white/90">{POOL_LANE_LABELS[lane]}</div>
          <div className="mt-0.5 text-[11px] text-white/38">{LANE_COPY[lane]}</div>
        </div>
        <div className="rounded-full border border-white/10 bg-black/20 px-2 py-0.5 text-[11px] font-semibold tabular-nums text-white/60">
          {states.length}
        </div>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-2 pr-2">
          {states.length > 0 ? (
            states.map((state) => (
              <TriagePlayerCard
                key={state.player.id}
                state={state}
                registration={registrationsById?.get(state.player.id) ?? null}
                statusOptions={statusOptions}
                selectedPlayerId={selectedPlayerId}
                actionsDisabled={actionsDisabled}
                onSelectPlayer={onSelectPlayer}
                onSetPoolMembership={onSetPoolMembership}
                onSetBalancerStatus={onSetBalancerStatus}
              />
            ))
          ) : (
            <div className="rounded-xl border border-dashed border-white/10 bg-black/10 px-3 py-8 text-center text-xs text-white/35">
              Drop players here
            </div>
          )}
        </div>
      </ScrollArea>
    </section>
  );
}

export function PoolTriageBoard({
  open,
  onOpenChange,
  playerStates,
  registrationsById,
  statusOptions,
  selectedPlayerId,
  onSelectPlayer,
  onSetPoolMembership,
  onSetBalancerStatus,
  actionsDisabled = false,
}: PoolTriageBoardProps) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const statesByLane = useMemo(
    () =>
      POOL_LANES.reduce<Record<PoolLane, PlayerValidationState[]>>(
        (acc, lane) => {
          acc[lane] = playerStates.filter((state) => derivePoolLane(state) === lane);
          return acc;
        },
        { excluded: [], needs_fix: [], ready: [] },
      ),
    [playerStates],
  );

  const handleDragEnd = async (event: DragEndEvent) => {
    const playerId = event.active.data.current?.playerId as number | undefined;
    const targetLane = event.over?.data.current?.lane as PoolLane | undefined;
    if (!playerId || !targetLane || !onSetPoolMembership) {
      return;
    }

    const currentState = playerStates.find((state) => state.player.id === playerId);
    if (!currentState) {
      return;
    }

    const patch = getPoolDropPatch(targetLane);
    if (currentState.player.is_in_pool === patch.is_in_pool) {
      return;
    }

    await onSetPoolMembership(playerId, patch.is_in_pool);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[min(760px,calc(100vh-3rem))] w-[min(1180px,calc(100vw-2rem))] max-w-none flex-col gap-0 overflow-hidden border-border bg-popover p-0 text-white shadow-2xl shadow-black/50">
        <DialogHeader className="shrink-0 border-b border-white/8 px-5 py-4">
          <DialogTitle className="text-base text-white">Balancing Pool Triage</DialogTitle>
          <DialogDescription className="text-xs text-white/42">
            Drag players to include or exclude them. Need Fix and Ready are computed from validation, so included players settle into the correct lane automatically.
          </DialogDescription>
        </DialogHeader>
        <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
          <div className="grid min-h-0 flex-1 gap-3 p-4 lg:grid-cols-3">
            {POOL_LANES.map((lane) => (
              <TriageLaneColumn
                key={lane}
                lane={lane}
                states={statesByLane[lane]}
                registrationsById={registrationsById}
                statusOptions={statusOptions}
                selectedPlayerId={selectedPlayerId}
                actionsDisabled={actionsDisabled}
                onSelectPlayer={onSelectPlayer}
                onSetPoolMembership={onSetPoolMembership}
                onSetBalancerStatus={onSetBalancerStatus}
              />
            ))}
          </div>
        </DndContext>
      </DialogContent>
    </Dialog>
  );
}
