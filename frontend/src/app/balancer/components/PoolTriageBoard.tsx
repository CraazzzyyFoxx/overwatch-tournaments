"use client";

import { useMemo } from "react";
import { DndContext, useDraggable, useDroppable, type DragEndEvent } from "@dnd-kit/core";
import { GripVertical } from "lucide-react";
import { useTranslations } from "next-intl";

import { EmptyNote } from "@/components/kit/EmptyNote";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useDragSensors } from "@/hooks/useDragSensors";
import { cn } from "@/lib/utils";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { RoleOntology } from "@/lib/roster/ontology";
import type { DivisionGrid } from "@/types/workspace.types";
import {
  POOL_LANES,
  derivePoolLane,
  getPoolDropPatch,
  type PlayerValidationState,
  type PoolLane,
} from "@/components/balancer/balancer-page-helpers";

import type { StatusOptionGroups } from "./BalancerStatusMenu";
import { PoolPlayerCard } from "./PoolPlayerCard";

type PoolTriageBoardProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  playerStates: PlayerValidationState[];
  /** The tournament owner's role dictionary: role glyphs and tints. `null` while it loads. */
  ontology: RoleOntology | null;
  /** The owner game's grid the cards' division crests resolve in. */
  divisionGrid: DivisionGrid;
  registrationsById?: Map<number, AdminRegistration>;
  statusOptions?: StatusOptionGroups;
  selectedPlayerId?: number | null;
  onSelectPlayer: (playerId: number | null) => void;
  onSetPoolMembership?: (playerId: number, isInPool: boolean) => unknown;
  onSetBalancerStatus?: (playerId: number, balancerStatus: string) => unknown;
  actionsDisabled?: boolean;
};

const LANE_ACCENTS: Record<PoolLane, string> = {
  // Neutral/inactive lane: overlay tokens instead of a hue, so it reads as
  // "no accent" beside the amber and emerald lanes.
  excluded: "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)]",
  needs_fix: "border-amber-300/20 bg-amber-500/[0.07]",
  ready: "border-emerald-300/20 bg-emerald-500/[0.07]",
};

function isCardActionTarget(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest("[data-card-action]") !== null;
}

function TriagePlayerCard({
  state,
  registration,
  ontology,
  divisionGrid,
  statusOptions,
  selectedPlayerId,
  actionsDisabled = false,
  onSelectPlayer,
  onSetPoolMembership,
  onSetBalancerStatus,
}: Readonly<{
  state: PlayerValidationState;
  registration: AdminRegistration | null;
  statusOptions?: StatusOptionGroups;
  ontology: RoleOntology | null;
  divisionGrid: DivisionGrid;
  selectedPlayerId?: number | null;
  actionsDisabled?: boolean;
  onSelectPlayer: (playerId: number | null) => void;
  onSetPoolMembership?: (playerId: number, isInPool: boolean) => unknown;
  onSetBalancerStatus?: (playerId: number, balancerStatus: string) => unknown;
}>) {
  const t = useTranslations("balancerTool.pool.triage");
  const lane = derivePoolLane(state);
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `pool-player:${state.player.id}`,
    data: { playerId: state.player.id, lane },
    // Dragging out of Excluded would include the player; that only happens through a status change.
    disabled: actionsDisabled || !onSetPoolMembership || !state.player.is_in_pool,
  });

  return (
    <PoolPlayerCard
      ref={setNodeRef}
      variant="card"
      player={state.player}
      issues={state.issues}
      registration={registration}
      statusOptions={statusOptions}
      ontology={ontology}
      divisionGrid={divisionGrid}
      selected={selectedPlayerId === state.player.id}
      actionsDisabled={actionsDisabled}
      onSelectPlayer={onSelectPlayer}
      onSetPoolMembership={onSetPoolMembership}
      onSetBalancerStatus={onSetBalancerStatus}
      style={transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined}
      className={cn(isDragging && "z-50 scale-[1.02] opacity-80 shadow-[0_22px_56px_rgba(0,0,0,0.34)]")}
      leading={
        state.player.is_in_pool ? (
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            data-card-action
            aria-label={t("drag")}
            className="shrink-0 cursor-grab touch-none text-[color:var(--aqt-fg-dim)] hover:text-[color:var(--aqt-fg)] active:cursor-grabbing"
            {...attributes}
            {...listeners}
          >
            <GripVertical aria-hidden="true" />
          </Button>
        ) : null
      }
    />
  );
}

