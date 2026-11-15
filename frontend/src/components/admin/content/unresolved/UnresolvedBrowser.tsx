"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useFormatter } from "@/lib/datetime/client";

import { DataTable } from "@craazzzyyfoxx/admin-kit/data-table";
import { FilterBar } from "@craazzzyyfoxx/admin-kit/kit/FilterBar";
import { useFilters } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import { usePermissions } from "@/hooks/usePermissions";
import { catalogQueryKeys } from "@/lib/catalog/query-keys";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { CatalogAliasMissKind, CatalogAliasMissRead } from "@/types/admin.types";
import { MISS_QUEUE_KEY } from "@/app/admin/content/miss-queue";

import { unresolvedFilterDefs } from "./filters";
import { attachableKind, formatMissOrigin, formatSeenAt } from "./model";
import { MissTarget } from "./UnresolvedCells";
import { useUnresolvedColumns } from "./useUnresolvedColumns";

/**
 * The triage queue of log names the parser could not resolve (F13).
 *
 * Not a fourth catalogue: it edits nothing itself, it decides which catalogue
 * entity an unrecognised string meant. That decision is the screen's whole
 * job, so it stays inline — pick a target, press Attach — instead of moving
 * into a dialog the way an entity edit would.
 */
export function UnresolvedBrowser() {
  const t = useTranslations("adminWorkspace.content");
  const format = useFormatter();
  const queryClient = useQueryClient();
  const { isSuperuser } = usePermissions();
  // Target entity per miss row. Dynamic, per-row keys that come and go with the
  // queue, so a Map rather than an object literal.
  const [targets, setTargets] = useState<Map<number, number>>(new Map());

  const filterDefs = useMemo(() => unresolvedFilterDefs(t), [t]);
  const filters = useFilters(filterDefs);
  const kindFilter = String(filters.values.type ?? "") as CatalogAliasMissKind | "";
  const includeResolved = filters.values.resolved === true;

  // Also refreshes the tab badge: it hangs off the same key root.
  const invalidateQueue = () => {
    queryClient.invalidateQueries({ queryKey: MISS_QUEUE_KEY });
  };

  const pickTarget = useCallback((missId: number, entityId: number | undefined) => {
    setTargets((previous) => {
      const updated = new Map(previous);
      if (entityId === undefined) {
        updated.delete(missId);
      } else {
        updated.set(missId, entityId);
      }
      return updated;
    });
  }, []);

  const attachMutation = useMutation({
    mutationFn: ({ miss, entityId }: { miss: CatalogAliasMissRead; entityId: number }) =>
      adminService.attachCatalogAlias({
        entity_id: entityId,
        alias: miss.raw_name,
      }),
    onSuccess: (_result, { miss }) => {
      const kind = attachableKind(miss);
      notify.success(t("catalog.attached", { name: miss.raw_name, entity: t(`catalog.kinds.${miss.kind}`).toLowerCase() }));
      invalidateQueue();
      if (kind !== null) {
        // The alias now lives on the entity, so every cached read of that game's kind (public and admin) is stale.
        // The miss's own discipline and kind, captured with the submit, never the page's current view.
        queryClient.invalidateQueries({ queryKey: catalogQueryKeys.kind({ discipline: miss.discipline }, kind) });
      }
      pickTarget(miss.id, undefined);
    },
    onError: (error) => notify.apiError(error, { title: t("catalog.attachError") }),
  });

  const dismissMutation = useMutation({
    mutationFn: (miss: CatalogAliasMissRead) => adminService.dismissCatalogAliasMiss(miss.id),
    onSuccess: (_result, miss) => {
      notify.success(t("catalog.hidden", { name: miss.raw_name }));
      invalidateQueue();
      pickTarget(miss.id, undefined);
    },
    onError: (error) => notify.apiError(error, { title: t("catalog.hideError") }),
  });

  const attachingId = attachMutation.isPending ? attachMutation.variables?.miss.id : undefined;
  const dismissingId = dismissMutation.isPending ? dismissMutation.variables?.id : undefined;

  const columns = useUnresolvedColumns({
    isSuperuser,
    targets,
    attachingId,
    dismissingId,
    onPickTarget: pickTarget,
    onAttach: attachMutation.mutate,
    onDismiss: dismissMutation.mutate,
  });

  return (
    <DataTable
      filterKey={filters.filterKey}
      queryKey={(page, search, pageSize) => [
        ...MISS_QUEUE_KEY,
        kindFilter,
        includeResolved,
        page,
        search,
        pageSize,
      ]}
      queryFn={async (page, search, pageSize) => {
        const response = await adminService.getCatalogAliasMisses({
          page,
          per_page: pageSize,
          kind: kindFilter || undefined,
          include_resolved: includeResolved,
        });
        if (!search) {
          return response;
        }
        // ponytail: `misses_list` takes no search term, so the box narrows the
        // page in hand. Enough for a queue that lives in the dozens; lift by
        // adding `search` to the RPC once it grows past one page.
        const needle = search.toLowerCase();
        const results = response.results.filter((miss) =>
          miss.raw_name.toLowerCase().includes(needle)
        );
        return { ...response, results, total: results.length };
      }}
      columns={columns}
      searchPlaceholder={t("catalog.search")}
      toolbar={<FilterBar defs={filterDefs} filters={filters} />}
      emptyMessage={
        includeResolved
          ? t("catalog.noResolved")
          : t("catalog.nothing")
      }
      renderMobileCard={(row) => (
        <div className="min-w-0 flex-1 space-y-1.5">
          <p className="truncate font-medium">{row.original.raw_name}</p>
          <p className="truncate text-xs text-muted-foreground">
            {t("catalog.mobileSummary", {
              entity: formatMissOrigin(t, row.original),
              count: row.original.occurrences,
              date: formatSeenAt(format, row.original.last_seen_at),
            })}
          </p>
          <MissTarget
            miss={row.original}
            canTriage={isSuperuser}
            value={targets.get(row.original.id)}
            onChange={(entityId) => pickTarget(row.original.id, entityId)}
            disabled={row.original.id === attachingId || row.original.id === dismissingId}
          />
        </div>
      )}
    />
  );
}
