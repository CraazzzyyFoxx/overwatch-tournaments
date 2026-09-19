"use client";

import { ArrowDownWideNarrow, Search, ShieldCheck, UserRoundCheck, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { TONE_CLASS } from "@/components/kit/tone";
import { resolveDivisionFromRank } from "@/lib/division-grid";
import { getRoleIconName, ROLE_ACCENT } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { DraftRole } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { filterCaptainRows, type DraftCaptainSort } from "./setup-model";
import type { DraftCaptainSetup } from "./setup-types";
import { poolRegistrationSummary, registrationLabel } from "./setup-types";
import { EmptyNote } from "@/components/kit/EmptyNote";

interface DraftCaptainsStepProps {
  pool: AdminRegistration[];
  teamCount: number;
  value: DraftCaptainSetup;
  onChange: (next: DraftCaptainSetup) => void;
  /** The TOURNAMENT's grid (workspace default as fallback), resolved by the
   *  wizard — never the global OW ladder `useDivisionGrid` alone would give. */
  divisionGrid: DivisionGrid;
}

const FILTER_ROLES: DraftRole[] = ["tank", "damage", "support"];
const SORTS: DraftCaptainSort[] = ["rank_desc", "rank_asc", "name"];

export function DraftCaptainsStep({
  pool,
  teamCount,
  value,
  onChange,
  divisionGrid
}: Readonly<DraftCaptainsStepProps>) {
  const t = useTranslations("draftAdmin");
  const [search, setSearch] = useState("");
  const [roles, setRoles] = useState<DraftRole[]>([]);
  const [sort, setSort] = useState<DraftCaptainSort>("rank_desc");

  const rows = useMemo(
    () =>
      pool.map((registration) => {
        const summary = poolRegistrationSummary(registration);
        return {
          id: registration.id,
          label: registrationLabel(registration),
          roles: summary.roles,
          rank: summary.rank
        };
      }),
    [pool]
  );
  const visible = useMemo(
    () => filterCaptainRows(rows, { query: search, roles, sort }),
    [roles, rows, search, sort]
  );
  const rowsById = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows]);

  const toggle = (id: number) => {
    const selected = value.ids.includes(id);
    if (!selected && value.ids.length >= teamCount) return;
    onChange({
      ...value,
      ids: selected ? value.ids.filter((candidate) => candidate !== id) : [...value.ids, id]
    });
  };

  const renderRank = (rank: number | null, size: number) => {
    const division = resolveDivisionFromRank(divisionGrid, rank);
    return (
      <span className="inline-flex shrink-0 items-center gap-1.5 font-mono text-xs tabular-nums text-muted-foreground">
        {division != null && (
          <DivisionIcon
            division={division}
            tournamentGrid={divisionGrid}
            width={size}
            height={size}
          />
        )}
        {rank ?? "—"}
      </span>
    );
  };

  return (
    <div className="space-y-5">
      <div
        role="status"
        className={cn(
          "sticky top-2 z-10 flex items-center justify-between rounded-xl border px-4 py-3 shadow-sm backdrop-blur",
          TONE_CLASS[value.ids.length === teamCount ? "success" : "warning"]
        )}
      >
        <div className="flex items-center gap-3">
          <UserRoundCheck className="h-5 w-5" aria-hidden />
          <span className="text-sm font-medium">{t("captainsSelected")}</span>
        </div>
        <strong className="tabular-nums">
          {value.ids.length} / {teamCount}
        </strong>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.65fr)]">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-52 flex-1">
              <Search
                className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground"
                aria-hidden
              />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={t("searchCaptains")}
                aria-label={t("searchCaptains")}
                className="pl-9"
              />
            </div>
            {/* Multi-select toggles rather than a single-value dropdown: a captain
                pool is usually filtered to "tank or support", which a select
                cannot express. No role checked means every role. */}
            <div
              className="inline-flex h-9 items-center gap-0.5 rounded-md border border-border/70 bg-card p-0.5"
              role="group"
              aria-label={t("roleFilter")}
            >
              {FILTER_ROLES.map((role) => {
                const active = roles.includes(role);
                return (
                  <button
                    key={role}
                    type="button"
                    aria-pressed={active}
                    title={t(`roles.${role}`)}
                    onClick={() =>
                      setRoles((current) =>
                        current.includes(role)
                          ? current.filter((entry) => entry !== role)
                          : [...current, role]
                      )
                    }
                    className={cn(
                      "inline-flex h-8 w-9 items-center justify-center rounded-[5px] transition-colors",
                      active ? "bg-primary/15 ring-1 ring-primary/40" : "hover:bg-muted/60"
                    )}
                  >
                    <PlayerRoleIcon
                      role={getRoleIconName(role)}
                      size={18}
                      color={active ? ROLE_ACCENT[role] : "var(--aqt-fg-muted)"}
                      decorative
                    />
                    <span className="sr-only">{t(`roles.${role}`)}</span>
                  </button>
                );
              })}
            </div>
            <Select value={sort} onValueChange={(next) => setSort(next as DraftCaptainSort)}>
              <SelectTrigger className="w-44" aria-label={t("captainSort")}>
                <ArrowDownWideNarrow
                  className="h-4 w-4 shrink-0 text-muted-foreground"
                  aria-hidden
                />
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
              const selected = value.ids.includes(row.id);
              const disabled = !selected && value.ids.length >= teamCount;
              return (
                <label
                  key={row.id}
                  className={cn(
                    "flex cursor-pointer items-center gap-3 px-4 py-2.5 transition-colors",
                    selected ? "bg-primary/8" : "hover:bg-muted/50",
                    disabled && "cursor-not-allowed opacity-50"
                  )}
                >
                  <Checkbox
                    checked={selected}
                    disabled={disabled}
                    onCheckedChange={() => toggle(row.id)}
                    aria-label={t("selectCaptain", { name: row.label })}
                  />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{row.label}</span>
                  <span className="flex shrink-0 items-center gap-1.5">
                    {row.roles.map((role) => (
                      <PlayerRoleIcon
                        key={role}
                        role={getRoleIconName(role)}
                        size={16}
                        color={ROLE_ACCENT[role]}
                        label={t(`roles.${role}`)}
                      />
                    ))}
                  </span>
                  {renderRank(row.rank, 22)}
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

        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-muted-foreground" aria-hidden />
            <h3 className="text-sm font-semibold">{t("selectedTeams")}</h3>
          </div>
          {value.ids.length === 0 ? (
            <EmptyNote className="text-center">{t("selectCaptainsHint")}</EmptyNote>
          ) : (
            <div className="space-y-2">
              {value.ids.map((id, index) => {
                const row = rowsById.get(id);
                if (!row) return null;
                return (
                  <div key={id} className="rounded-xl border border-border/70 bg-card p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-medium tabular-nums">
                        {index + 1}. {row.label}
                      </span>
                      {renderRank(row.rank, 20)}
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7 shrink-0"
                        onClick={() => toggle(id)}
                        aria-label={t("removeCaptain", { name: row.label })}
                      >
                        <X className="h-4 w-4" aria-hidden />
                      </Button>
                    </div>
                    <div className="mt-1 flex items-center gap-1.5">
                      {row.roles.map((role) => (
                        <PlayerRoleIcon
                          key={role}
                          role={getRoleIconName(role)}
                          size={14}
                          color={ROLE_ACCENT[role]}
                          label={t(`roles.${role}`)}
                        />
                      ))}
                    </div>
                    <Input
                      id={`team-name-${id}`}
                      className="mt-2 h-8"
                      placeholder={t("teamName")}
                      aria-label={`${row.label} · ${t("teamName")}`}
                      value={value.teamNames[id] ?? ""}
                      onChange={(event) =>
                        onChange({
                          ...value,
                          teamNames: { ...value.teamNames, [id]: event.target.value }
                        })
                      }
                    />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
