"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Switch } from "@/components/ui/switch";
import { Spinner } from "@/components/ui/spinner";
import { notificationQueryKeys } from "@/lib/notifications/query-keys";
import { notify } from "@/lib/notify";
import notificationService from "@/services/notification.service";
import { useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import type { NotificationGroup, NotificationPreferences } from "@/types/notification.types";

/** Rail order of the three opt-out groups; the labels live in `accountSettings`. */
const GROUPS: readonly NotificationGroup[] = ["tournament", "matches", "team"];

/**
 * Which Discord DMs this account still wants.
 *
 * In-app notifications are not switchable and deliberately absent: the inbox is
 * the record of what happened, and a reader who silenced it would simply stop
 * being told. What is switchable is the copy Discord sends, grouped in three
 * rather than per kind — someone who does not want match pings wants none of
 * them, and twelve switches would be twelve ways to end up half-muted.
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
    mutationFn: (discord_dm: Partial<Record<NotificationGroup, boolean>>) =>
      notificationService.updatePreferences({ discord_dm }),
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
            <div
              key={group}
              className="flex items-start gap-3 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-3 py-2.5"
            >
              <div className="flex-1 space-y-1">
                <p id={`dm-${group}-label`} className="text-sm text-[color:var(--aqt-fg)]">
                  {t(`notifications.groups.${group}.label`)}
                </p>
                <p id={`dm-${group}-desc`} className="text-xs text-[color:var(--aqt-fg-dim)]">
                  {t(`notifications.groups.${group}.desc`)}
                </p>
              </div>
              <Switch
                checked={preferences?.discord_dm[group] ?? true}
                // Never act on a guess: without a loaded row there is no value
                // to invert, and a wrong payload here silently re-enables DMs
                // the reader turned off.
                disabled={!preferences || save.isPending}
                onCheckedChange={(next) => save.mutate({ [group]: next })}
                aria-labelledby={`dm-${group}-label`}
                aria-describedby={`dm-${group}-desc`}
              />
            </div>
          ))}
        </div>

        <p className="text-label text-[color:var(--aqt-fg-dim)]">{t("notifications.footnote")}</p>
      </section>
    </div>
  );
}
