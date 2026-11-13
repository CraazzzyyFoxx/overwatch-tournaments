"use client";

import { useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useTranslations } from "next-intl";

import {
  auditDiffRows,
  auditSourceLabel,
  describeAuditAction,
  formatAuditActor,
  formatAuditTarget,
  formatAuditTimestamp,
  isMachineActor,
  useAuditTranslator
} from "@/components/kit/audit-log";
import type { FilterState } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { AuditLogRead } from "@/types/admin.types";

/**
 * The feed's columns. Takes the two filter writers rather than reading them off
 * `filters` in the memo: that object is rebuilt every render, the writers are
 * not, so the columns depend on the callbacks themselves.
 */
export function useAuditColumns({
  set: setFilter,
  setMany: setFilters
}: Readonly<Pick<FilterState, "set" | "setMany">>): ColumnDef<AuditLogRead>[] {
  const t = useTranslations("adminMatches.audit");
  const tk = useTranslations("kitAudit.audit");
  const auditT = useAuditTranslator();
  const format = useFormatter();

  return useMemo<ColumnDef<AuditLogRead>[]>(
    () => [
      {
        accessorKey: "created_at",
        header: t("when"),
        size: 180,
        cell: ({ row }) => (
          <time
            dateTime={row.original.created_at}
            className="whitespace-nowrap text-sm tabular-nums text-muted-foreground"
          >
            {formatAuditTimestamp(format, row.original.created_at)}
          </time>
        ),
      },
      {
        accessorKey: "action",
        header: t("action"),
        cell: ({ row }) => {
          const described = describeAuditAction(row.original.action, auditT);
          return (
            <div className="flex min-w-0 flex-wrap items-baseline gap-1.5">
              <span
                className="text-sm font-medium"
                title={described.recognised ? undefined : described.raw}
              >
                {described.label}
              </span>
              {described.recognised ? null : (
                // Never let a phrase we derived from the raw string pass for a
                // curated one: `action` is written from every service on the
                // platform, so this dictionary will always trail new call sites.
                <span className="text-caption text-muted-foreground" title={described.raw}>
                  {tk("unrecognised")}
                </span>
              )}
            </div>
          );
        },
      },
      {
        accessorKey: "actor_label",
        header: t("actor"),
        cell: ({ row }) => (
          <div className="min-w-0">
            {/* A machine actor is a fact, not a missing name (FR3), so it reads
                as one instead of as an em dash. */}
            <p
              className={cn(
                "truncate text-sm",
                isMachineActor(row.original) ? "italic text-muted-foreground" : "font-medium",
              )}
            >
              {formatAuditActor(row.original, auditT)}
            </p>
            {row.original.actor_auth_user_id != null ? (
              <Button
                variant="link"
                size="sm"
                className="h-auto p-0"
                onClick={() => setFilter("actor_user_id", String(row.original.actor_auth_user_id))}
              >
                {t("onlyActor")}
              </Button>
            ) : null}
          </div>
        ),
      },
      {
        accessorKey: "entity_type",
        header: t("target"),
        cell: ({ row }) => {
          const target = formatAuditTarget(row.original, auditT);
          if (!target) return null;
          return (
            <div className="min-w-0">
              <p className="truncate text-sm" title={target}>
                {target}
              </p>
              {row.original.entity_type && row.original.entity_id != null ? (
                <Button
                  variant="link"
                  size="sm"
                  className="h-auto p-0"
                  // The type and the id are one filter in two params, so they go
                  // in one write: `set` twice would start from the same URL
                  // snapshot and only the second would survive.
                  onClick={() =>
                    setFilters({
                      entity_type: row.original.entity_type ?? null,
                      entity_id: String(row.original.entity_id),
                    })
                  }
                >
                  {t("onlyRecord")}
                </Button>
              ) : null}
            </div>
          );
        },
      },
      {
        accessorKey: "source",
        header: t("source"),
        size: 132,
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-sm text-muted-foreground">
            {auditSourceLabel(row.original.source, auditT)}
          </span>
        ),
      },
      {
        id: "changes",
        header: t("changes"),
        enableSorting: false,
        cell: ({ row }) => {
          const rows = auditDiffRows(row.original.before_json, row.original.after_json, auditT);
          if (rows.length === 0) {
            return row.original.reason ? (
              <span className="text-xs text-muted-foreground">{t("reasonOnly")}</span>
            ) : null;
          }
          const named = rows.slice(0, 3).map((diff) => diff.field);
          return (
            <span
              className="text-xs text-muted-foreground"
              title={rows.map((diff) => diff.field).join(", ")}
            >
              <span className="font-mono">{named.join(", ")}</span>
              {rows.length > named.length ? ` ${t("moreFields", { count: rows.length - named.length })}` : ""}
            </span>
          );
        },
      },
    ],
    [format, setFilter, setFilters, t, tk, auditT],
  );
}
