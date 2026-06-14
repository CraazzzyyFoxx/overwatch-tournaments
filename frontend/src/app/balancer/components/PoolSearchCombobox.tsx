"use client";

import { Plus, Search, SlidersHorizontal, UserCheck } from "lucide-react";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { BalancerApplication, BalancerPlayerRecord, BalancerRoleCode } from "@/types/balancer-admin.types";
import {
  ROLE_LABELS,
  buildApplicationSearchIndex,
  buildPlayerSearchIndex,
  isRoleEntryActive,
  type PlayerValidationIssue,
} from "@/app/balancer/components/workspace-helpers";

const MAX_RESULTS_PER_GROUP = 6;

const SORT_OPTIONS = [
  { value: "added_desc", label: "Newest in pool" },
  { value: "added_asc", label: "Oldest in pool" },
  { value: "name_asc", label: "Name A-Z" },
  { value: "division_asc", label: "Highest division first" },
  { value: "division_desc", label: "Lowest division first" },
] as const;

type PoolSearchComboboxProps = {
  playerStates: Array<{
    player: BalancerPlayerRecord;
    issues: PlayerValidationIssue[];
  }>;
  applications: BalancerApplication[];
  value: string;
  onValueChange: (value: string) => void;
  sortValue: string;
  onSortValueChange: (value: string) => void;
  showFilters: boolean;
  onShowFiltersChange: (open: boolean) => void;
  onSelectPlayer: (playerId: number) => void;
  onAddFromApplication: (application: BalancerApplication) => void;
  disabled?: boolean;
  suggestionsMode?: "default" | "applications";
};

function uniqueRoleCodes(roleCodes: BalancerRoleCode[]): BalancerRoleCode[] {
  return roleCodes.filter((roleCode, index) => roleCodes.indexOf(roleCode) === index);
}

function normalizeApplicationRole(role: string | null | undefined): BalancerRoleCode | null {
  const normalized = role?.trim().toLowerCase();

  if (!normalized) {
    return null;
  }

  if (normalized === "tank") {
    return "tank";
  }

  if (normalized === "dps" || normalized === "damage") {
    return "dps";
  }

  if (normalized === "support") {
    return "support";
  }

  return null;
}

function getApplicationRoleCodes(application: BalancerApplication): BalancerRoleCode[] {
  return uniqueRoleCodes(
    [application.primary_role, ...application.additional_roles_json]
      .map((role) => normalizeApplicationRole(role))
      .filter((roleCode): roleCode is BalancerRoleCode => roleCode !== null),
  );
}

function getPlayerRoleCodes(player: BalancerPlayerRecord): BalancerRoleCode[] {
  return uniqueRoleCodes(
    [...player.role_entries_json]
      .sort((left, right) => left.priority - right.priority)
      .filter((entry) => isRoleEntryActive(entry) && entry.rank_value !== null)
      .map((entry) => entry.role),
  );
}

function RoleIconRow({ roleCodes }: { roleCodes: BalancerRoleCode[] }) {
  if (roleCodes.length === 0) {
    return <span className="text-xs text-muted-foreground">No roles</span>;
  }

  return (
    <div className="flex items-center gap-1">
      {roleCodes.map((roleCode) => (
        <span
          key={roleCode}
          className="flex h-6 w-6 items-center justify-center rounded-full border border-border/60 bg-background/90"
          title={ROLE_LABELS[roleCode]}
        >
          <PlayerRoleIcon role={ROLE_LABELS[roleCode]} size={14} />
        </span>
      ))}
      <span className="sr-only">{roleCodes.map((roleCode) => ROLE_LABELS[roleCode]).join(", ")}</span>
    </div>
  );
}

