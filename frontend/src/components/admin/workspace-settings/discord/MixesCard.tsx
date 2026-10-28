"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import {
  useScopedSettingsForm,
  type ScopedSettingsForm
} from "@/components/kit/useScopedSettingsForm";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { DiscordChannelSelect } from "@/components/discord/DiscordChannelSelect";
import { useDiscordChannels } from "@/hooks/useDiscordEntities";
import balancerAdminService from "@/services/balancer-admin.service";
import type { DiscordVoicePermission } from "@/types/discord.types";
import type {
  WorkspaceBalancerConfig,
  WorkspaceBalancerConfigUpsert
} from "@/types/balancer-admin.types";
import { balancerQueryKeys } from "@/lib/balancer/query-keys";

const VOICE_PERMISSION_MESSAGE_KEYS = {
  view_channel: "viewChannel",
  connect: "connect",
  move_members: "moveMembers"
} as const satisfies Record<DiscordVoicePermission, string>;

function missingLabel(
  t: (key: "viewChannel" | "connect" | "moveMembers") => string,
  missing: DiscordVoicePermission[] | null | undefined
): string | null {
  if (!missing || missing.length === 0) return null;
  return missing
    .map((name) => t(VOICE_PERMISSION_MESSAGE_KEYS[name]))
    .join(", ");
}

type MixFields = Pick<
  WorkspaceBalancerConfigUpsert,
  "mix_discord_channel_id" | "mix_voice_category_id" | "mix_general_voice_channel_ids"
>;

/** The fields that differ from the stored config; their count is the save bar's summary. */
function mixDiff(form: MixFields, base: MixFields): Partial<MixFields> {
  const diff: Partial<MixFields> = {};
  if (form.mix_discord_channel_id !== base.mix_discord_channel_id) {
    diff.mix_discord_channel_id = form.mix_discord_channel_id;
  }
  if (form.mix_voice_category_id !== base.mix_voice_category_id) {
    diff.mix_voice_category_id = form.mix_voice_category_id;
  }
  const voices = form.mix_general_voice_channel_ids;
  const savedVoices = base.mix_general_voice_channel_ids;
  if (voices.length !== savedVoices.length || voices.some((id) => !savedVoices.includes(id))) {
    diff.mix_general_voice_channel_ids = voices;
  }
  return diff;
}

/** The mix draft the Discord section's `SaveBar` saves, plus its read. */
export interface MixesForm extends ScopedSettingsForm<MixFields, Partial<MixFields>> {
  query: UseQueryResult<WorkspaceBalancerConfig>;
}

/**
 * Draft of where every mix in this workspace announces its matchup, the voice
 * category it moves players through, and which of its voices players wait in;
 * saved through the Discord section's one `SaveBar`.
 *
 * All three live in `balancer.workspace_config.config_json`, and the upsert
 * rewrites that whole blob, so every save posts every key (rank-delta knobs
 * included) with only the edited ones replaced. Same query key as the
 * balancer page's dialog, so both views agree after a save.
 */
export function useMixesForm(workspaceId: number | null, enabled: boolean): MixesForm {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: balancerQueryKeys.workspaceConfig(workspaceId ?? 0),
    queryFn: () => balancerAdminService.getWorkspaceBalancerConfig(workspaceId as number),
    enabled: enabled && workspaceId !== null
  });
  const config = query.data;
  const baseline = useMemo<MixFields | null>(
    () =>
      config
        ? {
            mix_discord_channel_id: config.mix_discord_channel_id ?? null,
            mix_voice_category_id: config.mix_voice_category_id ?? null,
            mix_general_voice_channel_ids: config.mix_general_voice_channel_ids ?? []
          }
        : null,
    [config]
  );

  const form = useScopedSettingsForm({
    baseline,
    toPayload: mixDiff,
    submit: (_diff, values) =>
      balancerAdminService.upsertWorkspaceBalancerConfig(workspaceId as number, {
        rank_delta_threshold: config?.rank_delta_threshold ?? null,
        rank_delta_hide_from_pool: config?.rank_delta_hide_from_pool ?? false,
        ...values
      }),
    onSaved: () => {
      queryClient.invalidateQueries({
        queryKey: balancerQueryKeys.workspaceConfig(workspaceId as number)
      });
    }
  });

  return { ...form, query };
}

