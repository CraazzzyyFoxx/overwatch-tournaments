"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { SettingGroup, SettingRow, settingHintId, settingLabelId } from "@/components/kit/SettingRow";
import { Button } from "@/components/ui/button";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { notificationQueryKeys } from "@/lib/notifications/query-keys";
import { notify } from "@/lib/notify";
import notificationService from "@/services/notification.service";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import type {
  NotificationGroup,
  NotificationPreferences,
  NotificationPreferencesUpdate
} from "@/types/notification.types";

/** Rail order of the participant groups; the labels live in `accountSettings`. */
const GROUPS: readonly NotificationGroup[] = ["tournament", "matches", "team"];

/**
 * Which Discord DMs this account still wants.
 *
 * In-app notifications are not switchable and deliberately absent: the inbox is
 * the record of what happened, and a reader who silenced it would simply stop
 * being told. What is switchable is the copy Discord sends, grouped rather than
 * per kind — someone who does not want match pings wants none of them, and
 * twelve switches would be twelve ways to end up half-muted.
 *
 * The `staff` group appears only for someone who is staff somewhere. It is the
 * master switch; with two or more workspaces each also gets its own switch
 * underneath, inert while the master is off.
 *
 * No Save button, like the mix panel next door: each switch writes its own
 * group and the server answers with the effective row, which becomes the new
 * state. A failed write leaves the switch where the server still has it.
 */
export default function NotificationsSection() {
  const t = useTranslations("accountSettings");
  const queryClient = useQueryClient();
  const setActiveTab = useAccountSettingsModalStore((state) => state.setActiveTab);

  const preferencesQuery = useQuery({
    queryKey: notificationQueryKeys.preferences(),
    queryFn: () => notificationService.preferences(),
    staleTime: 60_000
  });
  const preferences = preferencesQuery.data;

  const save = useMutation({
    mutationFn: (body: NotificationPreferencesUpdate) => notificationService.updatePreferences(body),
    onSuccess: (saved: NotificationPreferences) =>
      queryClient.setQueryData(notificationQueryKeys.preferences(), saved),
    onError: (error) => notify.apiError(error)
  });

  if (preferencesQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title={t("notifications.loadError")}
        onAction={() => void preferencesQuery.refetch()}
      />
    );
  }

  const staffWorkspaces = preferences?.staff_workspaces ?? [];

  return (
    <div className="space-y-3">
      {/* Not an error: the switches keep their meaning, the messages simply
          have nowhere to go until a Discord account is linked — and that is
          one tab away rather than on this one. A dashed note, so it sits
          above the group card rather than inside it. */}
      {preferences && !preferences.discord_linked ? (
        <EmptyNote
          size="sm"
          action={
            <Button variant="link" size="inline" onClick={() => setActiveTab("profile")}>
              {t("notifications.linkDiscordAction")}
            </Button>
          }
        >
          {t("notifications.linkDiscordHint")}
        </EmptyNote>
      ) : null}

      <SettingGroup
        id="notifications-discord"
        level={4}
        title={t("notifications.discordTitle")}
        description={t("notifications.discordDesc")}
      >
        {preferencesQuery.isLoading
          ? // Shaped like the rows below, so nothing moves when they land.
            GROUPS.map((name) => (
              <div
                key={name}
                aria-hidden
                className="flex items-center justify-between gap-6 py-3 first:pt-0 last:pb-0"
              >
                <div className="min-w-0 flex-1 space-y-1.5">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-3 w-full max-w-xs" />
                </div>
                <Skeleton className="h-6 w-11 shrink-0 rounded-full" />
              </div>
            ))
          : GROUPS.map((name) => (
              <SettingRow
                key={name}
                htmlFor={`dm-${name}`}
                label={t(`notifications.groups.${name}.label`)}
                hint={t(`notifications.groups.${name}.desc`)}
              >
                <Switch
                  id={`dm-${name}`}
                  aria-describedby={settingHintId(`dm-${name}`)}
                  checked={preferences?.discord_dm[name] ?? true}
                  // Never act on a guess: without a loaded row there is no value
                  // to invert, and a wrong payload here silently re-enables DMs
                  // the reader turned off.
                  disabled={!preferences || save.isPending}
                  onCheckedChange={(next) => save.mutate({ discord_dm: { [name]: next } })}
                />
              </SettingRow>
            ))}

        {preferences && staffWorkspaces.length > 0 ? (
          <div className="py-3 first:pt-0 last:pb-0">
            <SettingRow
              htmlFor="dm-staff"
              label={t("notifications.groups.staff.label")}
              hint={t("notifications.groups.staff.desc")}
            >
              <Switch
                id="dm-staff"
                aria-describedby={settingHintId("dm-staff")}
                checked={preferences.discord_dm.staff}
                disabled={save.isPending}
                onCheckedChange={(next) => save.mutate({ discord_dm: { staff: next } })}
              />
            </SettingRow>
            {/* One workspace needs no second switch saying the same thing. */}
            {staffWorkspaces.length > 1 ? (
              <ul className="ms-1 space-y-2 border-s border-border/60 ps-4">
                {staffWorkspaces.map((workspace) => {
                  const id = `dm-staff-${workspace.workspace_id}`;
                  return (
                    <li key={workspace.workspace_id} className="flex min-h-9 items-center justify-between gap-3">
                      <Label
                        id={settingLabelId(id)}
                        htmlFor={id}
                        title={workspace.name}
                        className="min-w-0 truncate text-caption font-normal leading-normal text-[color:var(--aqt-fg-muted)]"
                      >
                        {workspace.name}
                      </Label>
                      <Switch
                        id={id}
                        checked={workspace.enabled}
                        disabled={!preferences.discord_dm.staff || save.isPending}
                        onCheckedChange={(next) =>
                          save.mutate({ staff_workspaces: { [workspace.workspace_id]: next } })
                        }
                      />
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </div>
        ) : null}
      </SettingGroup>

      <p className="text-caption text-pretty text-[color:var(--aqt-fg-dim)]">{t("notifications.footnote")}</p>
    </div>
  );
}
