"use client";

import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Switch } from "@/components/ui/switch";
import { Spinner } from "@/components/ui/spinner";
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

  if (preferencesQuery.isLoading) {
    return (
      <Spinner
        className="text-[color:var(--aqt-fg-muted)]"
        label={t("notifications.title")}
      />
    );
  }

  if (preferencesQuery.isError) {
    return <p className="text-sm text-[color:var(--aqt-fg-dim)]">{t("notifications.loadError")}</p>;
  }

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h4 className="text-sm font-medium text-[color:var(--aqt-fg-muted)]">
          {t("notifications.discordTitle")}
        </h4>
        <p className="text-xs text-[color:var(--aqt-fg-dim)]">{t("notifications.discordDesc")}</p>

        {/* Not an error: the switches keep their meaning, the messages simply
            have nowhere to go until a Discord account is linked — and that is
            one tab away rather than on this one. */}
        {preferences && !preferences.discord_linked ? (
          <div className="rounded-lg border border-dashed border-[color:var(--aqt-border-2)] px-3 py-2.5">
            <p className="text-xs text-[color:var(--aqt-fg-muted)]">
              {t("notifications.linkDiscordHint")}
            </p>
            <button
              type="button"
              onClick={() => setActiveTab("profile")}
              className="mt-2 text-xs font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("notifications.linkDiscordAction")}
            </button>
          </div>
        ) : null}

        <div className="space-y-2">
          {GROUPS.map((group) => (
            <GroupSwitch
              key={group}
              id={`dm-${group}`}
              label={t(`notifications.groups.${group}.label`)}
              desc={t(`notifications.groups.${group}.desc`)}
              checked={preferences?.discord_dm[group] ?? true}
              // Never act on a guess: without a loaded row there is no value
              // to invert, and a wrong payload here silently re-enables DMs
              // the reader turned off.
              disabled={!preferences || save.isPending}
              onCheckedChange={(next) => save.mutate({ discord_dm: { [group]: next } })}
            />
          ))}

          {preferences && preferences.staff_workspaces.length > 0 ? (
            <GroupSwitch
              id="dm-staff"
              label={t("notifications.groups.staff.label")}
              desc={t("notifications.groups.staff.desc")}
              checked={preferences.discord_dm.staff}
              disabled={save.isPending}
              onCheckedChange={(next) => save.mutate({ discord_dm: { staff: next } })}
            >
              {/* One workspace needs no second switch saying the same thing. */}
              {preferences.staff_workspaces.length > 1 ? (
                <ul className="mt-2 space-y-1.5 border-t border-[color:var(--aqt-border)] pt-2">
                  {preferences.staff_workspaces.map((workspace) => (
                    <li key={workspace.workspace_id} className="flex items-center gap-3">
                      <span
                        id={`dm-staff-${workspace.workspace_id}-label`}
                        className="flex-1 truncate text-xs text-[color:var(--aqt-fg-muted)]"
                      >
                        {workspace.name}
                      </span>
                      <Switch
                        checked={workspace.enabled}
                        disabled={!preferences.discord_dm.staff || save.isPending}
                        onCheckedChange={(next) =>
                          save.mutate({ staff_workspaces: { [workspace.workspace_id]: next } })
                        }
                        aria-labelledby={`dm-staff-${workspace.workspace_id}-label`}
                      />
                    </li>
                  ))}
                </ul>
              ) : null}
            </GroupSwitch>
          ) : null}
        </div>

        <p className="text-label text-[color:var(--aqt-fg-dim)]">{t("notifications.footnote")}</p>
      </section>
    </div>
  );
}

function GroupSwitch({
  id,
  label,
  desc,
  checked,
  disabled,
  onCheckedChange,
  children
}: Readonly<{
  id: string;
  label: string;
  desc: string;
  checked: boolean;
  disabled: boolean;
  onCheckedChange: (next: boolean) => void;
  children?: ReactNode;
}>) {
  return (
    <div className="rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-3 py-2.5">
      <div className="flex items-start gap-3">
        <div className="flex-1 space-y-1">
          <p id={`${id}-label`} className="text-sm text-[color:var(--aqt-fg)]">
            {label}
          </p>
          <p id={`${id}-desc`} className="text-xs text-[color:var(--aqt-fg-dim)]">
            {desc}
          </p>
        </div>
        <Switch
          checked={checked}
          disabled={disabled}
          onCheckedChange={onCheckedChange}
          aria-labelledby={`${id}-label`}
          aria-describedby={`${id}-desc`}
        />
      </div>
      {children}
    </div>
  );
}
