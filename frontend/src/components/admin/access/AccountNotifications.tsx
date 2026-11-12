"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AccountSection } from "@/components/admin/access/AccountCard";
import { LoadErrorNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { formatDate, formatRelative } from "@/components/kit/format-time";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { accessQueryKeys } from "@/lib/access/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import { notify } from "@/lib/notify";
import notificationService from "@/services/notification.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type {
  AdminUserNotifications,
  NotificationGroup,
  NotificationPreferencesUpdate
} from "@/types/notification.types";

const GROUPS: readonly { key: NotificationGroup; labelKey: "tournaments" | "matches" | "teams"; hintKey: "checkInOpening" | "matchMoved" | "teamInvites" }[] = [
  { key: "tournament", labelKey: "tournaments", hintKey: "checkInOpening" },
  { key: "matches", labelKey: "matches", hintKey: "matchMoved" },
  { key: "team", labelKey: "teams", hintKey: "teamInvites" }
];

/** Shown only for an account that is staff somewhere, like on the self-service screen. */
const STAFF_GROUP = {
  key: "staff",
  labelKey: "forOrganizers",
  hintKey: "disputes"
} as const;

/** The personal kinds a DM can carry (`NOTIFICATION_KIND_GROUPS`); others fall back to the raw kind. */
type NotificationMessageKey =
  | "checkInOpened"
  | "registrationApproved"
  | "registrationRejected"
  | "matchScheduled"
  | "reportDisputed"
  | "disputeDecision"
  | "teamInvite"
  | "inviteAnswered"
  | "removedFromTeam"
  | "teamDisbanded"
  | "teamRejected"
  | "mixBanRoom"
  | "mixDraft";

const KIND_LABELS: Record<string, NotificationMessageKey> = {
  "check_in.opened": "checkInOpened",
  "registration.approved": "registrationApproved",
  "registration.rejected": "registrationRejected",
  "encounter.scheduled": "matchScheduled",
  "encounter.report_disputed": "reportDisputed",
  "encounter.dispute_review": "disputeDecision",
  "team_invite.received": "teamInvite",
  "team_invite.answered": "inviteAnswered",
  "team.kicked": "removedFromTeam",
  "team.disbanded": "teamDisbanded",
  "team.rejected": "teamRejected",
  "mix.ban_room_opened": "mixBanRoom",
  "mix.draft_started": "mixDraft"
};

/**
 * What reaches this account and where: the Discord-DM group switches (plus one
 * per staff workspace), the badge its bell shows, and the last DMs actually
 * sent — the answer to "why did I not get a message" without opening the database.
 *
 * The switches are the user's own settings; an admin can flip them (support
 * asks for it) with `auth_user.update`, and every write answers with the
 * effective row, same as the self-service screen.
 */
export function AccountNotifications({
  userId,
  canEdit
}: Readonly<{ userId: number; canEdit: boolean }>) {
  const t = useTranslations("adminAccess.notifications");
  const tc = useTranslations("adminAccess.common");
  const queryClient = useQueryClient();
  const format = useFormatter();
  const workspaces = useWorkspaceStore((state) => state.workspaces);
  const idPrefix = useId();
  const queryKey = accessQueryKeys.userNotifications(userId);

  const query = useQuery({
    queryKey,
    queryFn: () => notificationService.adminUserNotifications(userId)
  });
  const data = query.data;

  const save = useMutation({
    mutationFn: (body: NotificationPreferencesUpdate) =>
      notificationService.updateAdminUserPreferences(userId, body),
    onSuccess: (saved: AdminUserNotifications) => queryClient.setQueryData(queryKey, saved),
    onError: (error) => notify.apiError(error, { title: t("dmSettingError") })
  });

  return (
    <AccountSection
      title={tc("notifications")}
      summary={data ? t("unreadCount", { count: data.unread_count }) : undefined}
    >
      {query.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : !data ? (
        <LoadErrorNote title={t("loadError")} onRetry={() => void query.refetch()} />
      ) : (
        <div className="space-y-3">
          {!data.discord_linked ? (
            <p className="text-caption text-muted-foreground">{t("noDiscord")}</p>
          ) : null}

          <div role="group" aria-label={t("discordDms")} className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">{t("discordDms")}</p>
            {[...GROUPS, ...(data.staff_workspaces.length > 0 ? [STAFF_GROUP] : [])].map((group) => (
              <div key={group.key} className="flex items-center justify-between gap-3 py-0.5">
                <div className="min-w-0">
                  <p id={`${idPrefix}-${group.key}`} className="text-sm">
                    {tc(group.labelKey)}
                  </p>
                  <p
                    id={`${idPrefix}-${group.key}-hint`}
                    className="truncate text-xs text-muted-foreground"
                  >
                    {t(group.hintKey)}
                  </p>
                </div>
                <Switch
                  checked={data.discord_dm[group.key]}
                  disabled={!canEdit || save.isPending}
                  onCheckedChange={(next) => save.mutate({ discord_dm: { [group.key]: next } })}
                  aria-labelledby={`${idPrefix}-${group.key}`}
                  aria-describedby={`${idPrefix}-${group.key}-hint`}
                />
              </div>
            ))}
            {data.staff_workspaces.length > 1
              ? data.staff_workspaces.map((workspace) => (
                  <div
                    key={workspace.workspace_id}
                    className="flex items-center justify-between gap-3 py-0.5 pl-4"
                  >
                    <p
                      id={`${idPrefix}-staff-${workspace.workspace_id}`}
                      className="min-w-0 truncate text-xs text-muted-foreground"
                    >
                      {workspace.name}
                    </p>
                    <Switch
                      checked={workspace.enabled}
                      disabled={!canEdit || !data.discord_dm.staff || save.isPending}
                      onCheckedChange={(next) =>
                        save.mutate({ staff_workspaces: { [workspace.workspace_id]: next } })
                      }
                      aria-labelledby={`${idPrefix}-staff-${workspace.workspace_id}`}
                    />
                  </div>
                ))
              : null}
          </div>

          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">{t("recentDms")}</p>
            {data.recent_deliveries.length === 0 ? (
              <p className="text-xs text-muted-foreground">{t("noDms")}</p>
            ) : (
              <ol className="space-y-1">
                {data.recent_deliveries.map((delivery) => {
                  const workspace =
                    delivery.workspace_id == null
                      ? null
                      : (workspaces.find((candidate) => candidate.id === delivery.workspace_id)
                          ?.name ?? tc("workspaceFallback", { id: delivery.workspace_id }));
                  return (
                    <li key={delivery.id} className="flex items-baseline gap-2 text-xs">
                      <span className="min-w-0 flex-1 truncate">
                        {KIND_LABELS[delivery.kind]
                          ? t(KIND_LABELS[delivery.kind])
                          : delivery.kind}
                        {workspace ? (
                          <span className="text-muted-foreground"> · {workspace}</span>
                        ) : null}
                      </span>
                      <time
                        dateTime={delivery.created_at}
                        title={formatDate(format, delivery.created_at)}
                        className="shrink-0 tabular-nums text-muted-foreground"
                      >
                        {formatRelative(format, delivery.created_at)}
                      </time>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        </div>
      )}
    </AccountSection>
  );
}
