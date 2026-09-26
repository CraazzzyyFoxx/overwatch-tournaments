"use client";

import { useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Ban, FolderInput, Pencil, RotateCcw, Unlock, UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";

import { adminColumnMeta, createKebabColumn, type KebabAction } from "@/components/data-table";
import { StatusPill } from "@/components/kit/StatusPill";
import { Badge } from "@/components/ui/badge";
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
 * The organizer's row vocabulary: name, lifecycle, admission, captain, roster
 * counts and — the reason the screen exists — the shortfall, as a column rather
 * than a badge.
 */
export function useRegistrationTeamColumns({
  canManageTeams,
  canExport,
  handlers
}: Readonly<{
  canManageTeams: boolean;
  canExport: boolean;
  /** Stable identity required: the kebab column closes over it, so a fresh
   *  object per render would rebuild every column. */
  handlers: TeamRowHandlers;
}>): ColumnDef<RegistrationTeam>[] {
  const t = useTranslations("registrationTeams");
  const tSlot = useTranslations("rosterShape.slotCodes");

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
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <span className="break-words font-medium">{row.original.name}</span>
              {row.original.roster_locked_at && (
                <Badge variant="outline">{t("lock.locked")}</Badge>
              )}
            </div>
            {row.original.rejection_reason && (
              <p className="break-words text-caption text-danger">
                {row.original.rejection_reason}
              </p>
            )}
          </div>
        ),
        meta: adminColumnMeta<RegistrationTeam>({
          mandatory: true,
          className: "min-w-[11rem]",
          // The two things an organizer knows a team by.
          searchValue: (team) => {
            const captain = captainOf(team);
            return `${team.name} ${captain ? memberName(captain) : ""} ${captain?.battle_tag ?? ""}`;
          }
        })
      },
      {
        id: "state",
        accessorFn: (team) => getRegistrationTeamStatus(team),
        header: t("admin.columns.state"),
        cell: ({ row }) => {
          const status = getRegistrationTeamStatus(row.original);
          return (
            <StatusPill tone={TEAM_STATUS_TONE[status] ?? "neutral"}>
              {t(`status.${status}`)}
            </StatusPill>
          );
        },
        meta: adminColumnMeta<RegistrationTeam>({ category: "core" })
      },
      {
        id: "admission",
        accessorFn: (team) => team.admission ?? "pending",
        header: t("admin.columns.admission"),
        cell: ({ row }) => {
          const admission = row.original.admission ?? "pending";
          return (
            <StatusPill tone={ADMISSION_TONE[admission] ?? "neutral"}>
              {t(`admission.${admission}`)}
            </StatusPill>
          );
        },
        meta: adminColumnMeta<RegistrationTeam>({ category: "core" })
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
          if (!captain) return <span className="text-muted-foreground">—</span>;
          const name = memberName(captain);
          return (
            <div className="min-w-0">
              <p className="break-words">{name}</p>
              {captain.battle_tag && captain.battle_tag !== name ? (
                <p className="break-words text-caption text-muted-foreground">
                  {captain.battle_tag}
                </p>
              ) : null}
            </div>
          );
        },
        meta: adminColumnMeta<RegistrationTeam>({ category: "core" })
      },
      {
        id: "roster",
        accessorFn: (team) => rosterCounts(team).starters,
        header: t("admin.columns.roster"),
        cell: ({ row }) => {
          const { starters, required } = rosterCounts(row.original);
          return (
            <span className="text-caption text-muted-foreground">
              {t("admin.rosterSummary", {
                starters,
                required,
                bench: row.original.substitutes_used,
                maxBench: row.original.max_substitutes
              })}
            </span>
          );
        },
        meta: adminColumnMeta<RegistrationTeam>({ category: "core", className: "min-w-[9rem]" })
      },
      {
        // The reason the screen exists, so it is a column and not a badge.
        id: "shortfall",
        accessorFn: (team) => Object.keys(team.open_slots).length,
        header: t("admin.columns.shortfall"),
        cell: ({ row }) => {
          const team = row.original;
          const issues = team.eligibility_issues?.length ?? 0;
          const short = team.status === "forming" && team.exported_team_id == null;
          if (!short && issues === 0) return <span className="text-muted-foreground">—</span>;
          return (
            <div className="space-y-0.5 text-caption text-warning">
              {short && <p>{t("list.shortfall", { slots: formatShortfall(team.open_slots, tSlot) })}</p>}
              {issues > 0 && <p>{t("admin.problemCount", { count: issues })}</p>}
            </div>
          );
        },
        meta: adminColumnMeta<RegistrationTeam>({ category: "core", className: "min-w-[10rem]" })
      },
      createKebabColumn<RegistrationTeam>(rowActions, { rowLabel: (team) => team.name })
    ];
  }, [canExport, canManageTeams, handlers, t, tSlot]);
}
