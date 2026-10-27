"use client";

import { ShieldCheck, X } from "lucide-react";
import { useMemo } from "react";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { resolveDivisionFromRank } from "@/lib/divisions/grid";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import type { RoleOntology } from "@/lib/roster/ontology";
import type { RosterShape } from "@/lib/roster/shape";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import type { DraftRole } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { CaptainPoolPicker } from "./CaptainPoolPicker";
import type { DraftCaptainRow } from "./setup-model";
import type { DraftCaptainSetup } from "./setup-types";
import { captainSeat, poolRegistrationSummary, registrationLabel } from "./setup-types";
import { EmptyNote } from "@/components/kit/EmptyNote";

interface DraftCaptainsStepProps {
  pool: AdminRegistration[];
  teamCount: number;
  value: DraftCaptainSetup;
  onChange: (next: DraftCaptainSetup) => void;
  /** The TOURNAMENT's grid (workspace default as fallback), resolved by the
   *  wizard — never the global OW ladder `useDivisionGrid` alone would give. */
  divisionGrid: DivisionGrid;
  /** The shape the draft seats captains into: which roles have a slot at all. */
  rosterShape: Pick<RosterShape, "slots" | "has_role_slots">;
  /** The owner game's role dictionary: names and glyphs of the roles a captain can be seated on. */
  ontology: RoleOntology | null;
}

export function DraftCaptainsStep({
  pool,
  teamCount,
  value,
  onChange,
  divisionGrid,
  rosterShape,
  ontology
}: Readonly<DraftCaptainsStepProps>) {
  const t = useTranslations("draftAdmin");
  const slotLabel = useSlotLabel(ontology);
  const tAdmin = useTranslations("adminTournament.draft");

  const poolById = useMemo(
    () => new Map(pool.map((registration) => [registration.id, registration])),
    [pool]
  );
  const rows: DraftCaptainRow[] = useMemo(
    () =>
      pool.map((registration) => {
        const seat = captainSeat(registration, value.roles[registration.id], rosterShape);
        return {
          id: registration.id,
          label: registrationLabel(registration),
          roles: poolRegistrationSummary(registration).roles,
          rank: seat.rank,
          rankRole: seat.role
        };
      }),
    [pool, value.roles, rosterShape]
  );
  const rowsById = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows]);

  const setRole = (id: number, role: DraftRole) =>
    onChange({ ...value, roles: { ...value.roles, [id]: role } });

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
      <span className="inline-flex shrink-0 items-center gap-1.5 text-xs tabular-nums text-muted-foreground">
        {division != null && (
          <DivisionIcon
            division={division}
            tournamentGrid={divisionGrid}
            width={size}
            height={size}
          />
        )}
        {rank}
      </span>
    );
  };

  return (
    <div className="@container space-y-5">
      <Card
        role="status"
        className="sticky top-2 z-10 flex items-center justify-between px-4 py-3"
      >
        <span className="text-sm font-medium">{t("captainsSelected")}</span>
        <strong className="tabular-nums">
          {value.ids.length} / {teamCount}
        </strong>
      </Card>

      <div className="grid gap-5 @3xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <CaptainPoolPicker
          rows={rows}
          selectedIds={value.ids}
          teamCount={teamCount}
          onToggle={toggle}
          divisionGrid={divisionGrid}
          ontology={ontology}
        />

        <div className="@container space-y-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-muted-foreground" aria-hidden />
            <h3 className="text-sm font-semibold">{t("selectedTeams")}</h3>
          </div>
          {value.ids.length === 0 ? (
            <EmptyNote className="text-center">{t("selectCaptainsHint")}</EmptyNote>
          ) : (
            <div className="grid gap-2 @lg:grid-cols-2">
              {value.ids.map((id, index) => {
                const row = rowsById.get(id);
                const registration = poolById.get(id);
                if (!row || !registration) return null;
                const seat = captainSeat(registration, value.roles[id], rosterShape);
                return (
                  <Card key={id} className="min-w-0 p-3">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-medium tabular-nums">
                        {index + 1}. {row.label}
                      </span>
                      {/* The role the captain fills on their own roster, beside the
                          rank it produces. A choice only when there is one: a
                          role-less shape seats nobody on a role, and a one-role
                          captain has nothing to pick. */}
                      {seat.options.length > 1 ? (
                        <Select
                          value={seat.role ?? undefined}
                          onValueChange={(role) => setRole(id, role as DraftRole)}
                        >
                          <SelectTrigger
                            size="sm"
                            className="h-7 w-auto shrink-0 gap-1 px-1.5"
                            aria-label={t("captainRoleFor", { name: row.label })}
                            title={seat.role ? slotLabel(seat.role) : undefined}
                          >
                            <SelectValue>
                              {seat.role && (
                                <PlayerRoleIcon role={seat.role} ontology={ontology} size={14} decorative />
                              )}
                            </SelectValue>
                          </SelectTrigger>
                          <SelectContent>
                            {seat.options.map((role) => (
                              <SelectItem key={role} value={role}>
                                <span className="inline-flex items-center gap-2">
                                  <PlayerRoleIcon role={role} ontology={ontology} size={14} decorative />
                                  {slotLabel(role)}
                                  <span className="text-xs tabular-nums text-muted-foreground">
                                    {captainSeat(registration, role, rosterShape).rank}
                                  </span>
                                </span>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        <span className="flex shrink-0 items-center gap-1">
                          {(seat.role ? [seat.role] : row.roles).map((role) => (
                            <PlayerRoleIcon key={role} role={role} ontology={ontology} size={14} label={slotLabel(role)} />
                          ))}
                        </span>
                      )}
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
                    <Input
                      id={`team-name-${id}`}
                      size="sm"
                      className="mt-2"
                      placeholder={t("teamName")}
                      aria-label={tAdmin("teamNameFor", { label: row.label, teamName: t("teamName") })}
                      value={value.teamNames[id] ?? ""}
                      onChange={(event) =>
                        onChange({
                          ...value,
                          teamNames: { ...value.teamNames, [id]: event.target.value }
                        })
                      }
                    />
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
