"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { DiscordChannelSelect } from "@/components/discord/DiscordChannelSelect";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { SettingRow } from "@/components/kit/SettingRow";
import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useDiscordRoles } from "@/hooks/useDiscordEntities";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { VoiceSettings, VoiceStatus } from "@/types/admin.types";

const ISSUE_KEYS = ["guild_not_found", "category_not_found", "category_overflow"] as const;
const MISSING_PERMISSION_PREFIX = "missing_permission:";

interface TournamentVoiceSectionProps {
  tournamentId: number;
  workspaceId: number;
  canUpdateTournament: boolean;
}

/**
 * Voice channels the bot keeps for the tournament (`docs/tournament-voice-channels.md`).
 * A resource of its own, like the match-log channel: it saves with its own button,
 * not with the settings form's save bar.
 */
export function TournamentVoiceSection({
  tournamentId,
  workspaceId,
  canUpdateTournament
}: Readonly<TournamentVoiceSectionProps>) {
  const t = useTranslations("adminTournament.voiceSettings");
  const queryClient = useQueryClient();
  const queryKey = adminQueryKeys.tournamentVoice(tournamentId);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const statusQuery = useQuery({ queryKey, queryFn: () => adminService.getVoice(tournamentId) });
  const status = statusQuery.data;

  const refresh = () => queryClient.invalidateQueries({ queryKey });
  const putMutation = useMutation({
    mutationFn: (settings: VoiceSettings) => adminService.putVoice(tournamentId, settings),
    onSuccess: async () => {
      await refresh();
      notify.success(t("saved"));
    }
  });
  const syncMutation = useMutation({
    mutationFn: () => adminService.syncVoice(tournamentId),
    onSuccess: async () => {
      await refresh();
      notify.success(t("syncRequested"));
    }
  });

  if (!status) {
    return statusQuery.isError ? (
      <EmptyNote size="sm">{t("loadError")}</EmptyNote>
    ) : (
      <Skeleton className="h-24 w-full" />
    );
  }

  const settings = status.settings;
  const busy = putMutation.isPending || syncMutation.isPending;

  return (
    <>
      {/* Keyed by the saved settings: a save or refetch resets the draft to what the server holds. */}
      <VoiceForm
        key={JSON.stringify(settings)}
        workspaceId={workspaceId}
        settings={settings}
        canEdit={canUpdateTournament}
        saving={putMutation.isPending}
        onSave={(next) => putMutation.mutate(next)}
      />

      {canUpdateTournament ? (
        <div className="flex flex-wrap gap-2 pt-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => syncMutation.mutate()}
          >
            {t("sync")}
          </Button>
          {!settings.early_teams ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => putMutation.mutate({ ...settings, early_teams: true })}
            >
              {t("earlyTeams")}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="destructive"
            size="sm"
            disabled={busy}
            onClick={() => setDeleteOpen(true)}
          >
            {t("deleteAll")}
          </Button>
        </div>
      ) : null}

      <VoiceStatusPanel status={status} />

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        onConfirm={() =>
          putMutation.mutate({ ...settings, enabled: false }, { onSettled: () => setDeleteOpen(false) })
        }
        pending={putMutation.isPending}
        intent={{
          title: t("deleteTitle"),
          description: t("deleteDescription"),
          confirmLabel: t("deleteConfirm"),
          tone: "danger"
        }}
      />
    </>
  );
}

