"use client";

import { memo, useRef, type MouseEvent } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Check } from "lucide-react";
import { useTranslations } from "next-intl";

import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { Button } from "@/components/ui/button";
import { ContextMenuItem, ContextMenuSeparator } from "@craazzzyyfoxx/admin-kit/ui/context-menu";
import { cn } from "@/lib/utils";
import type { AdminRegistration, BalancerPlayerRecord } from "@/types/balancer-admin.types";
import type { RoleOntology } from "@/lib/roster/ontology";
import type { DivisionGrid } from "@/types/workspace.types";
import type { StatusOptionGroups } from "./BalancerStatusMenu";
import { PoolPlayerCard, type PoolPlayerCardProps } from "./PoolPlayerCard";
import type { PlayerValidationIssue } from "@/components/balancer/workspace-helpers";

type PoolPlayerCompactListProps = {
  playerStates: Array<{
    player: BalancerPlayerRecord;
    issues: PlayerValidationIssue[];
  }>;
  /** The tournament owner's role dictionary: role names, glyphs and tints. `null` while it loads. */
  ontology: RoleOntology | null;
  /** The owner game's grid the rows' division crests resolve in. */
  divisionGrid: DivisionGrid;
  registrationsById?: Map<number, AdminRegistration>;
  statusOptions?: StatusOptionGroups;
  selectedPlayerId?: number | null;
  selectedBulkIds?: ReadonlySet<number>;
  onToggleBulkSelection?: (playerId: number) => void;
  onSelectPlayer?: (playerId: number | null) => void;
  onSetPoolMembership?: (playerId: number, isInPool: boolean) => unknown;
  onSetBalancerStatus?: (playerId: number, balancerStatus: string) => unknown;
  actionsDisabled?: boolean;
  emptyTitle: string;
  emptyDescription: string;
};


/** A single-line row is ~52px; rows carrying issue chips are ~76px. */
const ESTIMATED_ROW_HEIGHT = 64;
/** Seed used until the ResizeObserver reports the real scroller height. */
const INITIAL_VIEWPORT_HEIGHT = 800;
const ROW_GAP = 6;
/** Below this a plain list is cheaper than measuring every row; matches the pool sizes we see. */
const VIRTUALIZATION_THRESHOLD = 50;


type PoolPlayerRowProps = Omit<PoolPlayerCardProps, "variant" | "leading" | "menuItems" | "className" | "style"> & {
  isBulkSelected: boolean;
  onToggleBulkSelection?: (playerId: number) => void;
};

/**
 * Memoized so a keystroke in the pool search only re-renders the rows whose data changed.
 * Each row mounts two Radix roots (context menu + status menu), which is why the list is
 * also virtualized — 200 pooled players would otherwise cost ~500ms per filter change.
 */
const PoolPlayerRow = memo(function PoolPlayerRow({
  isBulkSelected,
  onToggleBulkSelection,
  ...card
}: PoolPlayerRowProps) {
  const t = useTranslations("balancerTool.pool.list");
  const { player } = card;

  return (
    <PoolPlayerCard
      {...card}
      variant="row"
      className={cn(isBulkSelected && !card.selected && "border-cyan-400/35 bg-cyan-500/[0.06]")}
      leading={
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          data-card-action
          aria-pressed={isBulkSelected}
          aria-label={t(isBulkSelected ? "unselect" : "select", { name: player.identity })}
          onClick={() => onToggleBulkSelection?.(player.id)}
          className={cn(
            "shrink-0",
            isBulkSelected
              ? "border-cyan-300/50 bg-cyan-500/18 text-cyan-100"
              : "text-[color:var(--aqt-fg-dim)] hover:text-[color:var(--aqt-fg-muted)]",
          )}
        >
          {isBulkSelected ? <Check aria-hidden="true" /> : <span aria-hidden="true" className="size-2 rounded-full bg-current" />}
        </Button>
      }
      menuItems={
        onToggleBulkSelection ? (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem onClick={() => onToggleBulkSelection(player.id)}>
              <Check className="h-4 w-4" />
              {isBulkSelected ? t("removeFromSelection") : t("addToSelection")}
            </ContextMenuItem>
          </>
        ) : null
      }
    />
  );
});

