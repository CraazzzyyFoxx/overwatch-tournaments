"use client";

import { ColumnDef } from "@tanstack/react-table";
import {
  CheckCircle,
  CircleOff,
  Eye,
  EyeOff,
  MoreHorizontal,
  Pencil,
  Play,
  TestTube,
  Trash2,
} from "lucide-react";

import { AdminDataTable, adminColumnMeta } from "@/components/data-table";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import adminService from "@/services/admin.service";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import type { AchievementRule } from "@/types/admin.types";

import { countLeafConditions } from "../achievement-form.model";
import { IconLabel, categoryIcon, grainIcon, scopeIcon } from "../achievement-meta";

export interface AchievementsTableActions {
  canUpdate: boolean;
  canDelete: boolean;
  onOpen: (rule: AchievementRule) => void;
  onEdit: (rule: AchievementRule) => void;
  onTest: (rule: AchievementRule) => void;
  onEvaluate: (rule: AchievementRule) => void;
  onToggle: (rule: AchievementRule) => void;
  onDelete: (rule: AchievementRule) => void;
}

/** The paged rule catalog. Every row action is decided by the page, not here. */
export function AchievementsTable({
  workspaceId,
  actions,
}: Readonly<{ workspaceId: number; actions: AchievementsTableActions }>) {
  const listKey = achievementQueryKeys.adminList(workspaceId);

  const columns: ColumnDef<AchievementRule>[] = [
    {
      accessorKey: "id",
      header: "ID",
      size: 60,
      cell: ({ row }) => <span className="tabular-nums">{row.original.id}</span>,
    },
    {
      accessorKey: "enabled",
      header: "Status",
      size: 80,
      meta: adminColumnMeta<AchievementRule>({ align: "center" }),
      cell: ({ row }) =>
        row.original.enabled ? (
          <StatusIcon icon={CheckCircle} label="On" variant="success" />
        ) : (
          <StatusIcon icon={CircleOff} label="Off" variant="muted" />
        ),
    },
    { accessorKey: "slug", header: "Slug", size: 180 },
    { accessorKey: "name", header: "Name" },
    {
      accessorKey: "category",
      header: "Category",
      size: 120,
      cell: ({ row }) => (
        <IconLabel icon={categoryIcon(row.original.category)} label={row.original.category} />
      ),
    },
    {
      accessorKey: "scope",
      header: "Scope",
      size: 120,
      cell: ({ row }) => (
        <IconLabel icon={scopeIcon(row.original.scope)} label={row.original.scope} />
      ),
    },
    {
      accessorKey: "grain",
      header: "Grain",
      size: 140,
      cell: ({ row }) => (
        <IconLabel icon={grainIcon(row.original.grain)} label={row.original.grain.replace("_", " + ")} />
      ),
    },
    {
      accessorKey: "rule_version",
      header: "Ver",
      size: 50,
      cell: ({ row }) => <span className="tabular-nums">{row.original.rule_version}</span>,
    },
    {
      id: "conditions_count",
      header: "Conditions",
      size: 90,
      enableSorting: false,
      accessorFn: (row) => countLeafConditions(row.condition_tree),
      cell: ({ getValue }) => <span className="tabular-nums">{getValue<number>()}</span>,
    },
    {
      id: "actions",
      size: 50,
      cell: ({ row }) => {
        const rule = row.original;
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button aria-label={`Actions for ${rule.slug}`} variant="ghost" size="icon">
                <MoreHorizontal className="h-4 w-4" aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Actions</DropdownMenuLabel>
              <DropdownMenuItem onClick={() => actions.onOpen(rule)}>
                <Eye className="mr-2 h-4 w-4" aria-hidden />
                View details
              </DropdownMenuItem>
              {actions.canUpdate && (
                <DropdownMenuItem onClick={() => actions.onEdit(rule)}>
                  <Pencil className="mr-2 h-4 w-4" aria-hidden />
                  Edit achievement
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onClick={() => actions.onTest(rule)}>
                <TestTube className="mr-2 h-4 w-4" aria-hidden />
                Test (dry run)
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => actions.onEvaluate(rule)}>
                <Play className="mr-2 h-4 w-4" aria-hidden />
                Evaluate this achievement
              </DropdownMenuItem>
              {actions.canUpdate && (
                <DropdownMenuItem onClick={() => actions.onToggle(rule)}>
                  {rule.enabled ? (
                    <><EyeOff className="mr-2 h-4 w-4" aria-hidden />Disable</>
                  ) : (
                    <><Eye className="mr-2 h-4 w-4" aria-hidden />Enable</>
                  )}
                </DropdownMenuItem>
              )}
              {actions.canUpdate && actions.canDelete && <DropdownMenuSeparator />}
              {actions.canDelete && (
                <DropdownMenuItem onClick={() => actions.onDelete(rule)} className="text-destructive">
                  <Trash2 className="mr-2 h-4 w-4" aria-hidden />
                  Delete achievement
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ];

  return (
    <AdminDataTable
      queryKey={(page, search, pageSize, sf, sd) => [...listKey, page, search, pageSize, sf, sd]}
      queryFn={async (page, search, pageSize, sortField, sortDir) =>
        adminService.getAchievementRules(workspaceId, {
          page,
          per_page: pageSize,
          search: search || undefined,
          sort: sortField ?? undefined,
          order: sortDir,
        })
      }
      columns={columns}
      searchPlaceholder="Search achievements…"
      emptyMessage="No achievements found. Use “Seed defaults” to create the standard set, or “Create achievement” to start from scratch."
      onRowClick={(row) => actions.onOpen(row.original)}
    />
  );
}
