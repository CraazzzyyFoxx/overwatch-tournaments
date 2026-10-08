"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle, HelpCircle, MoreHorizontal, Users } from "lucide-react";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { SettingGroup, SettingRow } from "@/components/kit/SettingRow";
import { StatusPill } from "@/components/kit/StatusPill";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { toggleVariants } from "@/components/ui/toggle";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { DiscordChannelSelect } from "@/components/discord/DiscordChannelSelect";
import { DISCORD_CLIENT_ID } from "@/config/site";
import { useDiscordChannels, useDiscordGuildInfo } from "@/hooks/useDiscordEntities";
import { ApiError, getApiErrorMessage } from "@/lib/api/error";
import { notificationQueryKeys } from "@/lib/notifications/query-keys";
import { notify } from "@/lib/notify";
import { cn, initials } from "@/lib/utils";
import notificationService from "@/services/notification.service";
import workspaceService from "@/services/workspace.service";
import balancerAdminService from "@/services/balancer-admin.service";
import type { DiscordGuildInfo, DiscordVoicePermission } from "@/types/discord.types";
import type { WorkspaceBalancerConfigUpsert } from "@/types/balancer-admin.types";
import type { NotificationWorkspaceConfigUpdate } from "@/types/notification.types";
import type { ManageableDiscordGuild, Workspace } from "@/types/workspace.types";
import { Spinner } from "@/components/ui/spinner";
import { WorkspaceSettingsFrame } from "./WorkspaceSettingsFrame";
import { useWorkspaceSettingsForm } from "./useWorkspaceSettingsForm";
import { balancerQueryKeys } from "@/lib/balancer/query-keys";
import { userQueryKeys } from "@/lib/users/query-keys";
import { workspaceQueryKeys } from "@/lib/workspace/query-keys";

/**
 * The three ways a bind can fail, in the organiser's words.
 *
 * They are genuinely different situations (one is about this account, one is
 * about another workspace, one is about Discord being down) and a single
 * "could not link" toast would send the reader looking in the wrong place for
 * all three. The backend answers 403/409/503 exactly (`verify_discord_guild`),
 * so the status IS the distinction.
 */
const BIND_FAILURES: Record<number, string> = {
  403: "Discord says you no longer administer that server. Ask its owner for Manage Server (or ownership), then try again.",
  409: "Another workspace has already claimed that server. A Discord server belongs to one workspace, so ask the platform admins to release it first.",
  503: "Discord could not be reached, so nothing was linked. Try again in a moment."
};

function bindFailure(error: unknown): string {
  const status = error instanceof ApiError ? error.status : 0;
  return BIND_FAILURES[status] ?? getApiErrorMessage(error, "Could not link that Discord server.");
}

// Exactly what the bot does, and nothing else:
//   View Channels 1024 + Read Message History 65536 — ingesting match logs
//     (`attachment_processor.process_channel_history`),
//   Add Reactions 64 — the ✅/❌ it puts on each log it processed,
//   Send Messages 2048 + Embed Links 16384 + Attach Files 32768 — the mix
//     announcement, posted as `content` + `embed` + `file` in one call
//     (`discord-service/src/rabbit/gateway.py` `post_message`); drop either of
//     the last two and that post 403s with only a log line to show for it.
//   Connect 1048576 + Move Members 16777216 — moving mix players between voice
//     channels (`discord-service/src/services/voice.py`).
// It never writes roles — subscription sync only READS a member's roles — so
// Manage Roles is deliberately absent: every bit shows up on Discord's consent
// screen, and one that is never used is just a reason to refuse the install.
const BOT_PERMISSIONS = "17943616";

/**
 * Discord's install link for our bot, pre-pointed at the bound guild.
 *
 * `scope=bot` alone: the bot registers no slash commands. `guild_id` +
 * `disable_guild_select` mean the organiser confirms the server they already
 * linked here instead of picking one again — a mismatch between the two is the
 * whole failure mode this button exists to prevent.
 *
 * Null when no application id was built in: a link with an empty `client_id`
 * only reaches Discord's "invalid application" page.
 */
function botInviteUrl(guildId: string): string | null {
  if (!DISCORD_CLIENT_ID) return null;
  const params = new URLSearchParams({
    client_id: DISCORD_CLIENT_ID,
    scope: "bot",
    permissions: BOT_PERMISSIONS,
    guild_id: guildId,
    disable_guild_select: "true"
  });
  return `https://discord.com/oauth2/authorize?${params.toString()}`;
}

