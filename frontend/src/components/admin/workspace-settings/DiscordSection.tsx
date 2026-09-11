"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle, LoaderCircle, Users } from "lucide-react";

import { ConfirmDialog } from "@/components/admin/kit/ConfirmDialog";
import { StatusPill } from "@/components/admin/kit/StatusPill";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EYEBROW_CLASS } from "@/components/admin/tone";
import { DiscordChannelSelect } from "@/components/discord/DiscordChannelSelect";
import { useDiscordGuildInfo } from "@/hooks/useDiscordEntities";
import { ApiError, getApiErrorMessage } from "@/lib/api-error";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import workspaceService from "@/services/workspace.service";
import balancerAdminService from "@/services/balancer-admin.service";
import type { DiscordGuildInfo } from "@/types/discord.types";
import type { ManageableDiscordGuild, Workspace } from "@/types/workspace.types";
import { WorkspaceSettingsFrame } from "./WorkspaceSettingsFrame";
import { useWorkspaceSettingsForm } from "./useWorkspaceSettingsForm";

/**
 * The three ways a bind can fail, in the organiser's words.
 *
 * They are genuinely different situations — one is about this account, one is
 * about another workspace, one is about Discord being down — and a single
 * "could not link" toast would send the reader looking in the wrong place for
 * all three. The backend answers 403/409/503 exactly (`verify_discord_guild`),
 * so the status IS the distinction.
 */
const BIND_FAILURES: Record<number, string> = {
  403: "Discord says you no longer administer that server. Ask its owner for Manage Server (or ownership), then try again.",
  409: "Another workspace has already claimed that server. A Discord server belongs to one workspace — ask the platform admins to release it first.",
  503: "Discord could not be reached, so nothing was linked. Try again in a moment."
};

