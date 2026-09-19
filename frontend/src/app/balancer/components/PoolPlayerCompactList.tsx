"use client";

import { memo, useRef, type MouseEvent } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Check, Circle, Pencil, PlusCircle, ShieldX } from "lucide-react";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { cn } from "@/lib/utils";
import type { AdminRegistration, BalancerPlayerRecord } from "@/types/balancer-admin.types";
import { ROLE_TEXT_ACCENTS, getRegistrationBattleTags, splitBattleTag } from "@/components/balancer/balancer-page-helpers";
import { BalancerStatusContextMenuItems, BalancerStatusMenu, type StatusOptionGroups } from "./BalancerStatusMenu";
import { BattleTagContextMenuItems, BattleTagCopyButton, SmurfTagStrip } from "./BattleTagCopyControls";
import { IssueChip, issueChipKey } from "./IssueChip";
import {
  ROLE_LABELS,
  isRoleEntryActive,
  type PlayerValidationIssue,
} from "@/components/balancer/workspace-helpers";

type PoolPlayerCompactListProps = {
  playerStates: Array<{
    player: BalancerPlayerRecord;
    issues: PlayerValidationIssue[];
  }>;
  registrationsById?: Map<number, AdminRegistration>;
  statusOptions?: StatusOptionGroups;
  selectedPlayerId?: number | null;
  selectedBulkIds?: ReadonlySet<number>;
  onToggleBulkSelection?: (playerId: number) => void;
  onSelectPlayer?: (playerId: number | null) => void;
  onSetPoolMembership?: (playerId: number, isInPool: boolean) => unknown;
  onSetBalancerStatus?: (playerId: number, balancerStatus: string) => unknown;
  actionsDisabled?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
};


/** A single-line row is ~52px; rows carrying issue chips are ~76px. */
const ESTIMATED_ROW_HEIGHT = 64;
/** Seed used until the ResizeObserver reports the real scroller height. */
const INITIAL_VIEWPORT_HEIGHT = 800;
const ROW_GAP = 6;
/** Below this a plain list is cheaper than measuring every row; matches the pool sizes we see. */
const VIRTUALIZATION_THRESHOLD = 50;


type PoolPlayerRowProps = {
  player: BalancerPlayerRecord;
  issues: PlayerValidationIssue[];
  registration: AdminRegistration | null;
  statusOptions?: StatusOptionGroups;
  isSelected: boolean;
  isBulkSelected: boolean;
  onToggleBulkSelection?: (playerId: number) => void;
  onSelectPlayer?: (playerId: number | null) => void;
  onSetPoolMembership?: (playerId: number, isInPool: boolean) => unknown;
  onSetBalancerStatus?: (playerId: number, balancerStatus: string) => unknown;
  actionsDisabled: boolean;
};

/**
 * Memoized so a keystroke in the pool search only re-renders the rows whose data changed.
 * Each row mounts two Radix roots (context menu + status menu), which is why the list is
 * also virtualized — 200 pooled players would otherwise cost ~500ms per filter change.
 */