function VoiceForm({
  workspaceId,
  settings,
  canEdit,
  saving,
  onSave
}: Readonly<{
  workspaceId: number;
  settings: VoiceSettings;
  canEdit: boolean;
  saving: boolean;
  onSave: (settings: VoiceSettings) => void;
}>) {
  const t = useTranslations("adminTournament.voiceSettings");
  const [draft, setDraft] = useState(settings);
  const rolesQuery = useDiscordRoles(workspaceId);
  const roles = (rolesQuery.data?.roles ?? []).filter((role) => !role.managed);
  const disabled = !canEdit || saving;
  const dirty = JSON.stringify(draft) !== JSON.stringify(settings);

  return (
    <>
      <SettingRow htmlFor="voice-enabled" label={t("enabled")} hint={t("enabledHint")}>
        <Switch
          id="voice-enabled"
          checked={draft.enabled}
          disabled={disabled}
          onCheckedChange={(enabled) => setDraft({ ...draft, enabled })}
        />
      </SettingRow>
      <SettingRow htmlFor="voice-private" label={t("private")} hint={t("privateHint")}>
        <Switch
          id="voice-private"
          checked={draft.private}
          disabled={disabled}
          onCheckedChange={(next) => setDraft({ ...draft, private: next })}
        />
      </SettingRow>
      <SettingRow htmlFor="voice-category" label={t("category")} hint={t("categoryHint")}>
        <div className="w-full md:max-w-sm">
          <DiscordChannelSelect
            id="voice-category"
            type="category"
            workspaceId={workspaceId}
            value={draft.category_id ?? ""}
            onChange={(next) => setDraft({ ...draft, category_id: next === "" ? null : next })}
            disabled={disabled}
            ariaLabel={t("category")}
            placeholder={t("categoryAuto")}
            noneLabel={t("categoryAuto")}
          />
        </div>
      </SettingRow>
      <SettingRow label={t("staffRoles")} hint={t("staffRolesHint")}>
        <div className="w-full md:max-w-sm">
          {roles.length > 0 ? (
            <FilterChipGroup label={t("staffRoles")}>
              {roles.map((role) => {
                const pressed = draft.staff_role_ids.includes(role.id);
                return (
                  <FilterChip
                    key={role.id}
                    active={pressed}
                    disabled={disabled}
                    onClick={() =>
                      setDraft({
                        ...draft,
                        staff_role_ids: pressed
                          ? draft.staff_role_ids.filter((id) => id !== role.id)
                          : [...draft.staff_role_ids, role.id]
                      })
                    }
                  >
                    {role.name}
                  </FilterChip>
                );
              })}
            </FilterChipGroup>
          ) : (
            <p className="text-xs text-muted-foreground">
              {rolesQuery.isLoading ? t("rolesLoading") : t("noRoles")}
            </p>
          )}
        </div>
      </SettingRow>
      {canEdit ? (
        <div className="pt-1">
          <Button type="button" size="sm" disabled={!dirty || saving} onClick={() => onSave(draft)}>
            {t("save")}
          </Button>
        </div>
      ) : null}
    </>
  );
}

function VoiceStatusPanel({ status }: Readonly<{ status: VoiceStatus }>) {
  const t = useTranslations("adminTournament.voiceSettings");
  const format = useFormatter();

  const issueLabel = (code: string) => {
    if (code.startsWith(MISSING_PERMISSION_PREFIX)) {
      return t("issues.missing_permission", { permission: code.slice(MISSING_PERMISSION_PREFIX.length) });
    }
    return (ISSUE_KEYS as readonly string[]).includes(code)
      ? t(`issues.${code as (typeof ISSUE_KEYS)[number]}`)
      : code;
  };

  // A team's channel (`team:<id>`) carries the team's name; the warning itself only has the id.
  const teamName = (teamId: number) =>
    status.channels.find((channel) => channel.slot_key === `team:${teamId}`)?.name ??
    t("team", { id: teamId });

  const warningsByTeam = new Map<number | null, string[]>();
  for (const warning of status.warnings) {
    const names = warningsByTeam.get(warning.team_id) ?? [];
    names.push(warning.name ?? t("unnamedPlayer"));
    warningsByTeam.set(warning.team_id, names);
  }

  return (
    <div className="flex flex-col gap-3 pt-4">
      {!status.guild_linked ? (
        <p role="status" className="text-sm text-warning">
          {t("guildNotLinked")}
        </p>
      ) : null}

      {status.sync_issues.length > 0 ? (
        <ul className="flex flex-col gap-1 text-sm text-warning" aria-label={t("issuesTitle")}>
          {status.sync_issues.map((issue) => (
            <li key={`${issue.code}:${issue.detail ?? ""}`}>
              {issueLabel(issue.code)}
              {issue.detail ? ` (${issue.detail})` : ""}
            </li>
          ))}
        </ul>
      ) : null}

      {status.channels.length > 0 ? (
        <ul className="flex flex-col gap-1.5" aria-label={t("channelsTitle")}>
          {status.channels.map((channel) => (
            <li key={channel.slot_key} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted-foreground">{t(`kinds.${channel.kind}`)}</span>
              <span className="font-medium">{channel.name ?? channel.slot_key}</span>
              <StatusPill tone={channel.status === "active" ? "success" : "neutral"}>
                {t(`statuses.${channel.status}`)}
              </StatusPill>
              {channel.discord_channel_id ? (
                <span className="font-mono text-xs text-muted-foreground">
                  {channel.discord_channel_id}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <EmptyNote size="sm">{t("noChannels")}</EmptyNote>
      )}

      {warningsByTeam.size > 0 ? (
        <div className="flex flex-col gap-1 text-sm">
          <p className="font-medium">{t("warningsTitle")}</p>
          <ul className="flex flex-col gap-1 text-muted-foreground">
            {[...warningsByTeam].map(([teamId, names]) => (
              <li key={teamId ?? "none"}>
                {teamId === null ? t("noTeam") : teamName(teamId)}: {names.join(", ")}
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">{t("warningsHint")}</p>
        </div>
      ) : null}

      <p className="text-xs text-muted-foreground">
        {status.last_synced_at
          ? t("lastSynced", { time: format.dateTime(new Date(status.last_synced_at), { dateStyle: "medium", timeStyle: "short" }) })
          : t("neverSynced")}
      </p>
    </div>
  );
}
