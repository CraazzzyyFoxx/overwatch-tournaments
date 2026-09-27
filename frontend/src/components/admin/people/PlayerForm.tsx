"use client";

import { useMemo, useState } from "react";

import { Combobox, ComboboxCheck } from "@/components/kit/Combobox";
import { TeamCombobox } from "@/components/admin/TeamCombobox";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Checkbox } from "@/components/ui/checkbox";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { resolveDivisionFromRank } from "@/lib/divisions/grid";
import {
  PLAYER_ROLE_OPTIONS,
  filterSubRoleOptions,
  normalizePlayerRole,
  subRoleCatalogRole,
  type PlayerRoleOption
} from "@/lib/roster/player-role";
import type { PlayerCreateInput, PlayerSubRole, PlayerUpdateInput } from "@/types/admin.types";
import type { Team } from "@/types/team.types";
import type { DivisionGridVersion } from "@/types/workspace.types";
import { formatSubRoleLabel } from "@/lib/player";

/** Shown on the sub-role field for a role the sub-role catalog has no rows for. */
const NO_SUB_ROLE_CATALOG_PLACEHOLDER = "No sub-roles for this role";

export type PlayerFormMode = "create" | "edit";

export interface PlayerFormState {
  name: string;
  user_id: number;
  team_id: number;
  tournament_id: number;
  role: string;
  sub_role: string;
  rank: number;
  is_newcomer: boolean;
  is_substitution: boolean;
}

/** A participation the form can be opened on — the subset the fields read. */
export interface PlayerFormSubject {
  name: string;
  role: string | null;
  sub_role: string | null;
  rank: number;
  is_newcomer: boolean;
  is_substitution: boolean;
}

export function emptyPlayerForm(userId: number, tournamentId: number | null): PlayerFormState {
  return {
    name: "",
    user_id: userId,
    team_id: 0,
    tournament_id: tournamentId ?? 0,
    role: "Damage",
    sub_role: "",
    rank: 0,
    is_newcomer: false,
    is_substitution: false
  };
}

export function playerFormOf(subject: PlayerFormSubject, userId: number): PlayerFormState {
  return {
    ...emptyPlayerForm(userId, null),
    name: subject.name,
    role: normalizePlayerRole(subject.role),
    sub_role: subject.sub_role ?? "",
    rank: subject.rank,
    is_newcomer: subject.is_newcomer,
    is_substitution: subject.is_substitution
  };
}

/**
 * Sub-role fragment of a player payload. A role with no sub-role catalog (Flex)
 * sends an explicit `null`, because omitting the key would leave an already
 * stored sub-role in place on a role that cannot have one.
 */
function buildSubRolePayload(
  role: PlayerRoleOption,
  subRole: string
): { sub_role?: string | null } {
  if (subRoleCatalogRole(role) == null) return { sub_role: null };
  return subRole ? { sub_role: subRole } : {};
}

export function playerCreatePayload(state: PlayerFormState): PlayerCreateInput {
  const role = normalizePlayerRole(state.role);
  return {
    name: state.name.trim(),
    user_id: state.user_id,
    team_id: state.team_id,
    tournament_id: state.tournament_id,
    role,
    rank: state.rank,
    is_newcomer: state.is_newcomer,
    is_substitution: state.is_substitution,
    ...buildSubRolePayload(role, state.sub_role)
  };
}

export function playerUpdatePayload(state: PlayerFormState): PlayerUpdateInput {
  const role = normalizePlayerRole(state.role);
  return {
    name: state.name.trim(),
    role,
    rank: state.rank,
    is_newcomer: state.is_newcomer,
    is_substitution: state.is_substitution,
    ...buildSubRolePayload(role, state.sub_role)
  };
}

/** The first thing wrong with the form, or `undefined` when it can be sent. */
export function playerFormError(state: PlayerFormState, mode: PlayerFormMode): string | undefined {
  if (!state.name.trim()) return "Enter a player name before saving.";
  if (mode === "edit") return undefined;
  if (state.tournament_id <= 0) return "Pick the tournament this participation belongs to.";
  if (state.team_id <= 0) return "Select a team before saving.";
  return undefined;
}

interface PlayerOption {
  value: string;
  label: string;
  meta?: string;
}

