"use client";

import React from "react";
import { Folder, Hash } from "lucide-react";
import { useTranslations } from "next-intl";

import { useDiscordChannels } from "@/hooks/useDiscordEntities";
import { DiscordChannel } from "@/types/discord.types";

import { DiscordEntitySelect } from "./DiscordEntitySelect";

export interface DiscordChannelSelectProps {
  workspaceId: number | null | undefined;
  /** What is picked: a text channel to post in (default), or a category. */
  type?: "text" | "category";
  value: string;
  onChange: (channelId: string) => void;
  onChannelNameSelected?: (channelName: string) => void;
  disabled?: boolean;
  placeholder?: string;
  /** Accessible name for the manual ID field, which has no visible label. */
  ariaLabel?: string;
  /** Id of the visible label, when there is one. */
  id?: string;
  /** Offer a first option with this label that clears the channel. */
  noneLabel?: string;
  className?: string;
}

export function DiscordChannelSelect({
  workspaceId,
  type = "text",
  value,
  onChange,
  onChannelNameSelected,
  disabled,
  placeholder,
  ariaLabel,
  id,
  className,
  noneLabel
}: Readonly<DiscordChannelSelectProps>) {
  const t = useTranslations("discord");
  const ns = type === "category" ? "category" : "channel";
  const { data, isLoading, refetch } = useDiscordChannels(workspaceId);
  const [manualMode, setManualMode] = React.useState(false);
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");

  // A text channel is where a message posts; a category holds the voices mixes move players through.
  const channels: DiscordChannel[] = (data?.channels ?? []).filter((channel) => channel.type === type);
  const hasChannels = channels.length > 0;
  const selected = channels.find((channel) => channel.id === value);

  const groups = React.useMemo(() => {
    // Categories have no parent: one flat group.
    if (type === "category") return [{ entities: channels }];
    const grouped = new Map<string, DiscordChannel[]>();
    for (const channel of channels) {
      const category = channel.category_name || t("channel.uncategorized");
      const bucket = grouped.get(category);
      if (bucket) bucket.push(channel);
      else grouped.set(category, [channel]);
    }
    return [...grouped].map(([heading, entities]) => ({ heading, entities }));
  }, [channels, type, t]);

  const Icon = type === "category" ? Folder : Hash;

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
      noneLabel={noneLabel}
      onPick={pick}
      renderOption={(channel) => (
        <span className="flex min-w-0 flex-1 items-center gap-1.5">
          <Icon aria-hidden className="size-3.5 shrink-0 text-[color:var(--aqt-fg-dim)]" />
          <span className="truncate">{channel.name}</span>
        </span>
      )}
      renderSelectedLabel={(channel) => (
        <span className="flex items-center gap-1.5 truncate">
          <Icon aria-hidden className="size-3.5 shrink-0 text-[color:var(--aqt-fg-dim)]" />
          <span className="truncate">{channel.name}</span>
        </span>
      )}
      labels={{
        loading: t(`${ns}.loading`),
        dropdown: t(`${ns}.dropdown`),
        idAria: t(`${ns}.idAria`),
        placeholder: t(`${ns}.placeholder`),
        searchPlaceholder: t(`${ns}.searchPlaceholder`),
        searchLabel: t(`${ns}.searchLabel`),
        empty: t(`${ns}.empty`),
        refresh: t(`${ns}.refresh`),
        manual: t(`${ns}.manual`)
      }}
    />
  );
}
