"use client";

import { useTranslations } from "next-intl";
import { MoreHorizontal, Users } from "lucide-react";

import { SettingGroup } from "@/components/kit/SettingRow";
import { StatusPill } from "@/components/kit/StatusPill";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { DISCORD_CLIENT_ID } from "@/config/site";
import { initials } from "@/lib/utils";
import type { DiscordGuildInfo } from "@/types/discord.types";
import type { Workspace } from "@/types/workspace.types";
import { GuildMark } from "./GuildMark";

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

function OwnerMark({ name, src }: Readonly<{ name: string; src?: string | null }>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.discord");
  const label = t("ownerName", { name });
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
      <Avatar className="size-5 rounded-full border">
        {src ? <AvatarImage src={src} alt="" /> : null}
        <AvatarFallback>{initials(name)}</AvatarFallback>
      </Avatar>
      <span className="truncate" title={label}>
        {label}
      </span>
    </span>
  );
}

/**
 * The bound server: who it is, whether the bot can act in it, and the verbs
 * on it. "Change server" is the everyday action; unlinking and re-inviting the
 * bot are rare enough to live in the overflow menu, except when the bot is
 * missing: then the invite is the one thing that unblocks the page.
 *
 * Every verb here acts at once, never through the section's save bar, so the
 * group says so. Only a failing state is marked: a verified, bot-ready server
 * shows nothing.
 */
export function ServerCard({
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
  const t = useTranslations("adminWorkspace.workspaceSettings.discord");
  const boundId = workspace.discord_guild_id as string;
  const invite = botInviteUrl(boundId);
  // `connected: false` is two different situations and `error` separates
  // them: with an error Discord (or discord-service) was unreachable and the
  // lookup degraded rather than 500ing, which says nothing about the bot;
  // without one, Discord answered and the bot cannot see this guild (it was
  // never invited, or it was kicked).
  const botUnknown = info !== undefined && Boolean(info.error);
  const botMissing = info !== undefined && !info.connected && !info.error;

  return (
    <SettingGroup id="server" title={t("server")} immediate>
      <div className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
        <div className="flex min-w-0 items-center gap-3">
          <GuildMark name={name} src={icon} size="lg" />
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex min-w-0 items-center gap-2">
              <p className="truncate text-ui font-medium text-foreground" title={name}>
                {name}
              </p>
              {workspace.discord_guild_verified_at ? null : (
                <StatusPill tone="warning">{t("ownershipNotVerified")}</StatusPill>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
              {info?.member_count ? (
                <span className="inline-flex items-center gap-1">
                  <Users aria-hidden className="size-3" />
                  <span className="tabular-nums">{info.member_count}</span>
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
            {t("changeServer")}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={t("moreActions")}
                title={t("moreActions")}
              >
                <MoreHorizontal aria-hidden className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {invite && !botMissing ? (
                <DropdownMenuItem asChild>
                  <a href={invite} target="_blank" rel="noopener noreferrer">
                    {t("reinvite")}
                  </a>
                </DropdownMenuItem>
              ) : null}
              <DropdownMenuItem
                variant="destructive"
                disabled={unlinking}
                onSelect={onUnlink}
              >
                {t("unlink")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {botUnknown ? (
        <p className="py-4 text-caption text-muted-foreground last:pb-0">{t("botUnknown")}</p>
      ) : null}

      {botMissing ? (
        <div className="flex flex-wrap items-center gap-3 py-4 last:pb-0">
          <p className="max-w-prose text-caption text-warning">{t("botMissing")}</p>
          {invite ? (
            <Button asChild size="sm">
              <a href={invite} target="_blank" rel="noopener noreferrer">
                {t("addBot")}
              </a>
            </Button>
          ) : null}
        </div>
      ) : null}
    </SettingGroup>
  );
}
