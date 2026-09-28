"use client";

import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Archive } from "lucide-react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { DataTable } from "@/components/data-table";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { LinkTabs } from "@/components/kit/LinkTabs";
import { ConfirmDialog, type ConfirmIntent } from "@/components/kit/ConfirmDialog";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { notificationQueryKeys } from "@/lib/notifications/query-keys";
import { notify } from "@/lib/notify";
import notificationService from "@/services/notification.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { NotificationAdminItem } from "@/types/notification.types";

/**
 * The system notifications this workspace's own activity produced — a
 * registration decision, a team invite, a disputed report — and the retire that
 * takes one back out of every recipient's inbox.
 *
 * Scoped by `source_workspace_id`, which is why announcements are not here:
 * they are authored by hand, carry operator-written text in several locales and
 * have their own screen. One row with two delete buttons in two places is how
 * "retired" and "edited" end up disagreeing.
 *
 * "Retire" is not a delete. The server expires the row: it stops reaching any
 * inbox and stops counting toward any badge, while the row and the read marks
 * that record who saw it survive. The confirmation says exactly that, because
 * an operator who expects a hard delete would otherwise assume the evidence is
 * gone.
 */

/** The kinds the operator RPC accepts; the announcement owns another screen. */
const KINDS = [
  "team_invite.received",
  "team_invite.answered",
  "registration.approved",
  "registration.rejected",
  "registration.opened",
  "check_in.opened",
  "encounter.report_disputed",
  "encounter.scheduled",
  "team.kicked",
  "team.rejected",
  "team.disbanded"
] as const;

const ALL_KINDS = "all";
const KIND_PARAM = "kind";
/** The server's default page; it caps `per_page` at 100. */
const PAGE_SIZE = 25;