export function PoolPlayerCompactList({
  playerStates,
  ontology,
  divisionGrid,
  registrationsById,
  statusOptions,
  selectedPlayerId,
  selectedBulkIds,
  onToggleBulkSelection,
  onSelectPlayer,
  onSetPoolMembership,
  onSetBalancerStatus,
  actionsDisabled = false,
  emptyTitle,
  emptyDescription,
}: Readonly<PoolPlayerCompactListProps>) {
  const t = useTranslations("balancerTool.pool.list");
  const scrollRef = useRef<HTMLDivElement>(null);
  const shouldVirtualize = playerStates.length > VIRTUALIZATION_THRESHOLD;
  const virtualizer = useVirtualizer({
    count: shouldVirtualize ? playerStates.length : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ESTIMATED_ROW_HEIGHT,
    overscan: 6,
    gap: ROW_GAP,
    // Without a seed the first render measures 0px and paints an empty list for a frame.
    initialRect: { width: 0, height: INITIAL_VIEWPORT_HEIGHT },
  });

  if (playerStates.length === 0) {
    return (
      <EmptyNote title={emptyTitle} className="flex-1 justify-center">
        {emptyDescription}
      </EmptyNote>
    );
  }

  const row = (index: number) => {
    const { player, issues } = playerStates[index];

    return (
      <PoolPlayerRow
        player={player}
        issues={issues}
        ontology={ontology}
        divisionGrid={divisionGrid}
        registration={registrationsById?.get(player.id) ?? null}
        statusOptions={statusOptions}
        selected={player.id === selectedPlayerId}
        isBulkSelected={selectedBulkIds?.has(player.id) ?? false}
        onToggleBulkSelection={onToggleBulkSelection}
        onSelectPlayer={onSelectPlayer}
        onSetPoolMembership={onSetPoolMembership}
        onSetBalancerStatus={onSetBalancerStatus}
        actionsDisabled={actionsDisabled}
      />
    );
  };

  // One click on a row opens the player sheet. The handler sits on the `<li>`
  // rather than the row's own `div` — `onClick` on a non-interactive `div` is
  // what the design gate rejects — and subtrees marked `data-card-action`
  // (bulk select, status menu, copy controls) keep their own clicks. The check
  // is `Element`, not `HTMLElement`: a click landing on a button's SVG icon
  // has an `SVGElement` target and would otherwise fall through to here.
  const openRow = (index: number) => (event: MouseEvent<HTMLLIElement>) => {
    if (event.target instanceof Element && event.target.closest("[data-card-action]")) {
      return;
    }
    onSelectPlayer?.(playerStates[index].player.id);
  };

  return (
    // Below `xl` the balancer shell drops its `h-svh`/`overflow-hidden`, so `flex-1` alone would
    // resolve to the full virtual height and push a scrollbar onto the document. The cap keeps the
    // pool its own scroll region; at `xl` the flex track is smaller and the cap never applies.
    <div
      ref={scrollRef}
      className="min-h-0 max-h-[calc(100svh-16rem)] flex-1 overflow-y-auto overflow-x-hidden pr-2"
    >
      {shouldVirtualize ? (
        <ul
          aria-label={t("label")}
          className="relative w-full"
          style={{ height: virtualizer.getTotalSize() }}
        >
          {virtualizer.getVirtualItems().map((virtualRow) => (
            <li
              key={playerStates[virtualRow.index].player.id}
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              className="absolute inset-x-0 top-0"
              style={{ transform: `translateY(${virtualRow.start}px)` }}
              onClick={openRow(virtualRow.index)}
            >
              {row(virtualRow.index)}
            </li>
          ))}
        </ul>
      ) : (
        <ul aria-label={t("label")} className="space-y-1.5">
          {playerStates.map((state, index) => (
            <li key={state.player.id} onClick={openRow(index)}>
              {row(index)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
