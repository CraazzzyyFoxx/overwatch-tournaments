"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import {
  useScopedSettingsForm,
  type ScopedSettingsForm
} from "@/components/kit/useScopedSettingsForm";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { DiscordChannelSelect } from "@/components/discord/DiscordChannelSelect";
import { notificationQueryKeys } from "@/lib/notifications/query-keys";
import notificationService from "@/services/notification.service";
import type {
  NotificationWorkspaceConfig,
  NotificationWorkspaceConfigUpdate
} from "@/types/notification.types";
import { announcementFailure } from "./errors";

/**
 * Human names for the kinds the server offers. The list itself comes from the
 * server (`broadcastable_kinds`), so a kind added there appears here without a
 * release: unnamed, but never missing.
 */
const KIND_MESSAGE_KEYS: Record<
  string,
  "registrationOpened" | "checkInOpened" | "encounterScheduled"
> = {
  "registration.opened": "registrationOpened",
  "check_in.opened": "checkInOpened",
  "encounter.scheduled": "encounterScheduled"
};

/** The fields that differ from the stored config; their count is the save bar's summary. */
function announcementDiff(
  form: NotificationWorkspaceConfigUpdate,
  base: NotificationWorkspaceConfigUpdate
): Partial<NotificationWorkspaceConfigUpdate> {
  const diff: Partial<NotificationWorkspaceConfigUpdate> = {};
  if (form.discord_channel_id !== base.discord_channel_id) {
    diff.discord_channel_id = form.discord_channel_id;
  }
  if (form.locale !== base.locale) diff.locale = form.locale;
  const kindsChanged =
    form.broadcast_kinds.length !== base.broadcast_kinds.length ||
    form.broadcast_kinds.some((kind) => !base.broadcast_kinds.includes(kind));
  if (kindsChanged) diff.broadcast_kinds = form.broadcast_kinds;
  return diff;
}

/** The announcement draft the Discord section's `SaveBar` saves, plus its read. */
export interface AnnouncementsForm
  extends ScopedSettingsForm<
    NotificationWorkspaceConfigUpdate,
    Partial<NotificationWorkspaceConfigUpdate>
  > {
  query: UseQueryResult<NotificationWorkspaceConfig>;
  /** Why the last save was refused, in the organiser's words. */
  error: string | null;
}

/**
 * Draft of where tournament events are announced, which of them, and in what
 * language; saved through the Discord section's one `SaveBar`.
 *
 * The RPC takes all three fields, so a save sends the whole draft, not the
 * diff. A refusal is kept as `error`, because a guild unlinked since the page
 * loaded and Discord being down are different fixes.
 */
export function useAnnouncementsForm(
  workspaceId: number | null,
  enabled: boolean
): AnnouncementsForm {
  const t = useTranslations("adminWorkspace.workspaceSettings.discord");
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: notificationQueryKeys.workspaceConfig(workspaceId ?? 0),
    queryFn: () => notificationService.workspaceConfig(workspaceId as number),
    enabled: enabled && workspaceId !== null
  });
  const config = query.data;
  const baseline = useMemo<NotificationWorkspaceConfigUpdate | null>(
    () =>
      config
        ? {
            discord_channel_id: config.discord_channel_id,
            locale: config.locale,
            broadcast_kinds: config.broadcast_kinds
          }
        : null,
    [config]
  );

  const form = useScopedSettingsForm({
    baseline,
    toPayload: announcementDiff,
    submit: async (_diff, values) => {
      try {
        const saved = await notificationService.updateWorkspaceConfig(workspaceId as number, values);
        setError(null);
        queryClient.setQueryData(notificationQueryKeys.workspaceConfig(workspaceId as number), saved);
      } catch (cause) {
        setError(announcementFailure(cause, t));
        throw cause;
      }
    }
  });

  return { ...form, query, error };
}

export function AnnouncementsCard({
  workspaceId,
  announcements
}: Readonly<{ workspaceId: number; announcements: AnnouncementsForm }>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.discord");
  const contentT = useTranslations("adminWorkspace.content.fields");
  const { query, form: values, patch, saving, error } = announcements;
  const kinds = query.data?.broadcastable_kinds ?? [];

  if (query.isError) {
    return (
      <PageStateCard
        state="error"
        title={t("announcementLoadError")}
        onAction={() => void query.refetch()}
      />
    );
  }

  return (
    <SettingGroup id="announcements" title={t("announcements")}>
      {!values ? (
        <div aria-busy="true" className="flex flex-col gap-4 py-2">
          <span className="sr-only">{t("announcementLoading")}</span>
          {[0, 1, 2].map((row) => (
            <div key={row} className="grid gap-2 @xl:grid-cols-2 @xl:gap-6">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-9 w-full" />
            </div>
          ))}
        </div>
      ) : (
        <>
          <SettingRow label={t("channel")} hint={t("channelHint")}>
            <div className="w-full md:max-w-sm">
              <DiscordChannelSelect
                workspaceId={workspaceId}
                // The picker has no null: "" is its no-channel value.
                value={values.discord_channel_id ?? ""}
                onChange={(next) => patch({ discord_channel_id: next === "" ? null : next })}
                disabled={saving}
                ariaLabel={t("announcementChannelAria")}
                placeholder={t("noChannel")}
                noneLabel={t("noChannel")}
              />
            </div>
          </SettingRow>

          {/* A list of choices reads down from its label, not as a column
              pushed to the far edge of the card. */}
          <SettingRow label={t("events")} hint={t("eventsHint")} stacked>
            <div className="flex flex-col gap-2">
              {kinds.map((kind) => {
                const id = `broadcast-${kind}`;
                const checked = values.broadcast_kinds.includes(kind);
                return (
                  <div key={kind} className="flex items-center gap-2">
                    <Checkbox
                      id={id}
                      checked={checked}
                      disabled={saving}
                      onCheckedChange={(next) =>
                        patch({
                          broadcast_kinds:
                            next === true
                              ? [...values.broadcast_kinds, kind]
                              : values.broadcast_kinds.filter((entry) => entry !== kind)
                        })
                      }
                    />
                    <Label htmlFor={id} className="text-sm font-normal">
                      {KIND_MESSAGE_KEYS[kind] ? contentT(KIND_MESSAGE_KEYS[kind]) : kind}
                    </Label>
                  </div>
                );
              })}
            </div>
          </SettingRow>

          <SettingRow label={t("language")} hint={t("languageHint")}>
            <ToggleGroup
              variant="pill"
              size="sm"
              value={values.locale}
              onValueChange={(next) => patch({ locale: next as "ru" | "en" })}
              aria-label={t("language")}
            >
              <ToggleGroupItem value="ru" disabled={saving}>
                {t("russian")}
              </ToggleGroupItem>
              <ToggleGroupItem value="en" disabled={saving}>
                {t("english")}
              </ToggleGroupItem>
            </ToggleGroup>
          </SettingRow>
        </>
      )}

      {error ? (
        <p role="alert" className="max-w-prose pt-4 text-sm font-medium text-danger">
          {error}
        </p>
      ) : null}
    </SettingGroup>
  );
}