export default function AdminWorkspaceNotificationsPage() {
  const { canAccessPermission, isLoaded } = usePermissions();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const t = useTranslations<never>();
  const format = useFormatter();
  const queryClient = useQueryClient();

  const { searchParams } = useQueryParams({ resetOnChange: [] });
  const [confirming, setConfirming] = useState<{ ids?: number[]; kind?: string } | null>(null);
  // Seen from the table's own fetch: the kind retire is pointless on an empty kind.
  const [total, setTotal] = useState<number | null>(null);

  const canRead = workspaceId != null && canAccessPermission("notification.read", workspaceId);
  // Two grants, two questions — the server checks them separately, so a
  // `notification.read` holder gets the table with no retire control at all.
  const canRetire = workspaceId != null && canAccessPermission("notification.delete", workspaceId);
  // The filter lives in the URL, not in component state: it decides which rows
  // a bulk retire would take, so "which kind was I looking at" must survive a
  // reload and be linkable to a colleague rather than reset silently.
  const requested = searchParams?.get(KIND_PARAM);
  const kind = requested && KINDS.includes(requested as (typeof KINDS)[number]) ? requested : ALL_KINDS;
  const kindFilter = kind === ALL_KINDS ? null : kind;

  const retire = useMutation({
    mutationFn: (target: { ids?: number[]; kind?: string }) =>
      notificationService.retireWorkspaceNotifications({
        workspaceId: workspaceId as number,
        ids: target.ids,
        kind: target.kind
      }),
    onSuccess: (result) => {
      notify.success(t("notifications.workspaceAdmin.retired", { count: result.retired }));
      // Both feeds read the same rows: an expired notification has to leave the
      // operator table *and* the bell of everyone still holding it open.
      void queryClient.invalidateQueries({ queryKey: notificationQueryKeys.list() });
    }
  });

  const columns = useMemo<ColumnDef<NotificationAdminItem>[]>(() => {
    const stamp = (value: string | null) =>
      value == null ? (
        <span className="text-sm text-muted-foreground">&mdash;</span>
      ) : (
        <time dateTime={value} className="whitespace-nowrap text-sm tabular-nums">
          {format.dateTime(new Date(value), { dateStyle: "medium", timeStyle: "short" })}
        </time>
      );
    const isRetired = (row: NotificationAdminItem) =>
      row.expires_at != null && new Date(row.expires_at).getTime() <= Date.now();

    const defs: ColumnDef<NotificationAdminItem>[] = [
      {
        accessorKey: "kind",
        header: t("notifications.workspaceAdmin.columns.kind"),
        size: 220,
        // One server order (newest first); a header sort would change nothing.
        enableSorting: false,
        cell: ({ row }) => (
          <Badge tone="neutral" className="font-normal">
            {t(`notifications.workspaceAdmin.kinds.${row.original.kind}` as never)}
          </Badge>
        )
      },
      {
        id: "recipient",
        header: t("notifications.workspaceAdmin.columns.recipient"),
        size: 200,
        enableSorting: false,
        // Username joined at read time, id as the fallback: the account can be
        // gone while the row it was told about still has to be retirable.
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.recipient_username ?? row.original.recipient_auth_user_id ?? "—"}
          </span>
        )
      },
      {
        accessorKey: "published_at",
        header: t("notifications.workspaceAdmin.columns.publishedAt"),
        size: 190,
        enableSorting: false,
        cell: ({ row }) => stamp(row.original.published_at)
      },
      {
        id: "state",
        header: t("notifications.workspaceAdmin.columns.state"),
        size: 130,
        enableSorting: false,
        // Read off the stamp rather than asked of the backend: the inbox reads
        // filter on exactly this window, so a stored flag could disagree with
        // who actually still sees the row.
        cell: ({ row }) => (
          <Badge tone={isRetired(row.original) ? "neutral" : "success"} className="font-normal">
            {t(
              isRetired(row.original)
                ? "notifications.workspaceAdmin.state.retired"
                : "notifications.workspaceAdmin.state.live"
            )}
          </Badge>
        )
      }
    ];

    if (canRetire) {
      defs.push({
        id: "actions",
        header: "",
        size: 130,
        enableSorting: false,
        cell: ({ row }) =>
          isRetired(row.original) ? null : (
            <Button
              variant="ghost"
              size="sm"
              disabled={retire.isPending}
              onClick={() => setConfirming({ ids: [row.original.id] })}
            >
              {t("notifications.workspaceAdmin.retire.action")}
            </Button>
          )
      });
    }
    return defs;
  }, [t, format, canRetire, retire.isPending]);

  if (!isLoaded) return <Skeleton className="h-64 w-full rounded-xl" />;

  if (workspaceId == null) {
    return (
      <div className="space-y-6">
        <AdminPageHeader
          title={t("notifications.workspaceAdmin.title")}
          description={t("notifications.workspaceAdmin.description")}
        />
        <EmptyNote className="text-center">
          {t("notifications.workspaceAdmin.pickWorkspace")}
        </EmptyNote>
      </div>
    );
  }

  if (!canRead) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("notifications.workspaceAdmin.unauthorized.title")}</CardTitle>
          <CardDescription>
            {t("notifications.workspaceAdmin.unauthorized.description")}
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const intent: ConfirmIntent = {
    title: t("notifications.workspaceAdmin.retire.title"),
    description: t("notifications.workspaceAdmin.retire.description"),
    confirmLabel: t("notifications.workspaceAdmin.retire.action"),
    tone: "warning"
  };

  return (
    <div className="space-y-4">
      <AdminPageHeader
        title={t("notifications.workspaceAdmin.title")}
        description={t("notifications.workspaceAdmin.description")}
        actions={
          // Only offered with a kind chosen: "retire everything this workspace
          // ever sent" is not a button, and the server refuses it too.
          canRetire && kindFilter ? (
            <Button
              size="sm"
              variant="outline"
              data-field="retire-kind"
              disabled={retire.isPending || total === 0}
              onClick={() => setConfirming({ kind: kindFilter })}
            >
              <Archive aria-hidden className="size-4" />
              {t("notifications.workspaceAdmin.retire.kindAction")}
            </Button>
          ) : undefined
        }
        footer={
          canRetire ? undefined : (
            <p className="text-xs text-muted-foreground">
              {t("notifications.workspaceAdmin.readOnly")}
            </p>
          )
        }
      />

      <DataTable<NotificationAdminItem>
        columns={columns}
        getRowId={(row) => String(row.id)}
        emptyMessage={t("notifications.workspaceAdmin.empty")}
        initialPageSize={PAGE_SIZE}
        pageSizeOptions={[25, 50, 100]}
        filterKey={kind}
        // The kind row is the table's filter row, and taking the toolbar slot
        // also drops the built-in search box: the server does not search, so
        // a box there would type into nothing. Real links, so a filtered view
        // is linkable and survives a reload.
        toolbar={
          <div data-field="kind" className="min-w-0">
            <LinkTabs
              ariaLabel={t("notifications.workspaceAdmin.kindLabel")}
              activeKey={kind}
              items={[ALL_KINDS, ...KINDS].map((option) => ({
                key: option,
                label:
                  option === ALL_KINDS
                    ? t("notifications.workspaceAdmin.allKinds")
                    : t(`notifications.workspaceAdmin.kinds.${option}` as never),
                href:
                  option === ALL_KINDS
                    ? "/admin/notifications"
                    : `/admin/notifications?${KIND_PARAM}=${option}`
              }))}
            />
          </div>
        }
        // Under the `list()` prefix, so a retire refetches the page on screen.
        queryKey={(page, _search, pageSize) => [
          ...notificationQueryKeys.workspaceNotifications(workspaceId, kindFilter),
          page,
          pageSize
        ]}
        queryFn={async (page, _search, pageSize) => {
          const result = await notificationService.listWorkspaceNotifications({
            workspaceId,
            kind: kindFilter,
            page,
            perPage: pageSize
          });
          setTotal(result.total);
          return result;
        }}
      />

      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(open) => !open && setConfirming(null)}
        intent={intent}
        pending={retire.isPending}
        onConfirm={() => {
          if (confirming) retire.mutate(confirming);
          setConfirming(null);
        }}
      />
    </div>
  );
}
