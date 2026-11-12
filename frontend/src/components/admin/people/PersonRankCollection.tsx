"use client";

import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { StatusBadge } from "@/components/admin/collectors/rank-shared";
import { EmptyNote, LoadErrorNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { SettingGroup } from "@/components/kit/SettingRow";
import { formatDate, formatRelative } from "@/components/kit/format-time";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * «Сбор рангов»: the person's accounts in the tab's game, each with what needs attention and a re-fetch. A game that
 * collects no native rank says so instead of claiming no account is linked.
 */
export function PersonRankCollection({
  personId,
  game,
  supported
}: Readonly<{ personId: number; game: string; supported: boolean }>) {
  const t = useTranslations("adminPeople.rank");
  const tGame = useTranslations("common.discipline");
  return supported ? (
    <CollectionList personId={personId} game={game} />
  ) : (
    <SettingGroup id="collection" title={t("collection")}>
      <EmptyNote>{tGame("widgetUnsupported")}</EmptyNote>
    </SettingGroup>
  );
}

function CollectionList({ personId, game }: Readonly<{ personId: number; game: string }>) {
  const t = useTranslations("adminPeople.rank");
  const format = useFormatter();
  const queryClient = useQueryClient();
  // Scoped server-side to the injected workspace; see `admin.service.ts`.
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const statusQuery = useQuery({
    queryKey: adminQueryKeys.rankCollection(workspaceId, game, personId),
    queryFn: () => adminService.getRankCollectionStatus(personId, game)
  });
  const rows = statusQuery.data ?? [];

  const trigger = useMutation({
    mutationFn: (socialAccountIds: number[] | null) =>
      adminService.triggerRankCollection(game, { user_id: personId, social_account_ids: socialAccountIds }),
    onSuccess: (result) => {
      notify.success(t("queued", { count: result.enqueued }));
      queryClient.invalidateQueries({ queryKey: adminQueryKeys.rank() });
    },
    onError: (error) => notify.apiError(error, { title: t("queueError") })
  });

  return (
    <SettingGroup
      id="collection"
      title={t("collection")}
      actions={
        rows.length > 0 ? (
          <Button size="sm" disabled={trigger.isPending} onClick={() => trigger.mutate(null)}>
            {trigger.isPending ? <Spinner className="size-3.5" /> : null}
            {t("collectAll")}
          </Button>
        ) : null
      }
    >
      {statusQuery.isPending ? (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : statusQuery.isError ? (
        <LoadErrorNote onRetry={() => void statusQuery.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyNote size="sm">{t("noTags")}</EmptyNote>
      ) : (
        <ul className="divide-y divide-border/60">
          {rows.map((row) => (
            <li key={row.social_account_id} className="flex items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="min-w-0 truncate text-body font-medium" title={row.handle}>
                    {row.handle}
                  </span>
                  {/* `ok` is the norm: only a state that needs attention gets a pill. */}
                  {row.status && row.status !== "ok" ? <StatusBadge status={row.status} /> : null}
                </div>
                <p className="flex flex-wrap gap-x-1.5 text-caption tabular-nums text-muted-foreground">
                  {row.last_checked_at ? (
                    <span title={formatDate(format, row.last_checked_at)}>
                      {t("checked", { when: formatRelative(format, row.last_checked_at) })}
                    </span>
                  ) : null}
                  {row.consecutive_failures > 0 ? (
                    <>
                      {row.last_checked_at ? <span aria-hidden>·</span> : null}
                      <span title={row.last_error ?? undefined}>
                        {t("failures", { count: row.consecutive_failures })}
                      </span>
                    </>
                  ) : null}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="shrink-0"
                disabled={trigger.isPending}
                onClick={() => trigger.mutate([row.social_account_id])}
                aria-label={t("collectFor", { battleTag: row.handle })}
              >
                {t("collect")}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </SettingGroup>
  );
}
