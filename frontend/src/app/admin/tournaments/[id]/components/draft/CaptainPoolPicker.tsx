"use client";

import { useMemo, useState } from "react";
import { ArrowDownWideNarrow } from "lucide-react";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Checkbox } from "@/components/ui/checkbox";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { SearchField } from "@/components/ui/search-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { resolveDivisionFromRank } from "@/lib/division-grid";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { DraftRole } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { filterCaptainRows, type DraftCaptainRow, type DraftCaptainSort } from "./setup-model";

interface CaptainPoolPickerProps {
  rows: DraftCaptainRow[];
  selectedIds: number[];
  teamCount: number;
  onToggle: (id: number) => void;
  /** The TOURNAMENT's grid, so a rank resolves to the tier the draft uses. */
  divisionGrid: DivisionGrid;
}

const FILTER_ROLES: DraftRole[] = ["tank", "damage", "support"];
const SORTS: DraftCaptainSort[] = ["rank_desc", "rank_asc", "name"];

/**
 * The captain pool, laid out like the balancer's pool sidebar: one chip row
 * carrying both the filters and their counts, a search field, a sort, then
 * dense rows. Roles are OR-ed multi-select — a captain pool is routinely
 * narrowed to "tank or support", which a single-value dropdown cannot say.
 */
export function CaptainPoolPicker({
  rows,
  selectedIds,
  teamCount,
  onToggle,
  divisionGrid
}: Readonly<CaptainPoolPickerProps>) {
  const t = useTranslations("draftAdmin");
  const [query, setQuery] = useState("");
  const [roles, setRoles] = useState<DraftRole[]>([]);
  const [selectedOnly, setSelectedOnly] = useState(false);
  const [sort, setSort] = useState<DraftCaptainSort>("rank_desc");

  const roleCounts = useMemo(
    () =>
      FILTER_ROLES.map((role) => ({
        role,
        count: rows.filter((row) => row.roles.includes(role)).length
      })),
    [rows]
  );
  const visible = useMemo(
    () => filterCaptainRows(rows, { query, roles, sort, selectedOnly, selectedIds }),
    [query, roles, rows, selectedIds, selectedOnly, sort]
  );

  const full = selectedIds.length >= teamCount;

  return (
    <div className="space-y-3">
      <FilterChipGroup label={t("captainPoolFilters")} className="gap-1.5">
        <FilterChip
          active={roles.length === 0 && !selectedOnly}
          count={rows.length}
          onClick={() => {
            setRoles([]);
            setSelectedOnly(false);
          }}
        >
          {t("captainFilters.all")}
        </FilterChip>
        {roleCounts.map(({ role, count }) => (
          <FilterChip
            key={role}
            active={roles.includes(role)}
            count={count}
            onClick={() =>
              setRoles((current) =>
                current.includes(role)
                  ? current.filter((entry) => entry !== role)
                  : [...current, role]
              )
            }
          >
            <PlayerRoleIcon
              role={getRoleIconName(role)}
              size={14}
              color={roles.includes(role) ? ROLE_ACCENT[role] : "var(--aqt-fg-muted)"}
              decorative
            />
            {t(`roles.${role}`)}
          </FilterChip>
        ))}
        <FilterChip
          active={selectedOnly}
          count={`${selectedIds.length}/${teamCount}`}
          onClick={() => setSelectedOnly((current) => !current)}
        >
          {t("captainFilters.selected")}
        </FilterChip>
      </FilterChipGroup>

      <div className="flex flex-wrap items-center gap-2">
        <SearchField
          value={query}
          onValueChange={setQuery}
          label={t("searchCaptains")}
          placeholder={t("searchCaptains")}
          containerClassName="min-w-52 flex-1"
        />
        <Select value={sort} onValueChange={(next) => setSort(next as DraftCaptainSort)}>
          <SelectTrigger className="w-44" aria-label={t("captainSort")}>
            <ArrowDownWideNarrow className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SORTS.map((entry) => (
              <SelectItem key={entry} value={entry}>
                {t(`captainSorts.${entry}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="max-h-96 divide-y divide-border/60 overflow-auto rounded-xl border border-border/70">
        {visible.map((row) => {
          const selected = selectedIds.includes(row.id);
          const disabled = !selected && full;
          const division = resolveDivisionFromRank(divisionGrid, row.rank);
          return (
            <label
              key={row.id}
              className={cn(
                "flex cursor-pointer items-center gap-3 px-3 py-2 transition-colors",
                selected ? "bg-primary/8" : "hover:bg-muted/50",
                disabled && "cursor-not-allowed opacity-50"
              )}
            >
              <Checkbox
                checked={selected}
                disabled={disabled}
                onCheckedChange={() => onToggle(row.id)}
                aria-label={t("selectCaptain", { name: row.label })}
              />
              <span className="flex shrink-0 items-center gap-1">
                {row.roles.map((role) => (
                  <PlayerRoleIcon
                    key={role}
                    role={getRoleIconName(role)}
                    size={15}
                    color={ROLE_ACCENT[role]}
                    label={t(`roles.${role}`)}
                  />
                ))}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{row.label}</span>
              <span className="inline-flex shrink-0 items-center gap-1.5 font-mono text-xs tabular-nums">
                {division != null && (
                  <DivisionIcon
                    division={division}
                    tournamentGrid={divisionGrid}
                    width={20}
                    height={20}
                  />
                )}
                {/* The rank is the captain's STRONGEST playable role, so the
                    row names which role it came from instead of implying it is
                    the primary one. */}
                <span
                  className="min-w-10 text-right"
                  style={{ color: row.rankRole ? ROLE_ACCENT[row.rankRole] : undefined }}
                  title={
                    row.rankRole
                      ? t("captainRankOnRole", { role: t(`roles.${row.rankRole}`) })
                      : undefined
                  }
                >
                  {row.rank ?? "—"}
                </span>
              </span>
            </label>
          );
        })}
        {visible.length === 0 && (
          <p className="px-4 py-10 text-center text-sm text-muted-foreground">
            {t("noCaptainsFound")}
          </p>
        )}
      </div>
    </div>
  );
}