function TriageLaneColumn({
  lane,
  states,
  ontology,
  divisionGrid,
  registrationsById,
  statusOptions,
  selectedPlayerId,
  actionsDisabled,
  onSelectPlayer,
  onSetPoolMembership,
  onSetBalancerStatus,
}: Readonly<{
  lane: PoolLane;
  states: PlayerValidationState[];
  ontology: RoleOntology | null;
  divisionGrid: DivisionGrid;
  registrationsById?: Map<number, AdminRegistration>;
  statusOptions?: StatusOptionGroups;
  selectedPlayerId?: number | null;
  actionsDisabled?: boolean;
  onSelectPlayer: (playerId: number | null) => void;
  onSetPoolMembership?: (playerId: number, isInPool: boolean) => unknown;
  onSetBalancerStatus?: (playerId: number, balancerStatus: string) => unknown;
}>) {
  const t = useTranslations("balancerTool.pool");
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
        isOver && "border-primary/60 bg-primary/[0.12]",
      )}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-[color:var(--aqt-fg)]">{t(`view.${lane}`)}</div>
          <div className="mt-0.5 text-label text-[color:var(--aqt-fg-dim)]">{t(`triage.laneHint.${lane}`)}</div>
        </div>
        <Badge tone="neutral" shape="pill" size="sm" className="tabular-nums">
          {states.length}
        </Badge>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        {states.length > 0 ? (
          // The click sits on the `<li>`, not on the card's own `div`: the card
          // is a drag source and a plain `div`, and `onClick` on a
          // non-interactive `div` is what the design gate rejects. Subtrees
          // marked `data-card-action` (grip, pool toggle, status menu, copy
          // controls) keep their own clicks.
          <ul aria-label={t("triage.laneList", { lane: t(`view.${lane}`) })} className="space-y-2 pr-2">
            {states.map((state) => (
              <li
                key={state.player.id}
                onClick={(event) => {
                  if (isCardActionTarget(event.target)) {
                    return;
                  }
                  onSelectPlayer(state.player.id);
                }}
              >
                <TriagePlayerCard
                  state={state}
                  registration={registrationsById?.get(state.player.id) ?? null}
                  ontology={ontology}
                  divisionGrid={divisionGrid}
                  statusOptions={statusOptions}
                  selectedPlayerId={selectedPlayerId}
                  actionsDisabled={actionsDisabled}
                  onSelectPlayer={onSelectPlayer}
                  onSetPoolMembership={onSetPoolMembership}
                  onSetBalancerStatus={onSetBalancerStatus}
                />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyNote size="sm" className="py-8 text-center">
            {t("triage.dropHere")}
          </EmptyNote>
        )}
      </ScrollArea>
    </section>
  );
}

export function PoolTriageBoard({
  open,
  onOpenChange,
  playerStates,
  ontology,
  divisionGrid,
  registrationsById,
  statusOptions,
  selectedPlayerId,
  onSelectPlayer,
  onSetPoolMembership,
  onSetBalancerStatus,
  actionsDisabled = false,
}: Readonly<PoolTriageBoardProps>) {
  const t = useTranslations("balancerTool.pool.triage");
  const sensors = useDragSensors();
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
      <DialogContent variant="panel" className="h-[min(760px,calc(100vh-3rem))] w-[min(1180px,calc(100vw-2rem))] max-w-none">
        <DialogHeader variant="panel">
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
          <div className="grid min-h-0 flex-1 gap-3 p-4 lg:grid-cols-3">
            {POOL_LANES.map((lane) => (
              <TriageLaneColumn
                key={lane}
                lane={lane}
                states={statesByLane[lane]}
                ontology={ontology}
                divisionGrid={divisionGrid}
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