export function PoolSearchCombobox({
  playerStates,
  applications,
  value,
  onValueChange,
  sortValue,
  onSortValueChange,
  showFilters,
  onShowFiltersChange,
  onSelectPlayer,
  onAddFromApplication,
  disabled = false,
  suggestionsMode = "default",
}: PoolSearchComboboxProps) {
  const normalizedQuery = value.trim().toLowerCase();
  const applicationsById = new Map(applications.map((application) => [application.id, application]));
  const addableApplications = applications.filter((application) => application.is_active && application.player === null);

  const matchingPoolPlayers = normalizedQuery
    ? playerStates
        .filter(({ player }) =>
          buildPlayerSearchIndex(player, applicationsById.get(player.application_id) ?? null).includes(normalizedQuery),
        )
        .slice(0, MAX_RESULTS_PER_GROUP)
    : [];

  const matchingApplications = normalizedQuery
    ? addableApplications
        .filter((application) => buildApplicationSearchIndex(application).includes(normalizedQuery))
        .slice(0, MAX_RESULTS_PER_GROUP)
    : [];

  const shouldShowSuggestions = !disabled && normalizedQuery.length > 0;
  const totalSuggestionCount = matchingPoolPlayers.length + matchingApplications.length;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={value}
            onChange={(event) => onValueChange(event.target.value)}
            placeholder="Search registrations"
            aria-label="Search registrations"
            autoComplete="off"
            disabled={disabled}
            className="h-10 rounded-xl border-border/70 pl-9"
          />
        </div>

        <Button
          type="button"
          size="icon"
          variant={showFilters ? "secondary" : "outline"}
          aria-label={showFilters ? "Hide pool filters" : "Show pool filters"}
          aria-pressed={showFilters}
          onClick={() => onShowFiltersChange(!showFilters)}
        >
          <SlidersHorizontal className="h-4 w-4" />
        </Button>
      </div>

      {showFilters ? (
        <div className="space-y-1.5">
          <Label htmlFor="player-pool-sort" className="text-[11px] text-muted-foreground">Sort</Label>
          <Select value={sortValue} onValueChange={onSortValueChange}>
            <SelectTrigger id="player-pool-sort" className="h-8 w-full rounded-lg border-border/70 bg-background text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORT_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}

      {shouldShowSuggestions ? (
        <div className="relative z-10">
        <div className="absolute inset-x-0 top-0 overflow-hidden rounded-xl border border-border/70 bg-background/98 shadow-lg backdrop-blur">
          <div className="flex items-center justify-between border-b border-border/60 px-3 py-2 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
            <span>Quick results</span>
            <span>{totalSuggestionCount} results</span>
          </div>

          <ScrollArea className="max-h-72">
            <div className="space-y-4 p-2">
              {matchingPoolPlayers.length > 0 ? (
                <div className="space-y-1">
                  <p className="px-2 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">Players</p>
                  {matchingPoolPlayers.map(({ player, issues }) => {
                    const roleCodes = getPlayerRoleCodes(player);
                    const isValid = issues.length === 0;

                    return (
                      <button
                        key={`pool-${player.id}`}
                        type="button"
                        onClick={() => {
                          onSelectPlayer(player.id);
                          onValueChange("");
                        }}
                        className="flex w-full items-center gap-3 rounded-xl border border-transparent px-2.5 py-2 text-left transition-colors hover:border-primary/20 hover:bg-muted/35"
                      >
                        <UserCheck className={cn("h-4 w-4 shrink-0", isValid ? "text-emerald-600" : "text-amber-600")} />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="truncate text-sm font-medium text-foreground">{player.battle_tag}</span>
                            {!player.is_in_pool ? (
                              <Badge variant="outline" className="h-5 rounded-full px-2 text-[10px] uppercase tracking-[0.12em]">
                                Excluded
                              </Badge>
                            ) : null}
                            {player.is_flex ? (
                              <Badge variant="secondary" className="h-5 rounded-full px-2 text-[10px] uppercase tracking-[0.12em]">
                                Flex
                              </Badge>
                            ) : null}
                          </div>
                          <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                            <RoleIconRow roleCodes={roleCodes} />
                          </div>
                        </div>
                        <Badge
                          variant="outline"
                          className={cn(
                            "rounded-full px-2 text-[10px] uppercase tracking-[0.12em]",
                            isValid
                              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                              : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-200",
                          )}
                        >
                          {isValid ? "Ready" : "Need Fix"}
                        </Badge>
                      </button>
                    );
                  })}
                </div>
              ) : null}

              {matchingApplications.length > 0 ? (
                <div className="space-y-1">
                  <p className="px-2 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">Include</p>
                  {matchingApplications.map((application) => {
                    const roleCodes = getApplicationRoleCodes(application);

                    return (
                      <button
                        key={`app-${application.id}`}
                        type="button"
                        disabled={disabled}
                        onClick={() => {
                          onAddFromApplication(application);
                          onValueChange("");
                        }}
                        className="flex w-full items-center gap-3 rounded-xl border border-transparent px-2.5 py-2 text-left transition-colors hover:border-primary/20 hover:bg-muted/35 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <Plus className="h-4 w-4 shrink-0 text-primary" />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium text-foreground">{application.battle_tag}</div>
                          <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                            <RoleIconRow roleCodes={roleCodes} />
                          </div>
                        </div>
                        <span className="text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                          Include
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : null}

              {totalSuggestionCount === 0 ? (
                <div className="px-2 py-6 text-center text-sm text-muted-foreground">
                  No registrations match &quot;{value.trim()}&quot;.
                </div>
              ) : null}
            </div>
          </ScrollArea>
        </div>
        </div>
      ) : null}
    </div>
  );
}
