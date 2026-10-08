"use client";

import React from "react";
import { Hash } from "lucide-react";
import { useTranslations } from "next-intl";

import { useDiscordChannels } from "@/hooks/useDiscordEntities";
import { DiscordChannel } from "@/types/discord.types";

import { DiscordEntitySelect } from "./DiscordEntitySelect";

export interface DiscordChannelSelectProps {
  workspaceId: number | null | undefined;
  value: string;
  onChange: (channelId: string) => void;
  onChannelNameSelected?: (channelName: string) => void;
  disabled?: boolean;
  placeholder?: string;
  /** Accessible name for the manual ID field, which has no visible label. */
  ariaLabel?: string;
  /** Id of the visible label, when there is one. */
  id?: string;
  className?: string;
}

export function DiscordChannelSelect({
  workspaceId,
  value,
  onChange,
  onChannelNameSelected,
  disabled,
  placeholder,
  ariaLabel,
  id,
  className
}: Readonly<DiscordChannelSelectProps>) {
  const t = useTranslations("discord.channel");
  const { data, isLoading, refetch } = useDiscordChannels(workspaceId);
  const [manualMode, setManualMode] = React.useState(false);
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");

  // Every picker that uses this posts messages: voices and categories are not targets.
  const channels: DiscordChannel[] = (data?.channels ?? []).filter((channel) => channel.type === "text");
  const hasChannels = channels.length > 0;
  const selected = channels.find((channel) => channel.id === value);

  const groups = React.useMemo(() => {
    const grouped = new Map<string, DiscordChannel[]>();
    for (const channel of channels) {
      const category = channel.category_name || t("uncategorized");
      const bucket = grouped.get(category);
      if (bucket) bucket.push(channel);
      else grouped.set(category, [channel]);
    }
    return [...grouped].map(([heading, entities]) => ({ heading, entities }));
  }, [channels, t]);

  const pick = (channel: DiscordChannel) => {
    onChange(channel.id);
    onChannelNameSelected?.(channel.name);
    setOpen(false);
    setSearch("");
  };

  return (
    <DiscordEntitySelect
      size="default"
      id={id}
      value={value}
      onChange={onChange}
      disabled={disabled}
      placeholder={placeholder}
      ariaLabel={ariaLabel}
      className={className}
      isLoading={isLoading}
      hasEntities={hasChannels}
      onRefetch={() => refetch()}
      manualMode={manualMode}
      onManualModeChange={setManualMode}
      open={open}
      onOpenChange={setOpen}
      search={search}
      onSearchChange={setSearch}
      groups={groups}
      selected={selected}
      onPick={pick}
      renderOption={(channel) => (
        <span className="flex min-w-0 flex-1 items-center gap-1.5">
          <Hash aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate font-medium">{channel.name}</span>
        </span>
      )}
      renderSelectedLabel={(channel) => (
        <span className="flex items-center gap-1.5 truncate">
          <Hash aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate">{channel.name}</span>
        </span>
      )}
      labels={{
        loading: t("loading"),
        dropdown: t("dropdown"),
        idAria: t("idAria"),
        placeholder: t("placeholder"),
        searchPlaceholder: t("searchPlaceholder"),
        searchLabel: t("searchLabel"),
        empty: t("empty"),
        refresh: t("refresh"),
        manual: t("manual")
      }}
    />
  );
}
