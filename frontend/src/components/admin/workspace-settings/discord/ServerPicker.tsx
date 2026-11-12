"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";
import type { ManageableDiscordGuild } from "@/types/workspace.types";
import { GuildMark } from "./GuildMark";

/**
 * The servers this account administers, each one bindable.
 *
 * Rendered inside the "Link this server" group while nothing is linked and
 * inside the "Change server" dialog afterwards: one list, so the two cannot
 * disagree about which servers are offered or how a refusal reads. Both hosts
 * are already a surface, so the list draws only hairlines between rows.
 */
export function ServerPicker({
  boundId,
  guilds,
  loading,
  failed,
  onRetry,
  pendingId,
  error,
  onBind
}: Readonly<{
  boundId: string | null;
  guilds: ManageableDiscordGuild[];
  loading: boolean;
  failed: boolean;
  /** Re-reads the server list after a failed load. */
  onRetry?: () => void;
  pendingId: string | null;
  error: string | null;
  onBind: (guildId: string) => void;
}>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.discord");
  return (
    <div className="flex flex-col gap-3">
      {loading ? (
        <ul
          aria-busy="true"
          aria-label={t("asking")}
          className="flex flex-col divide-y divide-border/60"
        >
          {[0, 1, 2].map((row) => (
            <li key={row} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
              <Skeleton className="size-9 rounded-lg" />
              <Skeleton className="h-4 w-40" />
            </li>
          ))}
        </ul>
      ) : null}

      {failed ? (
        <PageStateCard
          state="error"
          title={t("unreachable")}
          onAction={onRetry}
          className="border-0 bg-transparent py-6"
        />
      ) : null}

      {/* No administered server is not an error: most often the Discord account
          simply is not linked yet, and the fix is one screen away. */}
      {!loading && !failed && guilds.length === 0 ? (
        <div className="max-w-prose">
          <p className="text-sm">{t("none")}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("linkHelp")}
          </p>
          <Button asChild variant="outline" size="sm" className="mt-3">
            <Link href="/?settings=profile">{t("accountSettings")}</Link>
          </Button>
        </div>
      ) : null}

      {guilds.length > 0 ? (
        <ul className="flex flex-col divide-y divide-border/60">
          {guilds.map((guild) => (
            <li
              key={guild.guild_id}
              className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
            >
              <div className="flex min-w-0 items-center gap-3">
                <GuildMark name={guild.name} src={guild.icon_url} size="md" />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium" title={guild.name}>
                    {guild.name}
                  </p>
                  {guild.owner ? (
                    <p className="text-caption text-muted-foreground">{t("owner")}</p>
                  ) : null}
                </div>
              </div>
              {guild.guild_id === boundId ? (
                <span className="text-caption text-muted-foreground">{t("linked")}</span>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={pendingId !== null}
                  onClick={() => onBind(guild.guild_id)}
                >
                  {pendingId === guild.guild_id ? <Spinner /> : null}
                  {t(boundId ? "linkThisInstead" : "linkServer")}
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
