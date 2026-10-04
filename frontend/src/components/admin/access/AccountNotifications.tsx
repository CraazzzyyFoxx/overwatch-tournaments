"use client";

import { useId } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AccountSection } from "@/components/admin/access/AccountCard";
import { EmptyNote } from "@/components/kit/EmptyNote";
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

const GROUPS: readonly { key: NotificationGroup; label: string; hint: string }[] = [
  { key: "tournament", label: "Tournaments", hint: "Check-in opening, registration decisions" },
  { key: "matches", label: "Matches", hint: "Match scheduled or moved, disputed reports" },
  { key: "team", label: "Teams", hint: "Invites, answers, removals" }
];

/** Shown only for an account that is staff somewhere, like on the self-service screen. */
const STAFF_GROUP = {
  key: "staff",
  label: "For organizers",
  hint: "Disputes awaiting a decision; ignores the tournament DM mute"
} as const;

/** The personal kinds a DM can carry (`NOTIFICATION_KIND_GROUPS`); others fall back to the raw kind. */
const KIND_LABELS: Record<string, string> = {
  "check_in.opened": "Check-in opened",
  "registration.approved": "Registration approved",
  "registration.rejected": "Registration rejected",
  "encounter.scheduled": "Match scheduled",
  "encounter.report_disputed": "Report disputed",
  "encounter.dispute_review": "Dispute needs a decision",
  "team_invite.received": "Team invite",
  "team_invite.answered": "Invite answered",
  "team.kicked": "Removed from team",
  "team.disbanded": "Team disbanded",
  "team.rejected": "Team rejected"
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
    onError: (error) => notify.apiError(error, { title: "Could not change the DM setting" })
  });

  return (
    <AccountSection
      title="Notifications"
      summary={data ? `${data.unread_count} unread` : undefined}
    >
      {query.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : !data ? (
        <p className="text-xs text-muted-foreground">Could not load notification settings.</p>
      ) : (
        <div className="space-y-3">
          {!data.discord_linked ? (
            <EmptyNote size="sm" tone="warning">
              No Discord linked — DMs have nowhere to go. The in-app inbox still gets everything.
            </EmptyNote>
          ) : null}

          <div role="group" aria-label="Discord direct messages" className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">Discord DMs</p>
            {[...GROUPS, ...(data.staff_workspaces.length > 0 ? [STAFF_GROUP] : [])].map((group) => (
              <div key={group.key} className="flex items-center justify-between gap-3 py-0.5">
                <div className="min-w-0">
                  <p id={`${idPrefix}-${group.key}`} className="text-sm">
                    {group.label}
                  </p>
                  <p
                    id={`${idPrefix}-${group.key}-hint`}
                    className="truncate text-xs text-muted-foreground"
                  >
                    {group.hint}
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
            <p className="text-xs font-medium text-muted-foreground">Recent DMs</p>
            {data.recent_deliveries.length === 0 ? (
              <p className="text-xs text-muted-foreground">No DMs sent to this account yet.</p>
            ) : (
              <ol className="space-y-1">
                {data.recent_deliveries.map((delivery) => {
                  const workspace =
                    delivery.workspace_id == null
                      ? null
                      : (workspaces.find((candidate) => candidate.id === delivery.workspace_id)
                          ?.name ?? `Workspace #${delivery.workspace_id}`);
                  return (
                    <li key={delivery.id} className="flex items-baseline gap-2 text-xs">
                      <span className="min-w-0 flex-1 truncate">
                        {KIND_LABELS[delivery.kind] ?? delivery.kind}
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