function RoleOptionContent({ role }: Readonly<{ role: PlayerRoleOption }>) {
  return (
    <div className="flex items-center gap-2">
      <PlayerRoleIcon role={role} size={18} decorative />
      <span>{role}</span>
    </div>
  );
}

function SearchableSelect({
  id,
  value,
  options,
  onChange,
  placeholder,
  searchPlaceholder,
  emptyMessage,
  disabled = false
}: Readonly<{
  id?: string;
  value: string;
  options: PlayerOption[];
  onChange: (value: string) => void;
  placeholder: string;
  searchPlaceholder: string;
  emptyMessage: string;
  disabled?: boolean;
}>) {
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const selected = options.find((option) => option.value === value);

  return (
    <Combobox
      id={id}
      open={open}
      onOpenChange={setOpen}
      label={selected?.label ?? placeholder}
      disabled={disabled}
      searchValue={searchValue}
      onSearchValueChange={setSearchValue}
      searchPlaceholder={searchPlaceholder}
      emptyMessage={emptyMessage}
    >
      <CommandGroup>
        {options.map((option) => (
          <CommandItem
            key={option.value}
            value={`${option.label} ${option.meta ?? ""} ${option.value}`}
            onSelect={() => {
              onChange(option.value);
              setOpen(false);
              setSearchValue("");
            }}
          >
            <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
              <span className="truncate">{option.label}</span>
              {option.meta ? (
                <span className="shrink-0 text-xs text-muted-foreground">{option.meta}</span>
              ) : null}
            </div>
            <ComboboxCheck selected={value === option.value} />
          </CommandItem>
        ))}
      </CommandGroup>
    </Combobox>
  );
}

/**
 * Division is derived from rank by the division grid, so the form renders it
 * read-only as the grid icon instead of an editable number the API discards.
 */
function DivisionField({
  rank,
  grid
}: Readonly<{ rank: number; grid: DivisionGridVersion | null }>) {
  const workspaceGrid = useDivisionGrid();
  const division = resolveDivisionFromRank(grid ?? workspaceGrid, rank);

  return (
    <div>
      <Label>Division</Label>
      <div className="flex h-9 items-center">
        {division == null ? (
          <span className="text-sm text-muted-foreground">—</span>
        ) : (
          <DivisionIcon division={division} tournamentGrid={grid} width={28} height={28} />
        )}
      </div>
    </div>
  );
}

export interface PlayerFormProps {
  mode: PlayerFormMode;
  value: PlayerFormState;
  onChange: (next: PlayerFormState) => void;
  /** Sub-role catalog of the workspace owning the participation's tournament. */
  subRoles: PlayerSubRole[] | undefined;
  /** Grid the division icon resolves against; `null` falls back to the workspace's. */
  divisionGrid: DivisionGridVersion | null;
  /** Create mode only: the tournaments a participation can be added to. */
  tournaments?: { id: number; name: string }[];
  /** Create mode only: teams of the tournament currently picked. */
  teams?: Team[];
}

/**
 * The one player (participation) form.
 *
 * Was two near-identical dialog bodies inside the old `/admin/players` screen;
 * `mode` is the whole difference — creating one also has to say which
 * tournament and team it joins, editing one cannot move it.
 */
