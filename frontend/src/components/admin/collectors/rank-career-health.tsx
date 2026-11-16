"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { DataTable, columnMeta } from "@craazzzyyfoxx/admin-kit/data-table";

import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { StatTileGridSkeleton } from "@/components/admin/StatTileGridSkeleton";
import { StatusPill } from "@/components/kit/StatusPill";
import { PageStateCard } from "@/components/ui/page-state-card";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { ApiError } from "@/lib/api/error";
import { useFormatter } from "@/lib/datetime/client";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { CareerProblem } from "@/types/admin.types";

import { formatRelative } from "./rank-shared";

const percent = (part: number, whole: number) => (whole ? Math.round((part / whole) * 100) : 0);

/**
 * How much of the players' Blizzard careers the collector sees, and the tags an
 * organizer has to fix. Sits under the health tiles; a game whose collector does
 * not serve the read (404) simply has no block rather than a broken page.
 */
export function RankCareerHealth({ discipline }: Readonly<{ discipline: string }>) {
  const t = useTranslations("collectors.rank.career");
  const format = useFormatter();
  // Scoped to the workspace `apiFetch` injects, so it belongs in the key.
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const query = useQuery({
    queryKey: adminQueryKeys.rankCareerHealth(workspaceId, discipline),
    queryFn: () => adminService.getCareerHealth(discipline),
    // A 404 is the answer ("this game has no such read"), not a blip to retry.
    retry: false
  });
  const data = query.data;

  const columns = useMemo<ColumnDef<CareerProblem>[]>(
    () => [
      {
        accessorKey: "kind",
        header: t("table.kind"),
        enableSorting: false,
        cell: ({ row }) => {
          const kind = row.original.kind;
          const key = `kind.${kind}` as "kind.lost";
          return (
            <StatusPill tone={kind === "lost" ? "warning" : "accent"}>
              {t.has(key) ? t(key) : kind}
            </StatusPill>
          );
        }
      },
      {
        accessorKey: "user_name",
        header: t("table.player"),
        meta: columnMeta<CareerProblem>({ searchValue: (row) => `${row.user_name} ${row.handle}` }),
        cell: ({ row }) => (
          <Link
            href={`/admin/people/${row.original.user_id}`}
            className="font-medium text-primary underline-offset-2 hover:underline"
          >
            {row.original.user_name}
          </Link>
        )
      },
      {
        accessorKey: "handle",
        header: t("table.handle"),
        cell: ({ row }) => <span className="font-mono text-xs">{row.original.handle}</span>
      },
      {
        accessorKey: "display_name",
        header: t("table.displayName"),
        cell: ({ row }) => row.original.display_name ?? <span className="text-muted-foreground">—</span>
      },
      {
        accessorKey: "last_success_at",
        header: t("table.lastFound"),
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-xs text-muted-foreground">
            {formatRelative(format, row.original.last_success_at) || "—"}
          </span>
        )
      }
    ],
    [format, t]
  );

  if (query.isError && query.error instanceof ApiError && query.error.status === 404) return null;

  let body;
  if (data) {
    const flagged = data.lost + data.renamed;
    body = (
      <>
        <StatTileGrid className="xl:grid-cols-5">
          <StatTile
            label={t("tiles.playersFound")}
            value={`${percent(data.players_found, data.players)}%`}
            detail={`${format.number(data.players_found)} / ${format.number(data.players)}`}
          />
          <StatTile
            label={t("tiles.playersPublic")}
            value={`${percent(data.players_public, data.players)}%`}
            detail={`${format.number(data.players_public)} / ${format.number(data.players)}`}
          />
          <StatTile
            label={t("tiles.notFound")}
            value={format.number(data.accounts_not_found)}
            detail={t("tiles.notFoundDetail", { total: data.accounts })}
          />
          <StatTile
            label={t("tiles.lost")}
            value={format.number(data.lost)}
            detail={t("tiles.lostDetail")}
            tone={data.lost > 0 ? "warning" : "neutral"}
          />
          <StatTile label={t("tiles.renamed")} value={format.number(data.renamed)} />
        </StatTileGrid>

        <div className="space-y-2">
          <h3 id="rank-career-problems" className="text-sm font-semibold">
            {t("table.title")}
          </h3>
          <DataTable<CareerProblem>
            rows={data.problems}
            columns={columns}
            initialPageSize={20}
            pageSizeOptions={[20, 50, 100, 200]}
            searchPlaceholder={t("table.search")}
            getRowId={(row) => String(row.social_account_id)}
            emptyMessage={t("table.empty")}
          />
          {flagged > data.problems.length ? (
            <p className="text-xs text-muted-foreground">
              {t("table.truncated", { count: data.problems.length, total: flagged })}
            </p>
          ) : null}
        </div>
      </>
    );
  } else if (query.isError) {
    body = <PageStateCard state="error" headingLevel={2} onAction={() => query.refetch()} />;
  } else {
    body = <StatTileGridSkeleton />;
  }

  return (
    <section aria-labelledby="rank-career-health" className="space-y-3 pt-2">
      <h2 id="rank-career-health" className="font-semibold leading-none">
        {t("title")}
      </h2>
      {body}
    </section>
  );
}
