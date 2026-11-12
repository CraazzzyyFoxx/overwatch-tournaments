"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingsGrid } from "@/components/kit/SettingRow";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { useDiscordGuildInfo } from "@/hooks/useDiscordEntities";
import { notify } from "@/lib/notify";
import workspaceService from "@/services/workspace.service";
import type { DiscordGuildInfo } from "@/types/discord.types";
import type { ManageableDiscordGuild, Workspace } from "@/types/workspace.types";
import { WorkspaceSettingsFrame } from "./WorkspaceSettingsFrame";
import { useWorkspaceSettingsForm } from "./useWorkspaceSettingsForm";
import { AnnouncementsCard, useAnnouncementsForm } from "./discord/AnnouncementsCard";
import { bindFailure } from "./discord/errors";
import { MixesCard, useMixesForm } from "./discord/MixesCard";
import { ServerCard } from "./discord/ServerCard";
import { ServerPicker } from "./discord/ServerPicker";
import { userQueryKeys } from "@/lib/users/query-keys";
import { workspaceQueryKeys } from "@/lib/workspace/query-keys";

/**
 * The bound server's name: Discord's answer, else the picker's, else plain
 * words. Never a made-up name ("Discord" read as the server's real one) and
 * never the id, which the card already prints under the name.
 */
function boundName(
  workspace: Workspace,
  info: DiscordGuildInfo | undefined,
  picker: ManageableDiscordGuild[],
  unnamed: string
): string {
  if (info?.name) return info.name;
  const fromPicker = picker.find((guild) => guild.guild_id === workspace.discord_guild_id);
  return fromPicker?.name ?? unnamed;
}

function boundIcon(
  workspace: Workspace,
  info: DiscordGuildInfo | undefined,
  picker: ManageableDiscordGuild[]
): string | null | undefined {
  if (info?.icon_url) return info.icon_url;
  return picker.find((guild) => guild.guild_id === workspace.discord_guild_id)?.icon_url;
}

/**
 * Everything Discord in one workspace: the guild it runs in (patron roles,
 * match-log channels), tournament announcements and mixes.
 *
 * The guild is a picker over the servers this account administers, never a
 * free-text ID: binding proves ownership through Discord OAuth server-side, so
 * the guild is not a field the workspace PATCH can set at all. Unlinking is a
 * separate verb (`clear_discord_guild`): workspace.update is enough, so an
 * organiser can leave a server they were kicked from.
 *
 * Announcements and mixes are drafts behind one `SaveBar`: both endpoints take
 * their whole body, so there is no per-field save to make instant.
 */
export function DiscordSection({ workspaceId }: Readonly<{ workspaceId: number | null }>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.discord");
  const saveBarT = useTranslations("admin.saveBar");
  const settings = useWorkspaceSettingsForm(workspaceId, "discord");
  const { invalidate } = settings;
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [unlinkOpen, setUnlinkOpen] = useState(false);

  const guildsQuery = useQuery({
    queryKey: userQueryKeys.myDiscordGuilds(),
    queryFn: () => workspaceService.myDiscordGuilds(),
    retry: false
  });
  const guildInfoQuery = useDiscordGuildInfo(workspaceId, Boolean(workspaceId));
  // Channels come from the linked guild, so there is nothing to read until one
  // is bound.
  const bound = Boolean(settings.workspace?.discord_guild_id);
  const announcements = useAnnouncementsForm(workspaceId, bound);
  const mixes = useMixesForm(workspaceId, bound);
  const changedCount =
    Object.keys(announcements.payload ?? {}).length + Object.keys(mixes.payload ?? {}).length;

  const refresh = () => {
    invalidate();
    if (workspaceId !== null) {
      queryClient.invalidateQueries({ queryKey: workspaceQueryKeys.discord(workspaceId) });
    }
  };

  const bind = useMutation({
    mutationFn: (guildId: string) =>
      workspaceService.verifyDiscordGuild(workspaceId as number, guildId),
    onSuccess: () => {
      setError(null);
      setPickerOpen(false);
      refresh();
      notify.success(t("linkedSuccess"));
    },
    onError: (cause) => {
      setError(bindFailure(cause, t));
      notify.apiError(cause, { title: t("linkError") });
    }
  });

  const unlink = useMutation({
    mutationFn: () => workspaceService.clearDiscordGuild(workspaceId as number),
    onSuccess: () => {
      setUnlinkOpen(false);
      setError(null);
      refresh();
      notify.success(t("unlinkedSuccess"));
    },
    onError: (cause) => {
      notify.apiError(cause, { title: t("unlinkError") });
    }
  });

  // Discord reports every server the account is in; only the ones it can
  // manage are bindable, and offering the rest would be offering a guaranteed
  // 403.
  const manageable = (guildsQuery.data ?? []).filter((guild) => guild.can_manage);

  return (
    <WorkspaceSettingsFrame workspaceId={workspaceId} settings={settings}>
      {({ workspace }) => {
        const boundId = workspace.discord_guild_id;
        const info = guildInfoQuery.data;
        const name = boundName(workspace, info, manageable, t("unnamedServer"));
        const picker = (
          <ServerPicker
            boundId={boundId}
            guilds={manageable}
            loading={guildsQuery.isLoading}
            failed={guildsQuery.isError}
            onRetry={() => void guildsQuery.refetch()}
            pendingId={bind.isPending ? (bind.variables ?? null) : null}
            error={error}
            onBind={(guildId) => bind.mutate(guildId)}
          />
        );

        return (
          <>
            {boundId ? (
              <>
                <SettingsGrid>
                  <ServerCard
                    workspace={workspace}
                    info={info}
                    name={name}
                    icon={boundIcon(workspace, info, manageable)}
                    onChange={() => {
                      setError(null);
                      setPickerOpen(true);
                    }}
                    onUnlink={() => setUnlinkOpen(true)}
                    unlinking={unlink.isPending}
                  />
                  <AnnouncementsCard workspaceId={workspace.id} announcements={announcements} />
                  <MixesCard workspaceId={workspace.id} mixes={mixes} />
                </SettingsGrid>
                <SaveBar
                  dirty={announcements.dirty || mixes.dirty}
                  summary={saveBarT("changedFields", { count: changedCount })}
                  // Announcements explain their own refusal inside their group.
                  error={mixes.error}
                  saving={announcements.saving || mixes.saving}
                  onDiscard={() => {
                    announcements.discard();
                    mixes.discard();
                  }}
                  onSave={() => {
                    if (announcements.dirty) announcements.save();
                    if (mixes.dirty) mixes.save();
                  }}
                />
              </>
            ) : (
              <SettingGroup id="server" title={t("linkServer")} description={t("linkServerHelp")} immediate>
                {picker}
              </SettingGroup>
            )}

            <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
              <DialogContent className="max-w-xl">
                <DialogHeader>
                  <DialogTitle>{t("changeTitle")}</DialogTitle>
                  <DialogDescription>
                    {t("switchWarning")}
                  </DialogDescription>
                </DialogHeader>
                {picker}
              </DialogContent>
            </Dialog>

            <ConfirmDialog
              open={unlinkOpen}
              onOpenChange={setUnlinkOpen}
              pending={unlink.isPending}
              intent={{
                title: t("unlinkTitle"),
                description: t("unlinkDescription", { name, workspace: workspace.name }),
                confirmLabel: t("unlink"),
                tone: "danger"
              }}
              onConfirm={() => unlink.mutate()}
            />
          </>
        );
      }}
    </WorkspaceSettingsFrame>
  );
}
