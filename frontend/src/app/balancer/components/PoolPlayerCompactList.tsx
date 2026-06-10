"use client";

import { Check, Circle, Pencil, PlusCircle, ShieldX } from "lucide-react";

import PlayerDivisionIcon from "@/components/PlayerDivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { AdminRegistration, BalancerPlayerRecord, BalancerRoleCode, StatusMeta } from "@/types/balancer-admin.types";
import { getRegistrationBattleTags } from "./balancer-page-helpers";
import { BattleTagContextMenuItems, BattleTagCopyButton, SmurfTagStrip } from "./BattleTagCopyControls";
import { IssueChip } from "./IssueChip";
import {
  ROLE_LABELS,
  isRoleEntryActive,
  type PlayerValidationIssue,
} from "@/app/balancer/components/workspace-helpers";

type StatusOptionGroups = {
  system: StatusMeta[];
  custom: StatusMeta[];
};

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
  maxHeightClassName?: string;
  emptyTitle?: string;
  emptyDescription?: string;
};

const ROLE_TEXT_ACCENTS: Record<BalancerRoleCode, string> = {
  tank: "text-sky-300",
  dps: "text-orange-300",
  support: "text-emerald-300",
};

function sortRoleEntries(player: BalancerPlayerRecord) {
  return [...player.role_entries_json].sort((left, right) => left.priority - right.priority);
}

function splitBattleTag(battleTag: string): { name: string; suffix: string | null } {
  const hashIndex = battleTag.indexOf("#");
  if (hashIndex < 0) {
    return { name: battleTag, suffix: null };
  }

  return {
    name: battleTag.slice(0, hashIndex),
    suffix: battleTag.slice(hashIndex),
  };
}

function uniqueRoleCodes(roleCodes: BalancerRoleCode[]): BalancerRoleCode[] {
  return roleCodes.filter((roleCode, index) => roleCodes.indexOf(roleCode) === index);
}

