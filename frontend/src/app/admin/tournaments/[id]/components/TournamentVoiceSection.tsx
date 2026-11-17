"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, RefreshCw } from "lucide-react";

import { DiscordChannelSelect } from "@/components/discord/DiscordChannelSelect";
import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { EmptyNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Combobox, ComboboxCheck } from "@craazzzyyfoxx/admin-kit/ui/combobox";
import { CommandGroup, CommandItem } from "@craazzzyyfoxx/admin-kit/ui/command";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@craazzzyyfoxx/admin-kit/ui/dropdown-menu";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useDiscordRoles } from "@/hooks/useDiscordEntities";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { VoiceSettings } from "@/types/admin.types";
import {
  hasVoiceIssues,
  VoiceChannelList,
  VoiceCounts,
  VoiceIssues,
  VoiceLastSynced
} from "./voice/VoiceChannelList";

interface TournamentVoiceSectionProps {
  tournamentId: number;
  workspaceId: number;
  canUpdateTournament: boolean;
}

/**
 * Voice channels the bot keeps for the tournament (`docs/tournament-voice-channels.md`),
 * as one settings group. Every control saves on its own, like the match-log channel:
 * the switch in the header turns the feature on, and off only after a confirmation,
 * because off is what deletes every channel.
 */
export function TournamentVoiceSection({
  tournamentId,
  workspaceId,
  canUpdateTournament
}: Readonly<TournamentVoiceSectionProps>) {
  const t = useTranslations("adminTournament.voiceSettings");
  const queryClient = useQueryClient();
  const queryKey = adminQueryKeys.tournamentVoice(tournamentId);
  const [disableOpen, setDisableOpen] = useState(false);

  const statusQuery = useQuery({ queryKey, queryFn: () => adminService.getVoice(tournamentId) });
  const status = statusQuery.data;

  const putMutation = useMutation({
    mutationFn: (settings: VoiceSettings) => adminService.putVoice(tournamentId, settings),
    onSuccess: (next) => {
      queryClient.setQueryData(queryKey, next);
      notify.success(t("saved"));
    }
  });
  const syncMutation = useMutation({
    mutationFn: () => adminService.syncVoice(tournamentId),
    onSuccess: (next) => {
      queryClient.setQueryData(queryKey, next);
      notify.success(t("syncRequested"));
    }
  });

  // While a save is in flight the controls show what was asked for; a failed one falls back to the server's.
  const settings = putMutation.isPending ? putMutation.variables : status?.settings;
  const disabled = !canUpdateTournament || putMutation.isPending;
  // Off with nothing made: only the settings, nothing to count or list.
  const inUse = Boolean(settings?.enabled) || (status?.channels.length ?? 0) > 0;
  const save = (patch: Partial<VoiceSettings>) => {
    if (settings) putMutation.mutate({ ...settings, ...patch });
  };

  return (
    <SettingGroup
      id="voice-channels"
      title={t("title")}
      description={t("description")}
      immediate
      actions={
        settings ? (
          <Switch
            id="voice-enabled"
            aria-label={t("enabled")}
            checked={settings.enabled}
            disabled={disabled}
            onCheckedChange={(enabled) => (enabled ? save({ enabled }) : setDisableOpen(true))}
          />
        ) : null
      }
    >
      {!status || !settings ? (
        statusQuery.isError ? (
          <EmptyNote size="sm">{t("loadError")}</EmptyNote>
        ) : (
          <Skeleton className="h-24 w-full" />
        )
      ) : (
        <>
          {inUse || hasVoiceIssues(status) ? (
          <div className="flex flex-col gap-2 py-3 first:pt-0">
            {inUse ? (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <div className="min-w-0 flex-1">
                  <VoiceCounts status={status} />
                  <VoiceLastSynced status={status} />
                </div>
                {canUpdateTournament ? (
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={syncMutation.isPending}
                      onClick={() => syncMutation.mutate()}
                    >
                      <RefreshCw aria-hidden className={syncMutation.isPending ? "animate-spin" : undefined} />
                      {t("sync")}
                    </Button>
                    {!settings.early_teams ? (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant="outline"
                            size="icon"
                            className="size-8"
                            aria-label={t("moreActions")}
                            title={t("moreActions")}
                          >
                            <MoreHorizontal aria-hidden className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem disabled={disabled} onSelect={() => save({ early_teams: true })}>
                            {t("earlyTeams")}
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
            <VoiceIssues status={status} />
          </div>
          ) : null}

          <VoiceSettingsRows workspaceId={workspaceId} settings={settings} disabled={disabled} save={save} />

          {inUse ? (
            <div className="flex flex-col gap-2 py-3 last:pb-0">
              <h3 className="text-sm font-medium">{t("channelsTitle")}</h3>
              <VoiceChannelList status={status} previewCount={6} />
            </div>
          ) : null}
        </>
      )}

      <ConfirmDialog
        open={disableOpen}
        onOpenChange={setDisableOpen}
        onConfirm={() => {
          if (settings) {
            putMutation.mutate({ ...settings, enabled: false }, { onSettled: () => setDisableOpen(false) });
          }
        }}
        pending={putMutation.isPending}
        intent={{
          title: t("deleteTitle"),
          description: t("deleteDescription"),
          confirmLabel: t("deleteConfirm"),
          tone: "danger"
        }}
      />
    </SettingGroup>
  );
}

function VoiceSettingsRows({
  workspaceId,
  settings,
  disabled,
  save
}: Readonly<{
  workspaceId: number;
  settings: VoiceSettings;
  disabled: boolean;
  save: (patch: Partial<VoiceSettings>) => void;
}>) {
  const t = useTranslations("adminTournament.voiceSettings");
  const tc = useTranslations("common");
  const rolesQuery = useDiscordRoles(workspaceId);
  const roles = (rolesQuery.data?.roles ?? []).filter((role) => !role.managed);
  // Roles toggle inside an open popover and save once it closes: one request, not one per click.
  const [roleDraft, setRoleDraft] = useState<string[] | null>(null);
  const roleIds = roleDraft ?? settings.staff_role_ids;
  const staffLabel = roles
    .filter((role) => roleIds.includes(role.id))
    .map((role) => role.name)
    .join(", ");

  return (
    <>
      <SettingRow htmlFor="voice-private" label={t("private")} hint={t("privateHint")}>
        <Switch
          id="voice-private"
          checked={settings.private}
          disabled={disabled}
          onCheckedChange={(next) => save({ private: next })}
        />
      </SettingRow>
      <SettingRow htmlFor="voice-category" label={t("category")} hint={t("categoryHint")}>
        <div className="w-full md:max-w-sm">
          <DiscordChannelSelect
            id="voice-category"
            type="category"
            workspaceId={workspaceId}
            value={settings.category_id ?? ""}
            onChange={(next) => save({ category_id: next === "" ? null : next })}
            disabled={disabled}
            ariaLabel={t("category")}
            placeholder={t("categoryAuto")}
            noneLabel={t("categoryAuto")}
          />
        </div>
      </SettingRow>
      <SettingRow htmlFor="voice-staff-roles" label={t("staffRoles")} hint={t("staffRolesHint")}>
        <div className="w-full md:max-w-sm">
          {roles.length > 0 ? (
            <Combobox
              id="voice-staff-roles"
              label={staffLabel}
              placeholder={t("staffRolesNone")}
              disabled={disabled}
              searchPlaceholder={tc("search")}
              emptyMessage={tc("noResults")}
              onOpenChange={(open) => {
                if (open) {
                  setRoleDraft(settings.staff_role_ids);
                  return;
                }
                if (roleDraft && [...roleDraft].sort().join() !== [...settings.staff_role_ids].sort().join()) {
                  save({ staff_role_ids: roleDraft });
                }
                setRoleDraft(null);
              }}
            >
              <CommandGroup>
                {roles.map((role) => {
                  const selected = roleIds.includes(role.id);
                  return (
                    <CommandItem
                      key={role.id}
                      value={`${role.name} ${role.id}`}
                      onSelect={() =>
                        setRoleDraft(selected ? roleIds.filter((id) => id !== role.id) : [...roleIds, role.id])
                      }
                    >
                      <span className="min-w-0 flex-1 truncate">{role.name}</span>
                      <ComboboxCheck selected={selected} />
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            </Combobox>
          ) : (
            <p className="text-xs text-muted-foreground">
              {rolesQuery.isLoading ? t("rolesLoading") : t("noRoles")}
            </p>
          )}
        </div>
      </SettingRow>
    </>
  );
}