export function PlayerForm({
  mode,
  value,
  onChange,
  subRoles,
  divisionGrid,
  tournaments = [],
  teams = []
}: Readonly<PlayerFormProps>) {
  const prefix = mode === "edit" ? "player-edit" : "player-create";
  const role = normalizePlayerRole(value.role);
  // Flex has no sub-role catalog, so its sub-role field is inert rather than a
  // dropdown holding a single unusable "No sub-role" row.
  const hasSubRoleCatalog = subRoleCatalogRole(role) != null;
  const subRoleOptions = filterSubRoleOptions(subRoles, role);
  const hasCurrentSubRoleOption = subRoleOptions.some(
    (subRole) => subRole.slug === value.sub_role
  );

  const subRoleSelectOptions = useMemo(() => {
    if (!hasSubRoleCatalog) return [];

    const options: PlayerOption[] = [
      { value: "none", label: "No sub-role" },
      ...subRoleOptions.map((subRole) => ({
        value: subRole.slug,
        label: subRole.label,
        meta: subRole.slug
      }))
    ];

    if (value.sub_role && !hasCurrentSubRoleOption) {
      options.push({
        value: value.sub_role,
        label: formatSubRoleLabel(value.sub_role) ?? value.sub_role,
        meta: "current"
      });
    }

    return options;
  }, [value.sub_role, hasCurrentSubRoleOption, hasSubRoleCatalog, subRoleOptions]);

  return (
    <div className="space-y-4">
      {mode === "create" ? (
        <>
          <div>
            <Label htmlFor={`${prefix}-tournament`}>Tournament *</Label>
            <Select
              value={value.tournament_id ? String(value.tournament_id) : ""}
              onValueChange={(next) =>
                onChange({ ...value, tournament_id: Number(next), team_id: 0 })
              }
            >
              <SelectTrigger id={`${prefix}-tournament`}>
                <SelectValue placeholder="Select tournament" />
              </SelectTrigger>
              <SelectContent>
                {tournaments.map((tournament) => (
                  <SelectItem key={tournament.id} value={String(tournament.id)}>
                    {tournament.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label htmlFor={`${prefix}-team`}>Team *</Label>
            <TeamCombobox
              id={`${prefix}-team`}
              teams={teams}
              value={value.team_id || null}
              placeholder={value.tournament_id ? "Search and select team" : "Pick a tournament first"}
              searchPlaceholder="Search team…"
              disabled={!value.tournament_id}
              onSelect={(team) => onChange({ ...value, team_id: team?.id ?? 0 })}
            />
          </div>
        </>
      ) : null}

      <div>
        <Label htmlFor={`${prefix}-name`}>Player name *</Label>
        <Input
          id={`${prefix}-name`}
          value={value.name}
          onChange={(event) => onChange({ ...value, name: event.target.value })}
          required
        />
      </div>

      <div>
        <Label htmlFor={`${prefix}-role`}>Role</Label>
        {/* Picking a role clears sub_role: a sub-role only exists for its own role. */}
        <Select
          value={role}
          onValueChange={(next) => onChange({ ...value, role: next, sub_role: "" })}
        >
          <SelectTrigger id={`${prefix}-role`}>
            <RoleOptionContent role={role} />
          </SelectTrigger>
          <SelectContent>
            {PLAYER_ROLE_OPTIONS.map((option) => (
              <SelectItem key={option} value={option}>
                <RoleOptionContent role={option} />
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label htmlFor={`${prefix}-sub-role`}>Sub-role</Label>
        <SearchableSelect
          id={`${prefix}-sub-role`}
          value={value.sub_role || "none"}
          options={subRoleSelectOptions}
          disabled={!hasSubRoleCatalog}
          placeholder={hasSubRoleCatalog ? "Select sub-role" : NO_SUB_ROLE_CATALOG_PLACEHOLDER}
          searchPlaceholder="Search sub-role…"
          emptyMessage="No sub-roles match that search."
          onChange={(next) => onChange({ ...value, sub_role: next === "none" ? "" : next })}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label htmlFor={`${prefix}-rank`}>Rank</Label>
          <NumberInput
            id={`${prefix}-rank`}
            integer
            min={0}
            value={value.rank}
            onValueChange={(rank) => onChange({ ...value, rank: rank ?? 0 })}
          />
        </div>

        <DivisionField rank={value.rank} grid={divisionGrid} />
      </div>

      <div className="space-y-2">
        <div className="flex items-center space-x-2">
          <Checkbox
            id={`${prefix}-newcomer`}
            checked={value.is_newcomer}
            onCheckedChange={(checked) => onChange({ ...value, is_newcomer: checked === true })}
          />
          <Label htmlFor={`${prefix}-newcomer`} className="cursor-pointer">
            Newcomer
          </Label>
        </div>

        <div className="flex items-center space-x-2">
          <Checkbox
            id={`${prefix}-substitution`}
            checked={value.is_substitution}
            onCheckedChange={(checked) => onChange({ ...value, is_substitution: checked === true })}
          />
          <Label htmlFor={`${prefix}-substitution`} className="cursor-pointer">
            Substitution
          </Label>
        </div>
      </div>
    </div>
  );
}