const PoolPlayerRow = memo(function PoolPlayerRow({
  player,
  issues,
  registration,
  statusOptions,
  isSelected,
  isBulkSelected,
  onToggleBulkSelection,
  onSelectPlayer,
  onSetPoolMembership,
  onSetBalancerStatus,
  actionsDisabled,
}: PoolPlayerRowProps) {
  const isReady = player.is_in_pool && issues.length === 0;
  const sortedEntries = [...player.role_entries_json].sort((left, right) => left.priority - right.priority);
  const rankedEntries = sortedEntries.filter((entry) => isRoleEntryActive(entry) && entry.rank_value !== null);
  const rankedRoleCodes = rankedEntries
    .map((entry) => entry.role)
    .filter((roleCode, index, all) => all.indexOf(roleCode) === index);
  const primaryEntry = rankedEntries[0] ?? sortedEntries[0] ?? null;
  const divisionNumber = primaryEntry?.division_number ?? null;
  const { name, suffix } = splitBattleTag(player.battle_tag);
  const primaryRole = primaryEntry?.role ?? null;
  const issueSummary = issues.map((issue) => issue.message).join(" | ");
  const battleTags = getRegistrationBattleTags(registration, player.battle_tag);
  const primaryBattleTag = battleTags[0] ?? player.battle_tag;
  const smurfTags = battleTags.slice(1);

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <div
          title={issueSummary || primaryBattleTag}
          className={cn(
            "group grid w-full cursor-pointer grid-cols-[24px_minmax(0,1fr)] items-start gap-2 rounded-lg border px-2.5 py-2 text-left transition-colors",
            "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] hover:border-[color:var(--aqt-border-2)] hover:bg-[color:var(--aqt-overlay-3)]",
            isSelected && "border-primary/45 bg-primary/[0.08]",
            isBulkSelected && !isSelected && "border-cyan-400/35 bg-cyan-500/[0.06]",
          )}
        >
          <button
            type="button"
            data-card-action
            aria-pressed={isBulkSelected}
            aria-label={isBulkSelected ? `Unselect ${player.battle_tag}` : `Select ${player.battle_tag}`}
            onClick={() => onToggleBulkSelection?.(player.id)}
            className={cn(
              "mt-0.5 flex h-6 w-6 items-center justify-center rounded-md border text-label transition-colors",
              isBulkSelected
                ? "border-cyan-300/50 bg-cyan-500/18 text-cyan-100"
                : "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-bg-2)] text-[color:var(--aqt-fg-dim)] hover:text-[color:var(--aqt-fg-muted)]",
            )}
          >
            {isBulkSelected ? <Check className="h-3 w-3" /> : <Circle className="h-2.5 w-2.5 fill-current stroke-none" />}
          </button>

          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <div className="flex min-w-0 flex-1 items-center gap-1.5">
                {rankedRoleCodes.length > 0 ? (
                  <div className="flex items-center gap-1">
                    {rankedRoleCodes.map((roleCode) => (
                      <span key={roleCode} title={ROLE_LABELS[roleCode]} className="opacity-95">
                        <PlayerRoleIcon role={ROLE_LABELS[roleCode]} size={15} />
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-label text-[color:var(--aqt-fg-dim)]">No roles</span>
                )}
                <button
                  type="button"
                  data-card-action
                  onClick={() => onSelectPlayer?.(player.id)}
                  title={`Edit ${primaryBattleTag}`}
                  className="flex min-w-0 items-baseline gap-1 rounded text-left"
                >
                  <span className="truncate text-caption font-medium text-[color:var(--aqt-fg)]">{name}</span>
                  {suffix ? <span className="shrink-0 text-label text-[color:var(--aqt-fg-dim)]">{suffix}</span> : null}
                </button>
              </div>

              <div className="flex shrink-0 items-center gap-1" data-card-action>
                <div className="flex items-center gap-2 pr-1">
                  {divisionNumber != null ? (
                    <span className="shrink-0" title={`Division ${divisionNumber}`}>
                      <DivisionIcon division={divisionNumber} width={20} height={20} />
                    </span>
                  ) : null}
                  {primaryEntry?.rank_value != null ? (
                    <span
                      className={cn(
                        "min-w-10 text-right text-caption font-semibold tabular-nums text-cyan-300",
                        primaryRole && ROLE_TEXT_ACCENTS[primaryRole],
                      )}
                    >
                      {primaryEntry.rank_value}
                    </span>
                  ) : (
                    <span className="text-label text-[color:var(--aqt-fg-dim)]">-</span>
                  )}
                </div>

                <BalancerStatusMenu
                  size="compact"
                  value={registration?.balancer_status}
                  statusOptions={statusOptions}
                  disabled={actionsDisabled}
                  onChange={registration ? (status) => onSetBalancerStatus?.(player.id, status) : undefined}
                />

                <BattleTagCopyButton battleTag={primaryBattleTag} />

                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={actionsDisabled || !onSetPoolMembership}
                  className={cn(
                    "h-7 w-7 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] text-[color:var(--aqt-fg-dim)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]",
                    !player.is_in_pool && "text-emerald-200/70",
                  )}
                  aria-label={
                    player.is_in_pool
                      ? `Exclude ${primaryBattleTag} from the balancer`
                      : `Include ${primaryBattleTag} in the balancer`
                  }
                  title={player.is_in_pool ? "Exclude from balancer" : "Include in balancer"}
                  onClick={() => onSetPoolMembership?.(player.id, !player.is_in_pool)}
                >
                  {player.is_in_pool ? <ShieldX className="h-3.5 w-3.5" /> : <PlusCircle className="h-3.5 w-3.5" />}
                </Button>
              </div>
            </div>

            {player.is_flex || isReady || issues.length > 0 || smurfTags.length > 0 ? (
              <div className="mt-1.5 flex flex-wrap items-center gap-1">
                {player.is_flex ? (
                  <span className="shrink-0 rounded-full border border-violet-300/20 bg-violet-500/12 px-1.5 py-0.5 text-label font-semibold uppercase tracking-label text-violet-200">
                    Flex
                  </span>
                ) : null}
                {isReady ? (
                  <span className="shrink-0 rounded-full border border-emerald-300/20 bg-emerald-500/10 px-1.5 py-0.5 text-label font-semibold uppercase tracking-label text-emerald-200">
                    Ready
                  </span>
                ) : null}
                {issues.map((issue) => (
                  <IssueChip key={`${player.id}-${issueChipKey(issue)}`} issue={issue} />
                ))}
                <SmurfTagStrip smurfTags={smurfTags} />
              </div>
            ) : null}
          </div>
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent className="w-56">
        <ContextMenuLabel>Player actions</ContextMenuLabel>
        <ContextMenuItem onClick={() => onSelectPlayer?.(player.id)}>
          <Pencil className="h-4 w-4" />
          Edit full profile
        </ContextMenuItem>
        <BattleTagContextMenuItems battleTags={battleTags} />
        {onSetPoolMembership ? (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem disabled={actionsDisabled} onClick={() => onSetPoolMembership(player.id, !player.is_in_pool)}>
              {player.is_in_pool ? <ShieldX className="h-4 w-4" /> : <PlusCircle className="h-4 w-4" />}
              {player.is_in_pool ? "Exclude from balancer" : "Include in balancer"}
            </ContextMenuItem>
          </>
        ) : null}
        <BalancerStatusContextMenuItems
          value={registration?.balancer_status}
          statusOptions={statusOptions}
          disabled={actionsDisabled}
          onChange={registration ? (status) => onSetBalancerStatus?.(player.id, status) : undefined}
        />
        {onToggleBulkSelection ? (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem onClick={() => onToggleBulkSelection(player.id)}>
              <Check className="h-4 w-4" />
              {isBulkSelected ? "Remove from selection" : "Add to selection"}
            </ContextMenuItem>
          </>
        ) : null}
      </ContextMenuContent>
    </ContextMenu>
  );
});

export function PoolPlayerCompactList({
  playerStates,
  registrationsById,
  statusOptions,
  selectedPlayerId,
  selectedBulkIds,
  onToggleBulkSelection,
  onSelectPlayer,
  onSetPoolMembership,
  onSetBalancerStatus,
  actionsDisabled = false,
  emptyTitle = "No players match the current filters",
  emptyDescription = "Try another search or change the pool filter.",
}: Readonly<PoolPlayerCompactListProps>) {
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
      <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] px-4 py-8 text-center">
        <div className="space-y-1.5">
          <p className="text-sm font-medium text-[color:var(--aqt-fg)]">{emptyTitle}</p>
          <p className="text-xs text-[color:var(--aqt-fg-dim)]">{emptyDescription}</p>
        </div>
      </div>
    );
  }

  const row = (index: number) => {
    const { player, issues } = playerStates[index];

    return (
      <PoolPlayerRow
        player={player}
        issues={issues}
        registration={registrationsById?.get(player.id) ?? null}
        statusOptions={statusOptions}
        isSelected={player.id === selectedPlayerId}
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
          aria-label="Pool players"
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
        <ul aria-label="Pool players" className="space-y-1.5">
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
