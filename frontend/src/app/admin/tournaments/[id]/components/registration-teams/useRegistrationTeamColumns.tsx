"use client";

import { useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Ban, FolderInput, Lock, Pencil, RotateCcw, Unlock, UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";

import { columnMeta, createKebabColumn, type KebabAction } from "@craazzzyyfoxx/admin-kit/data-table";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { notesCountColumn } from "@/components/registration/notesCountColumn";
import { PersonLabel } from "@/components/PlayerName";
import { StatusPill } from "@/components/kit/StatusPill";
import { formatShortfall } from "@/lib/registration/team-shortfall";
import { getRegistrationTeamStatus } from "@/lib/registration/team-tone";
import type { RegistrationTeam } from "@/types/registration-team.types";

import {
  ADMISSION_TONE,
  TEAM_STATUS_TONE,
  captainOf,
  isExportEligible,
  isTeamLive,
  memberName,
  rosterCounts
} from "./model";

/** What the row's kebab can start. Every one of them opens a dialog rather than
 *  writing: they all reach into a team the organizer does not own. */
export interface TeamRowHandlers {
  onRename: (team: RegistrationTeam) => void;
  onPlace: (team: RegistrationTeam) => void;
  onUnlock: (team: RegistrationTeam) => void;
  onResetCap: (team: RegistrationTeam) => void;
  onReExport: (team: RegistrationTeam) => void;
  onReject: (team: RegistrationTeam) => void;
}

/**
 * The organizer's row vocabulary: name, the one status worth attention,
 * captain, and the roster with — the reason the screen exists — what it is
 * still short of.
 */
export function useRegistrationTeamColumns({
  canManageTeams,
  canExport,
  slotLabel,
  handlers,
  noteCounts
}: Readonly<{
  canManageTeams: boolean;
  canExport: boolean;
  /** Names a slot in the tournament's own game. */
  slotLabel: (code: string) => string;
  /** Stable identity required: the kebab column closes over it, so a fresh
   *  object per render would rebuild every column. */
  handlers: TeamRowHandlers;
  /** Organizer notes per team id (as a string key); absent while loading. */
  noteCounts?: Record<string, number>;
}>): ColumnDef<RegistrationTeam>[] {
  const t = useTranslations("registrationTeams");
  const tNotes = useTranslations("registrationNotes");

  return useMemo<ColumnDef<RegistrationTeam>[]>(() => {
    const rowActions = (team: RegistrationTeam): KebabAction[] => {
      const editable = canManageTeams && team.exported_team_id == null && isTeamLive(team);
      return [
        {
          label: t("rename.save"),
          icon: Pencil,
          hidden: !editable,
          onSelect: () => handlers.onRename(team)
        },
        {
          label: t("admin.place"),
          icon: UserPlus,
          hidden: !editable,
          onSelect: () => handlers.onPlace(team)
        },
        {
          label: t("admin.unlock"),
          icon: Unlock,
          hidden: !editable || !team.roster_locked_at,
          onSelect: () => handlers.onUnlock(team)
        },
        {
          label: t("admin.resetCap"),
          icon: RotateCcw,
          hidden: !editable,
          onSelect: () => handlers.onResetCap(team)
        },
        {
          label: t("admin.reExport"),
          icon: FolderInput,
          hidden: !canExport || team.exported_team_id == null || !isExportEligible(team),
          onSelect: () => handlers.onReExport(team)
        },
        {
          label: t("admin.reject"),
          icon: Ban,
          destructive: true,
          hidden: !editable,
          onSelect: () => handlers.onReject(team)
        }
      ];
    };

    return [
      {
        id: "name",
        accessorFn: (team) => team.name,
        header: t("admin.columns.team"),
        cell: ({ row }) => (
          <div className="min-w-0 space-y-0.5">
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="break-words font-medium">{row.original.name}</span>
              {row.original.roster_locked_at && (
                <StatusIcon icon={Lock} label={t("lock.locked")} variant="muted" className="size-3.5" />
              )}
            </div>
            {row.original.rejection_reason && (
              <p className="break-words text-caption text-danger">
                {row.original.rejection_reason}
              </p>
            )}
          </div>
        ),
        meta: columnMeta<RegistrationTeam>({
          mandatory: true,
          className: "min-w-[11rem]",
          // The two things an organizer knows a team by.
          searchValue: (team) => {
            const captain = captainOf(team);
            return `${team.name} ${captain ? memberName(captain) : ""} ${captain?.primary_handle ?? ""} ${captain?.display.canonical ?? ""}`;
          }
        })
      },
      {
        // One status per row: the lifecycle when it wants attention (forming,
        // rejected, disbanded), else the admission when it does (pending,
        // waitlisted). A complete, accepted or exported team shows nothing.
        id: "state",
        accessorFn: (team) => getRegistrationTeamStatus(team),
        header: t("admin.columns.state"),
        cell: ({ row }) => {
          const status = getRegistrationTeamStatus(row.original);
          const statusTone = TEAM_STATUS_TONE[status];
          if (statusTone) return <StatusPill tone={statusTone}>{t(`status.${status}`)}</StatusPill>;
          const admission = row.original.admission ?? "pending";
          const admissionTone = ADMISSION_TONE[admission];
          if (!admissionTone) return null;
          return <StatusPill tone={admissionTone}>{t(`admission.${admission}`)}</StatusPill>;
        },
        meta: columnMeta<RegistrationTeam>({ category: "core" })
      },
      {
        id: "captain",
        accessorFn: (team) => {
          const captain = captainOf(team);
          return captain ? memberName(captain) : "";
        },
        header: t("admin.columns.captain"),
        cell: ({ row }) => {
          const captain = captainOf(row.original);
          if (!captain) return null;
          const { display } = captain;
          const shown = display.name + (display.tag ?? "");
          return (
            <div className="min-w-0">
              <PersonLabel display={display} showCanonical className="block break-words" />
              {captain.primary_handle && captain.primary_handle !== shown ? (
                <p className="break-words text-caption text-muted-foreground">
                  {captain.primary_handle}
                </p>
              ) : null}
            </div>
          );
        },
        meta: columnMeta<RegistrationTeam>({ category: "core" })
      },
      {
        // Counts and shortfall in one cell: both answer "how complete is it".
        id: "roster",
        accessorFn: (team) => rosterCounts(team).starters,
        header: t("admin.columns.roster"),
        cell: ({ row }) => {
          const team = row.original;
          const { starters, required } = rosterCounts(team);
          const issues = team.eligibility_issues?.length ?? 0;
          const short = team.status === "forming" && team.exported_team_id == null;
          return (
            <div className="space-y-0.5 text-caption">
              <p className="tabular-nums text-muted-foreground">
                {t("admin.rosterSummary", {
                  starters,
                  required,
                  bench: team.substitutes_used,
                  maxBench: team.max_substitutes
                })}
              </p>
              {short && (
                <p className="text-warning">
                  {t("list.shortfall", { slots: formatShortfall(team.open_slots, slotLabel) })}
                </p>
              )}
              {issues > 0 && <p className="text-warning">{t("admin.problemCount", { count: issues })}</p>}
            </div>
          );
        },
        meta: columnMeta<RegistrationTeam>({ category: "core", className: "min-w-[10rem]" })
      },
      notesCountColumn<RegistrationTeam>({
        header: tNotes("column"),
        count: (team) => noteCounts?.[String(team.id)] ?? 0,
        label: (count) => tNotes("count", { count })
      }),
      createKebabColumn<RegistrationTeam>(rowActions, { rowLabel: (team) => team.name })
    ];
  }, [canExport, canManageTeams, handlers, slotLabel, t, tNotes, noteCounts]);
}
