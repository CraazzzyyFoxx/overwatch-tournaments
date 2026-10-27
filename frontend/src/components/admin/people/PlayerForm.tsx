"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { Combobox, ComboboxCheck, ComboboxMeta } from "@/components/ui/combobox";
import { TeamCombobox } from "@/components/admin/TeamCombobox";
import DivisionIcon from "@/components/DivisionIcon";
import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
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
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { resolveDivisionFromRank } from "@/lib/divisions/grid";
import { ratedDimension, roleChoices, subRoleOptions, type RoleOntology } from "@/lib/roster/ontology";
import { OPEN_SLOT_CODE } from "@/lib/roster/shape";
import type { PlayerCreateInput, PlayerSubRole, PlayerUpdateInput } from "@/types/admin.types";
import type { Team } from "@/types/team.types";
import type { DivisionGridVersion } from "@/types/workspace.types";
import { formatSubRoleLabel } from "@/lib/player";
import { roleOf, subRoleOf, toRoleRef, type RoleRef } from "@/lib/roster/role-ref";

export type PlayerFormMode = "create" | "edit";

export interface PlayerFormState {
  name: string;
  user_id: number;
  team_id: number;
  tournament_id: number;
  /** A role code of the owner game's rated dimension, or `OPEN_SLOT_CODE` for none assigned. */
  role: string;
  sub_role: string;
  /** `null` = no rank (cleared field); otherwise >= 1. */
  rank: number | null;
  is_newcomer: boolean;
  is_substitution: boolean;
}

/** A participation the form can be opened on — the subset the fields read. */
export interface PlayerFormSubject {
  name: string;
  role: RoleRef | null;
  rank: number | null;
  is_newcomer: boolean;
  is_substitution: boolean;
}

export function emptyPlayerForm(userId: number, tournamentId: number | null): PlayerFormState {
  return {
    name: "",
    user_id: userId,
    team_id: 0,
    tournament_id: tournamentId ?? 0,
    role: OPEN_SLOT_CODE,
    sub_role: "",
    rank: null,
    is_newcomer: false,
    is_substitution: false
  };
}

export function playerFormOf(subject: PlayerFormSubject, userId: number): PlayerFormState {
  return {
    ...emptyPlayerForm(userId, null),
    name: subject.name,
    role: subject.role ? roleOf(subject.role) : OPEN_SLOT_CODE,
    sub_role: subRoleOf(subject.role) ?? "",
    rank: subject.rank,
    is_newcomer: subject.is_newcomer,
    is_substitution: subject.is_substitution
  };
}

/** What the form writes as the role: nothing for the open slot, else the role (or its sub-role leaf) of the owner's rated dimension. */
function roleRefOf(state: PlayerFormState, dimension: string): RoleRef | null {
  return toRoleRef(state.role === OPEN_SLOT_CODE ? null : state.role, state.sub_role, dimension);
}

export function playerCreatePayload(state: PlayerFormState, dimension: string): PlayerCreateInput {
  return {
    name: state.name.trim(),
    user_id: state.user_id,
    team_id: state.team_id,
    tournament_id: state.tournament_id,
    role: roleRefOf(state, dimension),
    rank: state.rank,
    is_newcomer: state.is_newcomer,
    is_substitution: state.is_substitution
  };
}

export function playerUpdatePayload(state: PlayerFormState, dimension: string): PlayerUpdateInput {
  return {
    name: state.name.trim(),
    role: roleRefOf(state, dimension),
    rank: state.rank,
    is_newcomer: state.is_newcomer,
    is_substitution: state.is_substitution
  };
}

/** The first thing wrong with the form, or `undefined` when it can be sent. */
export type PlayerFormErrorKey = "nameRequiredBeforeSave" | "tournamentRequired" | "teamRequired";

export function playerFormError(state: PlayerFormState, mode: PlayerFormMode): PlayerFormErrorKey | undefined {
  if (!state.name.trim()) return "nameRequiredBeforeSave";
  if (mode === "edit") return undefined;
  if (state.tournament_id <= 0) return "tournamentRequired";
  if (state.team_id <= 0) return "teamRequired";
  return undefined;
}

interface PlayerOption {
  value: string;
  label: string;
  meta?: string;
}