function roleIconTitle(roleCode: BalancerRoleCode): string {
  return ROLE_LABELS[roleCode];
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

function RoleIconStrip({ roleCodes }: { roleCodes: BalancerRoleCode[] }) {
  if (roleCodes.length === 0) {
    return <span className="text-[11px] text-white/28">No roles</span>;
  }

  return (
    <div className="flex items-center gap-1">
      {roleCodes.map((roleCode) => (
        <span key={roleCode} title={roleIconTitle(roleCode)} className="opacity-95">
          <PlayerRoleIcon role={ROLE_LABELS[roleCode]} size={15} />
        </span>
      ))}
    </div>
  );
}

function StatusMenu({
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
          className="h-7 max-w-[110px] justify-start rounded-lg border border-white/8 bg-black/15 px-2 text-[11px] text-white/60 hover:bg-white/5 hover:text-white"
          title={`Balancer status: ${getStatusName(statusOptions, value)}`}
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
  maxHeightClassName = "max-h-[32rem]",
  emptyTitle = "No players match the current filters",
  emptyDescription = "Try another search or change the pool filter.",
}: PoolPlayerCompactListProps) {
  if (playerStates.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center rounded-2xl border border-dashed border-white/10 bg-white/[0.02] px-4 py-8 text-center">
        <div className="space-y-1.5">
          <p className="text-sm font-medium text-white/88">{emptyTitle}</p>
          <p className="text-xs text-white/38">{emptyDescription}</p>
        </div>
      </div>
    );
  }

  return (
    <ScrollArea className={cn("min-h-0", maxHeightClassName)}>
      <div className="space-y-1.5 pr-2">
        {playerStates.map(({ player, issues }) => {
          const isSelected = player.id === selectedPlayerId;
          const isBulkSelected = selectedBulkIds?.has(player.id) ?? false;
          const isReady = player.is_in_pool && issues.length === 0;
          const sortedEntries = sortRoleEntries(player);
          const rankedEntries = sortedEntries.filter((entry) => isRoleEntryActive(entry) && entry.rank_value !== null);
          const rankedRoleCodes = uniqueRoleCodes(rankedEntries.map((entry) => entry.role));
          const primaryEntry = rankedEntries[0] ?? sortedEntries[0] ?? null;
          const divisionNumber = primaryEntry?.division_number ?? null;
          const { name, suffix } = splitBattleTag(player.battle_tag);
          const primaryRole = primaryEntry?.role ?? null;
          const issueSummary = issues.map((issue) => issue.message).join(" | ");
          const registration = registrationsById?.get(player.id) ?? null;
          const battleTags = getRegistrationBattleTags(registration, player.battle_tag);
          const primaryBattleTag = battleTags[0] ?? player.battle_tag;
          const smurfTags = battleTags.slice(1);

          return (
            <ContextMenu key={player.id}>
              <ContextMenuTrigger asChild>
                <div
                  title={issueSummary || primaryBattleTag}
                  onDoubleClick={(event) => {
                    if (isCardActionTarget(event.target)) {
                      return;
                    }
                    onSelectPlayer?.(player.id);
                  }}
                  className={cn(
                    "group grid w-full cursor-pointer grid-cols-[24px_minmax(0,1fr)] items-start gap-2 rounded-xl border px-2.5 py-2 text-left transition-all",
                    "border-white/6 bg-white/[0.02] hover:border-white/12 hover:bg-white/[0.04]",
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
                      "mt-0.5 flex h-5 w-5 items-center justify-center rounded-md border text-[10px] transition",
                      isBulkSelected
                        ? "border-cyan-300/50 bg-cyan-500/18 text-cyan-100"
                        : "border-white/10 bg-black/15 text-white/45 hover:border-white/18 hover:text-white/75",
                    )}
                  >
                    {isBulkSelected ? <Check className="h-3 w-3" /> : <Circle className="h-2.5 w-2.5 fill-current stroke-none" />}
                  </button>

                  <div className="min-w-0" title="Double-click to edit player">
                    <div className="flex items-center gap-2">
                      <div className="flex min-w-0 flex-1 items-center gap-1.5">
                        <RoleIconStrip roleCodes={rankedRoleCodes} />
                        <span className="truncate text-[13px] font-medium text-white/88">{name}</span>
                        {suffix ? <span className="shrink-0 text-[12px] text-white/28">{suffix}</span> : null}
                      </div>

                      <div className="flex shrink-0 items-center gap-1" data-card-action>
                        <div className="flex items-center gap-2 pr-1">
                          {divisionNumber != null ? (
                            <span className="shrink-0" title={`Division ${divisionNumber}`}>
                              <PlayerDivisionIcon division={divisionNumber} width={20} height={20} />
                            </span>
                          ) : null}
                          {primaryEntry?.rank_value != null ? (
                            <span
                              className={cn(
                                "min-w-10 text-right text-[13px] font-semibold tabular-nums text-cyan-300",
                                primaryRole && ROLE_TEXT_ACCENTS[primaryRole],
                              )}
                            >
                              {primaryEntry.rank_value}
                            </span>
                          ) : (
                            <span className="text-[12px] text-white/24">-</span>
                          )}
                        </div>

                        <StatusMenu
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
                            "h-7 w-7 rounded-lg border border-white/8 bg-black/15 text-white/45 hover:bg-white/5 hover:text-white",
                            !player.is_in_pool && "text-emerald-200/70",
                          )}
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
                          <span className="shrink-0 rounded-full border border-violet-300/20 bg-violet-500/12 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-violet-200">
                            Flex
                          </span>
                        ) : null}
                        {isReady ? (
                          <span className="shrink-0 rounded-full border border-emerald-300/20 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-200">
                            Ready
                          </span>
                        ) : null}
                        {issues.map((issue) => (
                          <IssueChip key={`${player.id}-${issue.code}`} issue={issue} />
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
                <StatusContextMenuItems
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
        })}
      </div>
    </ScrollArea>
  );
}