function bindFailure(error: unknown): string {
  const status = error instanceof ApiError ? error.status : 0;
  return BIND_FAILURES[status] ?? getApiErrorMessage(error, "Could not link that Discord server.");
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0]!.charAt(0)}${parts[1]!.charAt(0)}`.toUpperCase();
  }
  return (name.trim().slice(0, 2) || "?").toUpperCase();
}

function GuildMark({
  name,
  src,
  size
}: Readonly<{ name: string; src?: string | null; size: "md" | "lg" }>) {
  return (
    <Avatar
      className={cn(
        "rounded-lg border",
        size === "lg" ? "size-12" : "size-9"
      )}
    >
      {src ? <AvatarImage src={src} alt="" /> : null}
      <AvatarFallback className="rounded-lg bg-muted text-xs font-medium">
        {initials(name)}
      </AvatarFallback>
    </Avatar>
  );
}

function OwnerMark({
  name,
  src
}: Readonly<{ name: string; src?: string | null }>) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
      <Avatar className="size-6 rounded-full border">
        {src ? <AvatarImage src={src} alt="" /> : null}
        <AvatarFallback className="bg-muted text-xs font-medium">
          {initials(name)}
        </AvatarFallback>
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
 * Where every mix in this workspace announces its matchup.
 *
 * The value lives with the rest of the workspace's balancer knobs
 * (`balancer.workspace_config.config_json`), and the upsert rewrites that whole
 * blob -- so the rank-delta knobs are read back and posted along untouched.
 * Same query key as the balancer page's dialog, so both views agree after a save.
 */
function MixChannelCard({ workspaceId }: Readonly<{ workspaceId: number }>) {
  const queryClient = useQueryClient();
  const configQuery = useQuery({
    queryKey: ["workspace-balancer-config", workspaceId],
    queryFn: () => balancerAdminService.getWorkspaceBalancerConfig(workspaceId)
  });
  const config = configQuery.data;
  // The picker speaks in strings and has no null: "" is its no-channel value.
  const channel = config?.mix_discord_channel_id ?? "";

  const save = useMutation({
    mutationFn: (next: string) =>
      balancerAdminService.upsertWorkspaceBalancerConfig(workspaceId, {
        rank_delta_threshold: config?.rank_delta_threshold ?? null,
        rank_delta_hide_from_pool: config?.rank_delta_hide_from_pool ?? false,
        mix_discord_channel_id: next === "" ? null : next
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspace-balancer-config", workspaceId] });
      notify.success("Mix channel saved");
    },
    onError: (cause) => notify.apiError(cause, { title: "Could not save the mix channel" })
  });

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 pt-6">
        <h2 className={EYEBROW_CLASS}>Mix announcements</h2>

        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <DiscordChannelSelect
              workspaceId={workspaceId}
              value={channel}
              onChange={(next) => save.mutate(next)}
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
              onClick={() => save.mutate("")}
            >
              Clear
            </Button>
          ) : null}
        </div>

        <p className="max-w-prose text-xs text-muted-foreground text-pretty">
          Every mix in this workspace posts its matchup here. A single mix can be pointed
          elsewhere from its own settings, but only by a workspace admin -- hosts read the channel,
          they cannot repoint it.
        </p>
      </CardContent>
    </Card>
  );
}

/**
 * The one Discord guild a workspace runs in: patron roles and match-log channels alike.
 *
 * A picker over the servers this account administers, never a free-text ID:
 * binding a guild proves ownership through Discord OAuth server-side, so the
 * guild is not a field the workspace PATCH can set at all. Typing a snowflake
 * you do not administer could only ever produce a 403.
 *
 * Unlinking is a separate verb (`clear_discord_guild`): workspace.update is
 * enough, so an organiser can leave a server they were kicked from.
 */
export function DiscordSection({ workspaceId }: Readonly<{ workspaceId: number | null }>) {
  const settings = useWorkspaceSettingsForm(workspaceId, "discord");
  const { invalidate } = settings;
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [unlinkOpen, setUnlinkOpen] = useState(false);

  const guildsQuery = useQuery({
    queryKey: ["me", "discord-guilds"],
    queryFn: () => workspaceService.myDiscordGuilds(),
    retry: false
  });
  const guildInfoQuery = useDiscordGuildInfo(workspaceId, Boolean(workspaceId));

  const refresh = () => {
    invalidate();
    if (workspaceId !== null) {
      queryClient.invalidateQueries({ queryKey: ["workspace", workspaceId, "discord"] });
    }
  };

  const bind = useMutation({
    mutationFn: (guildId: string) =>
      workspaceService.verifyDiscordGuild(workspaceId as number, guildId),
    onSuccess: () => {
      setError(null);
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
        const icon = boundIcon(workspace, info, manageable);
        const ownerName = info?.owner_name ?? null;
        const ownerAvatar = info?.owner_avatar_url ?? null;

        return (
          <>
            <Card>
              <CardContent className="flex flex-col gap-4 pt-6">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className={EYEBROW_CLASS}>Linked server</h2>
                  {boundId ? (
                    workspace.discord_guild_verified_at ? (
                      <StatusPill tone="success">
                        <CheckCircle aria-hidden className="size-3" />
                        Ownership verified
                      </StatusPill>
                    ) : (
                      <StatusPill tone="warning">
                        <AlertTriangle aria-hidden className="size-3" />
                        Not verified
                      </StatusPill>
                    )
                  ) : null}
                </div>

                {boundId ? (
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <GuildMark name={name} src={icon} size="lg" />
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium" title={name}>
                          {name}
                        </p>
                        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                          {info?.member_count ? (
                            <span className="inline-flex items-center gap-1">
                              <Users aria-hidden className="size-3" />
                              <span className="tabular-nums">
                                {info.member_count === 1
                                  ? "1 member"
                                  : `${info.member_count} members`}
                              </span>
                            </span>
                          ) : null}
                          <span className="break-all font-mono">{boundId}</span>
                        </div>
                        {ownerName ? (
                          <div className="mt-1.5">
                            <OwnerMark name={ownerName} src={ownerAvatar} />
                          </div>
                        ) : null}
                      </div>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      className="text-danger"
                      disabled={unlink.isPending}
                      onClick={() => setUnlinkOpen(true)}
                    >
                      Unlink server
                    </Button>
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No Discord server linked yet.</p>
                )}

                <p className="max-w-prose text-xs text-muted-foreground text-pretty">
                  The server this workspace runs in: where Boosty&apos;s bot assigns subscriber
                  roles and where match-log channels live.
                </p>
              </CardContent>
            </Card>

            {/* Channels come from the linked guild, so there is nothing to pick
                until one is bound. */}
            {boundId ? <MixChannelCard workspaceId={workspace.id} /> : null}

            <Card>
              <CardContent className="flex flex-col gap-4 pt-6">
                <h2 className={EYEBROW_CLASS}>Your servers</h2>

                {guildsQuery.isLoading ? (
                  <p className="flex items-center gap-2 text-sm text-muted-foreground">
                    <LoaderCircle
                      aria-hidden
                      className="size-4 animate-spin motion-reduce:animate-none"
                    />
                    Asking Discord which servers you administer…
                  </p>
                ) : null}

                {guildsQuery.isError ? (
                  <p className="max-w-prose text-sm text-danger">
                    Discord could not be reached, so your servers could not be listed. Try again in
                    a moment.
                  </p>
                ) : null}

                {/* No administered server is not an error — most often the
                    Discord account simply is not linked yet, and the fix is one
                    screen away rather than on this one. */}
                {!guildsQuery.isLoading && !guildsQuery.isError && manageable.length === 0 ? (
                  <div className="max-w-prose rounded-lg border border-dashed border-border p-4">
                    <p className="text-sm">
                      You do not administer any Discord server that this account can see.
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Link your Discord account (or reconnect it, so the server list is fresh) in
                      account settings, then come back. You need to own the server or have Manage
                      Server on it.
                    </p>
                    <Button asChild variant="outline" size="sm" className="mt-3">
                      <Link href="/?settings=profile">Open account settings</Link>
                    </Button>
                  </div>
                ) : null}

                {manageable.length > 0 ? (
                  <ul className="flex flex-col gap-2">
                    {manageable.map((guild) => {
                      const isBound = guild.guild_id === boundId;
                      return (
                        <li
                          key={guild.guild_id}
                          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-3"
                        >
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
                          {isBound ? (
                            <StatusPill tone="success">
                              <CheckCircle aria-hidden className="size-3" />
                              Linked
                            </StatusPill>
                          ) : (
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={bind.isPending}
                              onClick={() => bind.mutate(guild.guild_id)}
                            >
                              {bind.isPending && bind.variables === guild.guild_id ? (
                                <LoaderCircle
                                  aria-hidden
                                  className="size-4 animate-spin motion-reduce:animate-none"
                                />
                              ) : null}
                              {boundId ? "Link this instead" : "Link this server"}
                            </Button>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                ) : null}

                {error ? (
                  <p role="alert" className="max-w-prose text-sm font-medium text-danger">
                    {error}
                  </p>
                ) : null}
              </CardContent>
            </Card>

            <ConfirmDialog
              open={unlinkOpen}
              onOpenChange={setUnlinkOpen}
              pending={unlink.isPending}
              intent={{
                title: "Unlink Discord server",
                description: `${name} stops serving ${workspace.name} the moment you confirm — Boosty subscriber roles and match-log channels have nowhere to go. You can link a server again later.`,
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