function RoleOptionContent({
  code,
  label,
  ontology
}: Readonly<{ code: string; label: string; ontology: RoleOntology | null }>) {
  return (
    <div className="flex items-center gap-2">
      <RosterSlotGlyph code={code} ontology={ontology} size={18} decorative />
      <span>{label}</span>
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
      label={selected?.label}
      placeholder={placeholder}
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
              {option.meta ? <ComboboxMeta>{option.meta}</ComboboxMeta> : null}
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
}: Readonly<{ rank: number | null; grid: DivisionGridVersion | null }>) {
  const t = useTranslations("adminPeople.form");
  const workspaceGrid = useDivisionGrid();
  const division = resolveDivisionFromRank(grid ?? workspaceGrid, rank);

  return (
    <div>
      <Label>{t("division")}</Label>
      <div className="flex h-9 items-center">
        {division == null ? null : (
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
  /** The participation's tournament's own game: its roles are the only ones offered. `null` while it loads. */
  ontology: RoleOntology | null;
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
  ontology,
  divisionGrid,
  tournaments = [],
  teams = []
}: Readonly<PlayerFormProps>) {
  const t = useTranslations("adminPeople.form");
  const prefix = mode === "edit" ? "player-edit" : "player-create";
  const slotLabel = useSlotLabel(ontology);
  const dimension = (ontology ? ratedDimension(ontology) : null)?.code;
  const role = value.role;
  // The open slot has no sub-role catalog, so its sub-role field is inert rather than a
  // dropdown holding a single unusable "No sub-role" row.
  const hasSubRoleCatalog = role !== OPEN_SLOT_CODE;

  const subRoleSelectOptions = useMemo(() => {
    if (role === OPEN_SLOT_CODE) return [];

    const choices = subRoleOptions(subRoles, dimension, role);
    const options: PlayerOption[] = [
      { value: "none", label: t("noSubRole") },
      ...choices.map((choice) => ({ value: choice.slug, label: choice.label, meta: choice.slug.slice(role.length + 1) }))
    ];

    if (value.sub_role && !choices.some((choice) => choice.slug === value.sub_role)) {
      options.push({
        value: value.sub_role,
        label: formatSubRoleLabel(value.sub_role) ?? value.sub_role,
        meta: "current"
      });
    }

    return options;
  }, [t, value.sub_role, subRoles, dimension, role]);

  return (
    <div className="space-y-4">
      {mode === "create" ? (
        <>
          <div>
            <Label htmlFor={`${prefix}-tournament`}>{t("tournament")}</Label>
            <Select
              value={value.tournament_id ? String(value.tournament_id) : ""}
              onValueChange={(next) =>
                onChange({ ...value, tournament_id: Number(next), team_id: 0 })
              }
            >
              <SelectTrigger id={`${prefix}-tournament`}>
                <SelectValue placeholder={t("selectTournament")} />
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
            <Label htmlFor={`${prefix}-team`}>{t("team")}</Label>
            <TeamCombobox
              id={`${prefix}-team`}
              teams={teams}
              value={value.team_id || null}
              placeholder={value.tournament_id ? t("searchAndSelectTeam") : t("pickTournament")}
              searchPlaceholder={t("searchTeam")}
              disabled={!value.tournament_id}
              onSelect={(team) => onChange({ ...value, team_id: team?.id ?? 0 })}
            />
          </div>
        </>
      ) : null}

      <div>
        <Label htmlFor={`${prefix}-name`}>{t("playerName")}</Label>
        <Input
          id={`${prefix}-name`}
          value={value.name}
          onChange={(event) => onChange({ ...value, name: event.target.value })}
          required
        />
      </div>

      <div>
        <Label htmlFor={`${prefix}-role`}>{t("role")}</Label>
        {/* Picking a role clears sub_role: a sub-role only exists for its own role. */}
        <Select
          value={role}
          disabled={!dimension}
          onValueChange={(next) => onChange({ ...value, role: next, sub_role: "" })}
        >
          <SelectTrigger id={`${prefix}-role`}>
            <RoleOptionContent code={role} label={slotLabel(role)} ontology={ontology} />
          </SelectTrigger>
          <SelectContent>
            {roleChoices(ontology, role).map((option) => (
              <SelectItem key={option} value={option}>
                <RoleOptionContent code={option} label={slotLabel(option)} ontology={ontology} />
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label htmlFor={`${prefix}-sub-role`}>{t("subRole")}</Label>
        <SearchableSelect
          id={`${prefix}-sub-role`}
          value={value.sub_role || "none"}
          options={subRoleSelectOptions}
          disabled={!hasSubRoleCatalog}
          placeholder={hasSubRoleCatalog ? t("selectSubRole") : t("noSubRoleCatalog")}
          searchPlaceholder={t("searchSubRole")}
          emptyMessage={t("noSubRoleMatch")}
          onChange={(next) => onChange({ ...value, sub_role: next === "none" ? "" : next })}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label htmlFor={`${prefix}-rank`}>{t("rank")}</Label>
          <NumberInput
            id={`${prefix}-rank`}
            integer
            min={1}
            value={value.rank}
            onValueChange={(rank) => onChange({ ...value, rank })}
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
            {t("newcomer")}
          </Label>
        </div>

        <div className="flex items-center space-x-2">
          <Checkbox
            id={`${prefix}-substitution`}
            checked={value.is_substitution}
            onCheckedChange={(checked) => onChange({ ...value, is_substitution: checked === true })}
          />
          <Label htmlFor={`${prefix}-substitution`} className="cursor-pointer">
            {t("substitution")}
          </Label>
        </div>
      </div>
    </div>
  );
}