function GuildMark({
  name,
  src,
  size
}: Readonly<{ name: string; src?: string | null; size: "md" | "lg" }>) {
  return (
    <Avatar className={cn("rounded-lg border", size === "lg" ? "size-12" : "size-9")}>
      {src ? <AvatarImage src={src} alt="" /> : null}
      <AvatarFallback className="rounded-lg bg-muted text-xs font-medium">
        {initials(name)}
      </AvatarFallback>
    </Avatar>
  );
}

function OwnerMark({ name, src }: Readonly<{ name: string; src?: string | null }>) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
      <Avatar className="size-5 rounded-full border">
        {src ? <AvatarImage src={src} alt="" /> : null}
        <AvatarFallback className="bg-muted text-[10px] font-medium">{initials(name)}</AvatarFallback>
      </Avatar>
      <span className="truncate" title={name}>
        Owner · <span className="text-foreground">{name}</span>
      </span>
    </span>
  );
}

function boundName(
  workspace: Workspace,
  info: DiscordGuildInfo | undefined,
  picker: ManageableDiscordGuild[]
): string {
  if (info?.name) return info.name;
  const fromPicker = picker.find((guild) => guild.guild_id === workspace.discord_guild_id);
  return fromPicker?.name ?? "Discord server";
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
 * The servers this account administers, each one bindable.
 *
 * Rendered inline while nothing is linked and inside the "Change server"
 * dialog afterwards: one list, so the two cannot disagree about which servers
 * are offered or how a refusal reads.
 */
function ServerPicker({
  boundId,
  guilds,
  loading,
  failed,
  pendingId,
  error,
  onBind
}: Readonly<{
  boundId: string | null;
  guilds: ManageableDiscordGuild[];
  loading: boolean;
  failed: boolean;
  pendingId: string | null;
  error: string | null;
  onBind: (guildId: string) => void;
}>) {
  return (
    <div className="flex flex-col gap-3">
      {loading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner />
          Asking Discord which servers you administer…
        </p>
      ) : null}

      {failed ? (
        <p className="max-w-prose text-sm text-danger">
          Discord could not be reached, so your servers could not be listed. Try again in a moment.
        </p>
      ) : null}

      {/* No administered server is not an error: most often the Discord account
          simply is not linked yet, and the fix is one screen away. */}
      {!loading && !failed && guilds.length === 0 ? (
        <div className="max-w-prose rounded-lg border border-dashed border-border p-4">
          <p className="text-sm">You do not administer any Discord server that this account can see.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Link your Discord account (or reconnect it, so the server list is fresh) in account
            settings, then come back. You need to own the server or have Manage Server on it.
          </p>
          <Button asChild variant="outline" size="sm" className="mt-3">
            <Link href="/?settings=profile">Open account settings</Link>
          </Button>
        </div>
      ) : null}

      {guilds.length > 0 ? (
        <ul className="flex flex-col divide-y divide-border/60 rounded-lg border border-border">
          {guilds.map((guild) => (
            <li key={guild.guild_id} className="flex flex-wrap items-center justify-between gap-3 p-3">
              <div className="flex min-w-0 items-center gap-3">
                <GuildMark name={guild.name} src={guild.icon_url} size="md" />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium" title={guild.name}>
                    {guild.name}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {guild.owner ? "You own this server" : "Manage Server"}
                  </p>
                </div>
              </div>
              {guild.guild_id === boundId ? (
                <StatusPill tone="success">
                  <CheckCircle aria-hidden className="size-3" />
                  Linked
                </StatusPill>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={pendingId !== null}
                  onClick={() => onBind(guild.guild_id)}
                >
                  {pendingId === guild.guild_id ? <Spinner /> : null}
                  {boundId ? "Link this instead" : "Link this server"}
                </Button>
              )}
            </li>
          ))}
        </ul>
      ) : null}

      {error ? (
        <p role="alert" className="max-w-prose text-sm font-medium text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/**
 * The bound server: who it is, whether the bot can act in it, and the verbs
 * on it. "Change server" is the everyday action; unlinking and re-inviting the
 * bot are rare enough to live in the overflow menu, except when the bot is
 * missing — then the invite is the one thing that unblocks the page.
 */
function ServerCard({
  workspace,
  info,
  name,
  icon,
  onChange,
  onUnlink,
  unlinking
}: Readonly<{
  workspace: Workspace;
  info: DiscordGuildInfo | undefined;
  name: string;
  icon: string | null | undefined;
  onChange: () => void;
  onUnlink: () => void;
  unlinking: boolean;
}>) {
  const boundId = workspace.discord_guild_id as string;
  const invite = botInviteUrl(boundId);
  // `connected: false` is two different situations and `error` separates
  // them: with an error Discord (or discord-service) was unreachable and the
  // lookup degraded rather than 500ing, which says nothing about the bot;
  // without one, Discord answered and the bot cannot see this guild — it was
  // never invited, or it was kicked.
  const botUnknown = info !== undefined && Boolean(info.error);
  const botMissing = info !== undefined && !info.connected && !info.error;
  const botPresent = info?.connected === true;

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 pt-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <GuildMark name={name} src={icon} size="lg" />
            <div className="flex min-w-0 flex-col gap-1">
              <p className="truncate text-base font-semibold" title={name}>
                {name}
              </p>
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                {info?.member_count ? (
                  <span className="inline-flex items-center gap-1">
                    <Users aria-hidden className="size-3" />
                    <span className="tabular-nums">
                      {info.member_count === 1 ? "1 member" : `${info.member_count} members`}
                    </span>
                  </span>
                ) : null}
                <span className="break-all font-mono">{boundId}</span>
              </div>
              {info?.owner_name ? (
                <OwnerMark name={info.owner_name} src={info.owner_avatar_url} />
              ) : null}
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <Button type="button" variant="outline" size="sm" onClick={onChange}>
              Change server
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button type="button" variant="ghost" size="icon" aria-label="More server actions">
                  <MoreHorizontal aria-hidden className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {invite && !botMissing ? (
                  <DropdownMenuItem asChild>
                    <a href={invite} target="_blank" rel="noopener noreferrer">
                      Re-invite bot
                    </a>
                  </DropdownMenuItem>
                ) : null}
                <DropdownMenuItem
                  className="text-danger focus:text-danger"
                  disabled={unlinking}
                  onSelect={onUnlink}
                >
                  Unlink server
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {workspace.discord_guild_verified_at ? (
            <StatusPill tone="success">
              <CheckCircle aria-hidden className="size-3" />
              Ownership verified
            </StatusPill>
          ) : (
            <StatusPill tone="warning">
              <AlertTriangle aria-hidden className="size-3" />
              Ownership not verified
            </StatusPill>
          )}
          {botPresent ? (
            <StatusPill tone="success">
              <CheckCircle aria-hidden className="size-3" />
              Bot in server
            </StatusPill>
          ) : null}
          {botMissing ? (
            <StatusPill tone="warning">
              <AlertTriangle aria-hidden className="size-3" />
              Bot not in server
            </StatusPill>
          ) : null}
          {botUnknown ? (
            <StatusPill tone="neutral">
              <HelpCircle aria-hidden className="size-3" />
              Bot status unknown
            </StatusPill>
          ) : null}
        </div>

        {botMissing ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-warning/30 bg-warning/10 p-3">
            <p className="max-w-prose text-sm text-warning">
              The bot is not in this server, so it cannot read match logs, post announcements or
              move mix players. Add it, then reload this page.
            </p>
            {invite ? (
              <Button asChild size="sm">
                <a href={invite} target="_blank" rel="noopener noreferrer">
                  Add bot to server
                </a>
              </Button>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

/**
 * Human names for the kinds the server offers. The list itself comes from the
 * server (`broadcastable_kinds`), so a kind added there appears here without a
 * release: unnamed, but never missing.
 */
const KIND_LABELS: Record<string, string> = {
  "registration.opened": "Registration opened",
  "check_in.opened": "Check-in opened",
  "encounter.scheduled": "Match scheduled"
};

const LOCALES = [
  { value: "ru", label: "Russian" },
  { value: "en", label: "English" }
] as const;

/**
 * The three ways an announcement save can fail, in the organiser's words: a
 * guild that was unlinked since the page loaded, Discord being unreachable,
 * and whatever the server said about the channel are three different fixes.
 */
function announcementFailure(error: unknown): string {
  const status = error instanceof ApiError ? error.status : 0;
  if (status === 409) {
    return "This workspace no longer has a linked Discord server, so there is no channel to post in. Reload the page and link one.";
  }
  if (status === 503) {
    return "Discord could not be reached, so the channel could not be checked. Nothing was saved; try again in a moment.";
  }
  return getApiErrorMessage(error, "Could not save the announcement settings.");
}

/**
 * Where tournament events are announced, which of them, and in what language.
 *
 * Saves on every change like the rest of this page: each field stands on its
 * own, and a draft-and-save bar beside controls that save instantly is how an
 * edit gets left behind. The body is always all three fields, because that is
 * what the RPC takes.
 */
function AnnouncementsCard({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const configQuery = useQuery({
    queryKey: notificationQueryKeys.workspaceConfig(workspaceId),
    queryFn: () => notificationService.workspaceConfig(workspaceId)
  });
  const config = configQuery.data;

  const save = useMutation({
    mutationFn: (body: NotificationWorkspaceConfigUpdate) =>
      notificationService.updateWorkspaceConfig(workspaceId, body),
    onSuccess: (saved) => {
      setError(null);
      queryClient.setQueryData(notificationQueryKeys.workspaceConfig(workspaceId), saved);
      notify.success("Announcement settings saved");
    },
    onError: (cause) => {
      setError(announcementFailure(cause));
      notify.apiError(cause, { title: "Could not save the announcement settings" });
    }
  });

  const update = (partial: Partial<NotificationWorkspaceConfigUpdate>) => {
    if (!config) return;
    save.mutate({
      discord_channel_id: config.discord_channel_id,
      locale: config.locale,
      broadcast_kinds: config.broadcast_kinds,
      ...partial
    });
  };

  return (
    <Card id="announcements">
      <CardContent className="pt-6">
        <SettingGroup title="Tournament announcements">
          {!config ? (
            <p className="py-2 text-sm text-muted-foreground">
              {configQuery.isError
                ? "The announcement settings failed to load. Reload the page."
                : "Loading announcement settings…"}
            </p>
          ) : (
            <>
              <SettingRow
                label="Channel"
                hint="With no channel the bot posts nothing. Hidden tournaments never reach it."
              >
                <div className="flex w-full items-center gap-2 md:max-w-sm">
                  <div className="min-w-0 flex-1">
                    <DiscordChannelSelect
                      workspaceId={workspaceId}
                      // The picker has no null: "" is its no-channel value.
                      value={config.discord_channel_id ?? ""}
                      onChange={(next) => update({ discord_channel_id: next === "" ? null : next })}
                      disabled={save.isPending}
                      ariaLabel="Announcement Discord channel"
                      placeholder="No channel"
                    />
                  </div>
                  {config.discord_channel_id ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={save.isPending}
                      onClick={() => update({ discord_channel_id: null })}
                    >
                      Clear
                    </Button>
                  ) : null}
                </div>
              </SettingRow>

              <SettingRow
                label="Events"
                hint="Match scheduled is one post per match, so it is off by default."
              >
                <div className="flex flex-col gap-2">
                  {config.broadcastable_kinds.map((kind) => {
                    const id = `broadcast-${kind}`;
                    const checked = config.broadcast_kinds.includes(kind);
                    return (
                      <div key={kind} className="flex items-center gap-2">
                        <Checkbox
                          id={id}
                          checked={checked}
                          disabled={save.isPending}
                          onCheckedChange={(next) =>
                            update({
                              broadcast_kinds:
                                next === true
                                  ? [...config.broadcast_kinds, kind]
                                  : config.broadcast_kinds.filter((entry) => entry !== kind)
                            })
                          }
                        />
                        <Label htmlFor={id} className="text-sm font-normal">
                          {KIND_LABELS[kind] ?? kind}
                        </Label>
                      </div>
                    );
                  })}
                </div>
              </SettingRow>

              <SettingRow
                htmlFor="announcement-locale"
                label="Language"
                hint="Times render in each reader's own timezone, whatever the language."
              >
                <Select
                  value={config.locale}
                  onValueChange={(next) => update({ locale: next as "ru" | "en" })}
                  disabled={save.isPending}
                >
                  <SelectTrigger id="announcement-locale" className="w-full md:w-40">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LOCALES.map((locale) => (
                      <SelectItem key={locale.value} value={locale.value}>
                        {locale.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </SettingRow>
            </>
          )}
        </SettingGroup>

        {error ? (
          <p role="alert" className="mt-3 max-w-prose text-sm font-medium text-danger">
            {error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

const VOICE_PERMISSION_LABELS: Record<DiscordVoicePermission, string> = {
  view_channel: "View Channel",
  connect: "Connect",
  move_members: "Move Members"
};

function missingLabel(missing: DiscordVoicePermission[] | null | undefined): string | null {
  if (!missing || missing.length === 0) return null;
  return missing.map((name) => VOICE_PERMISSION_LABELS[name]).join(", ");
}

/**
 * Where every mix in this workspace announces its matchup, the voice category
 * it moves players through, and which of its voices players wait in.
 *
 * All three live in `balancer.workspace_config.config_json`, and the upsert
 * rewrites that whole blob, so every save posts every key (rank-delta knobs
 * included) with only the changed ones replaced. Same query key as the
 * balancer page's dialog, so both views agree after a save.
 */
function MixesCard({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const queryClient = useQueryClient();
  const configQuery = useQuery({
    queryKey: balancerQueryKeys.workspaceConfig(workspaceId),
    queryFn: () => balancerAdminService.getWorkspaceBalancerConfig(workspaceId)
  });
  const channelsQuery = useDiscordChannels(workspaceId);
  const config = configQuery.data;
  // The pickers speak in strings and have no null: "" is their empty value.
  const channel = config?.mix_discord_channel_id ?? "";
  const categoryId = config?.mix_voice_category_id ?? "";
  const generalIds = config?.mix_general_voice_channel_ids ?? [];

  const channels = channelsQuery.data?.channels ?? [];
  const categories = channels.filter((item) => item.type === "category");
  const category = categories.find((item) => item.id === categoryId);
  // A voice outside the category is not offered: the move would take a player
  // out of the mix's own corner of the server.
  const voices = channels.filter(
    (item) => item.type === "voice" && item.category_id === categoryId
  );
  const lacking = voices.flatMap((voice) => {
    const missing = missingLabel(voice.missing_permissions);
    return missing ? [`${voice.name}: ${missing}`] : [];
  });

  const save = useMutation({
    mutationFn: (partial: Partial<WorkspaceBalancerConfigUpsert>) =>
      balancerAdminService.upsertWorkspaceBalancerConfig(workspaceId, {
        rank_delta_threshold: config?.rank_delta_threshold ?? null,
        rank_delta_hide_from_pool: config?.rank_delta_hide_from_pool ?? false,
        mix_discord_channel_id: config?.mix_discord_channel_id ?? null,
        mix_voice_category_id: config?.mix_voice_category_id ?? null,
        mix_general_voice_channel_ids: config?.mix_general_voice_channel_ids ?? [],
        ...partial
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: balancerQueryKeys.workspaceConfig(workspaceId) });
      notify.success("Mix settings saved");
    },
    onError: (cause) => notify.apiError(cause, { title: "Could not save the mix settings" })
  });

  const busy = configQuery.isLoading || channelsQuery.isLoading || save.isPending;
  const categoryMissing = missingLabel(category?.missing_permissions);

  return (
    <Card>
      <CardContent className="pt-6">
        <SettingGroup title="Mixes">
          <SettingRow
            label="Announcement channel"
            hint="Every mix posts its matchup here. A workspace admin can point a single mix elsewhere."
          >
            <div className="flex w-full items-center gap-2 md:max-w-sm">
              <div className="min-w-0 flex-1">
                <DiscordChannelSelect
                  workspaceId={workspaceId}
                  value={channel}
                  onChange={(next) => save.mutate({ mix_discord_channel_id: next === "" ? null : next })}
                  disabled={configQuery.isLoading || save.isPending}
                  ariaLabel="Mix Discord channel"
                  placeholder="No channel"
                />
              </div>
              {channel ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={save.isPending}
                  onClick={() => save.mutate({ mix_discord_channel_id: null })}
                >
                  Clear
                </Button>
              ) : null}
            </div>
          </SettingRow>

          <SettingRow
            label="Voice category"
            hint="Mixes move each team into a voice of this category. The bot needs View Channel, Connect and Move Members on it."
          >
            <div className="flex w-full flex-col gap-1 md:max-w-sm">
              <div className="flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  <Select
                    value={categoryId}
                    // A new category invalidates the old general voices: they
                    // belong to the category that is being left behind.
                    onValueChange={(next) =>
                      save.mutate({
                        mix_voice_category_id: next === "" ? null : next,
                        mix_general_voice_channel_ids: []
                      })
                    }
                    disabled={busy}
                  >
                    <SelectTrigger aria-label="Mix voice category">
                      <SelectValue placeholder="No voice category" />
                    </SelectTrigger>
                    <SelectContent>
                      {categories.map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {categoryId !== "" ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={save.isPending}
                    onClick={() =>
                      save.mutate({ mix_voice_category_id: null, mix_general_voice_channel_ids: [] })
                    }
                  >
                    Clear
                  </Button>
                ) : null}
              </div>
              {categoryMissing ? (
                <p className="text-xs text-warning">Missing: {categoryMissing}</p>
              ) : null}
            </div>
          </SettingRow>

          {categoryId !== "" ? (
            <SettingRow
              label="General voices"
              hint="Players wait in these. Every other voice in the category is a team voice."
            >
              <div className="flex w-full flex-col gap-2 md:max-w-sm">
                {voices.length > 0 ? (
                  <div role="group" aria-label="General voices" className="flex flex-wrap gap-1.5">
                    {voices.map((voice) => {
                      const pressed = generalIds.includes(voice.id);
                      const missing = missingLabel(voice.missing_permissions);
                      return (
                        <button
                          key={voice.id}
                          type="button"
                          aria-pressed={pressed}
                          data-state={pressed ? "on" : "off"}
                          disabled={busy}
                          onClick={() =>
                            save.mutate({
                              mix_general_voice_channel_ids: pressed
                                ? generalIds.filter((id) => id !== voice.id)
                                : [...generalIds, voice.id]
                            })
                          }
                          title={missing ? `Missing: ${missing}` : undefined}
                          className={cn(
                            toggleVariants({ variant: "outline", size: "sm" }),
                            "rounded-full active:scale-[0.98]",
                            pressed && "border-primary/50"
                          )}
                        >
                          {pressed ? <CheckCircle aria-hidden className="size-3.5" /> : null}
                          {voice.name}
                          {missing ? (
                            <AlertTriangle aria-hidden className="size-3.5 text-warning" />
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {channelsQuery.isLoading
                      ? "Loading voice channels…"
                      : "This category has no voice channels yet."}
                  </p>
                )}
                {lacking.length > 0 ? (
                  <p className="text-xs text-warning">Missing on {lacking.join("; ")}</p>
                ) : null}
              </div>
            </SettingRow>
          ) : null}
        </SettingGroup>
      </CardContent>
    </Card>
  );
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
 */
export function DiscordSection({ workspaceId }: Readonly<{ workspaceId: number | null }>) {
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
      notify.success("Discord server linked");
    },
    onError: (cause) => {
      setError(bindFailure(cause));
      notify.apiError(cause, { title: "Could not link that Discord server" });
    }
  });

  const unlink = useMutation({
    mutationFn: () => workspaceService.clearDiscordGuild(workspaceId as number),
    onSuccess: () => {
      setUnlinkOpen(false);
      setError(null);
      refresh();
      notify.success("Discord server unlinked");
    },
    onError: (cause) => {
      notify.apiError(cause, { title: "Could not unlink that Discord server" });
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
        const name = boundName(workspace, info, manageable);
        const picker = (
          <ServerPicker
            boundId={boundId}
            guilds={manageable}
            loading={guildsQuery.isLoading}
            failed={guildsQuery.isError}
            pendingId={bind.isPending ? (bind.variables ?? null) : null}
            error={error}
            onBind={(guildId) => bind.mutate(guildId)}
          />
        );

        return (
          <>
            {boundId ? (
              <>
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
                {/* Channels come from the linked guild, so there is nothing to
                    pick until one is bound. */}
                <AnnouncementsCard workspaceId={workspace.id} />
                <MixesCard workspaceId={workspace.id} />
              </>
            ) : (
              <Card>
                <CardContent className="flex flex-col gap-4 pt-6">
                  <div>
                    <h2 className={EYEBROW_CLASS}>Link a server</h2>
                    <p className="mt-1 max-w-prose text-sm text-muted-foreground">
                      Pick the Discord server this workspace runs in. Announcements and mixes are
                      set up once it is linked.
                    </p>
                  </div>
                  {picker}
                </CardContent>
              </Card>
            )}

            <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
              <DialogContent className="max-w-xl">
                <DialogHeader>
                  <DialogTitle>Change server</DialogTitle>
                  <DialogDescription>
                    Channels picked for announcements and mixes belong to the current server and
                    stop working after a switch.
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
                title: "Unlink Discord server",
                description: `${name} stops serving ${workspace.name} the moment you confirm. Boosty subscriber roles, match logs, announcements and mixes have nowhere to go until you link a server again.`,
                confirmLabel: "Unlink server",
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
