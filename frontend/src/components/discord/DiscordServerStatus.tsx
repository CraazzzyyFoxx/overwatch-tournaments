"use client";

import { CheckCircle2, XCircle, Users, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { useDiscordGuildInfo } from "@/hooks/useDiscordEntities";
import { StatusPill } from "@/components/kit/StatusPill";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function DiscordServerStatus({
  workspaceId,
  className,
}: Readonly<{
  workspaceId: number | null | undefined;
  className?: string;
}>) {
  const t = useTranslations("discord.server");
  const { data, isLoading, refetch } = useDiscordGuildInfo(workspaceId);

  if (!workspaceId) return null;

  if (isLoading) {
    return (
      <div className={cn("flex items-center gap-2 text-xs text-muted-foreground", className)}>
        <RefreshCw aria-hidden className="size-3.5 animate-spin motion-reduce:animate-none" />
        <span>{t("checking")}</span>
      </div>
    );
  }

  const isConnected = data?.connected ?? false;
  const name = data?.name || t("fallbackName");

  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-lg border bg-card p-3 text-sm text-card-foreground",
        className
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        <Avatar className="size-8 rounded-full border">
          {data?.icon_url ? <AvatarImage src={data.icon_url} alt="" /> : null}
          <AvatarFallback className="bg-muted text-xs">DC</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 font-medium">
            <span className="truncate">{name}</span>
            {/* Icon plus word, never colour alone. */}
            <StatusPill tone={isConnected ? "success" : "danger"} className="px-1.5 py-0">
              {isConnected ? (
                <CheckCircle2 aria-hidden className="me-1 size-3" />
              ) : (
                <XCircle aria-hidden className="me-1 size-3" />
              )}
              {isConnected ? t("connected") : t("disconnected")}
            </StatusPill>
          </div>
          {data?.member_count ? (
            <div className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
              <Users aria-hidden className="size-3" />
              <span className="tabular-nums">{t("members", { count: data.member_count })}</span>
            </div>
          ) : null}
        </div>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="size-7 shrink-0 text-muted-foreground hover:text-foreground"
        onClick={() => refetch()}
        aria-label={t("refresh")}
        title={t("refresh")}
      >
        <RefreshCw aria-hidden className="size-3.5" />
      </Button>
    </div>
  );
}