export function MixesCard({
  workspaceId,
  mixes
}: Readonly<{ workspaceId: number; mixes: MixesForm }>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.discord");
  const { query, form: values, patch, saving } = mixes;
  const channelsQuery = useDiscordChannels(workspaceId);

  if (query.isError) {
    return (
      <PageStateCard state="error" title={t("mixLoadError")} onAction={() => void query.refetch()} />
    );
  }

  // The pickers speak in strings and have no null: "" is their empty value.
  const categoryId = values?.mix_voice_category_id ?? "";
  const generalIds = values?.mix_general_voice_channel_ids ?? [];
  const channels = channelsQuery.data?.channels ?? [];
  const categories = channels.filter((item) => item.type === "category");
  const category = categories.find((item) => item.id === categoryId);
  // A voice outside the category is not offered: the move would take a player
  // out of the mix's own corner of the server.
  const voices = channels.filter(
    (item) => item.type === "voice" && item.category_id === categoryId
  );
  const lacking = voices.flatMap((voice) => {
    const missing = missingLabel(t, voice.missing_permissions);
    return missing ? [`${voice.name}: ${missing}`] : [];
  });
  const categoryMissing = missingLabel(t, category?.missing_permissions);
  const busy = channelsQuery.isLoading || saving;

  return (
    <SettingGroup id="mixes" title={t("mixes")}>
      {!values ? (
        <div aria-busy="true" className="flex flex-col gap-4 py-2">
          {[0, 1].map((row) => (
            <div key={row} className="grid gap-2 @xl:grid-cols-2 @xl:gap-6">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-9 w-full" />
            </div>
          ))}
        </div>
      ) : (
        <>
          <SettingRow
            htmlFor="mix-announcement-channel"
            label={t("announcementChannel")}
            hint={t("announcementChannelHint")}
          >
            <div className="w-full md:max-w-sm">
              <DiscordChannelSelect
                id="mix-announcement-channel"
                workspaceId={workspaceId}
                value={values.mix_discord_channel_id ?? ""}
                onChange={(next) => patch({ mix_discord_channel_id: next === "" ? null : next })}
                disabled={saving}
                ariaLabel={t("mixChannelAria")}
                placeholder={t("noChannel")}
                noneLabel={t("noChannel")}
              />
            </div>
          </SettingRow>

          <SettingRow htmlFor="mix-voice-category" label={t("voiceCategory")} hint={t("voiceCategoryHint")}>
            <div className="flex w-full flex-col gap-1 md:max-w-sm">
              <DiscordChannelSelect
                id="mix-voice-category"
                type="category"
                workspaceId={workspaceId}
                value={categoryId}
                // A new category invalidates the old general voices: they
                // belong to the category that is being left behind.
                onChange={(next) =>
                  patch({
                    mix_voice_category_id: next === "" ? null : next,
                    mix_general_voice_channel_ids: []
                  })
                }
                disabled={saving}
                ariaLabel={t("mixVoiceCategory")}
                placeholder={t("noVoiceCategory")}
                noneLabel={t("noVoiceCategory")}
              />
              {categoryMissing ? (
                <p className="text-xs text-warning">{t("missing", { value: categoryMissing })}</p>
              ) : null}
            </div>
          </SettingRow>

          {categoryId !== "" ? (
            <SettingRow label={t("generalVoices")} hint={t("generalVoicesHint")}>
              <div className="flex w-full flex-col gap-2 md:max-w-sm">
                {channelsQuery.isLoading ? (
                  <div aria-busy="true" className="flex gap-1.5">
                    <span className="sr-only">{t("asking")}</span>
                    <Skeleton className="h-7 w-20" />
                    <Skeleton className="h-7 w-20" />
                  </div>
                ) : voices.length > 0 ? (
                  <FilterChipGroup label={t("generalVoices")}>
                    {voices.map((voice) => {
                      const pressed = generalIds.includes(voice.id);
                      const missing = missingLabel(t, voice.missing_permissions);
                      return (
                        <FilterChip
                          key={voice.id}
                          active={pressed}
                          disabled={busy}
                          onClick={() =>
                            patch({
                              mix_general_voice_channel_ids: pressed
                                ? generalIds.filter((id) => id !== voice.id)
                                : [...generalIds, voice.id]
                            })
                          }
                          title={missing ? t("missing", { value: missing }) : undefined}
                        >
                          {voice.name}
                        </FilterChip>
                      );
                    })}
                  </FilterChipGroup>
                ) : (
                  <p className="text-xs text-warning">{t("noVoices")}</p>
                )}
                {lacking.length > 0 ? (
                  <p className="text-xs text-warning">
                    {t("missingOn", { value: lacking.join("; ") })}
                  </p>
                ) : null}
              </div>
            </SettingRow>
          ) : null}
        </>
      )}
    </SettingGroup>
  );
}
