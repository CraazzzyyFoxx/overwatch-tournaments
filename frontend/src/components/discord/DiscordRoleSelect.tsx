"use client";

import React from "react";
import { useTranslations } from "next-intl";

import { useDiscordRoles } from "@/hooks/useDiscordEntities";
import { ComboboxMeta } from "@/components/ui/combobox";
import { cn } from "@/lib/utils";
import { DiscordRole } from "@/types/discord.types";

import { DiscordEntitySelect } from "./DiscordEntitySelect";

export interface DiscordRoleSelectProps {
  workspaceId: number | null | undefined;
  value: string;
  onChange: (roleId: string) => void;
  onRoleNameSelected?: (roleName: string) => void;
  disabled?: boolean;
  placeholder?: string;
  /** Accessible name for the manual ID field, which has no visible label. */
  ariaLabel?: string;
  /** Id of the visible label, when there is one. */
  id?: string;
  className?: string;
}

/** Discord ships a per-role hex, which is real data and belongs inline. Anything
 *  else is not a colour we will hand to `style`, so it falls back to a token. */
function RoleDot({ color }: Readonly<{ color: string | null | undefined }>) {
  const hex = color && /^#[0-9A-Fa-f]{6}$/.test(color) ? color : null;
  return (
    <span
      aria-hidden
      className={cn("size-2.5 shrink-0 rounded-full", hex ? undefined : "bg-muted-foreground/40")}
      style={hex ? { backgroundColor: hex } : undefined}
    />
  );
}

export function DiscordRoleSelect({
  workspaceId,
  value,
  onChange,
  onRoleNameSelected,
  disabled,
  placeholder,
  ariaLabel,
  id,
  className
}: Readonly<DiscordRoleSelectProps>) {
  const t = useTranslations("discord.role");
  const { data, isLoading, refetch } = useDiscordRoles(workspaceId);
  const [manualMode, setManualMode] = React.useState(false);
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");

  const roles: DiscordRole[] = data?.roles ?? [];
  const hasRoles = roles.length > 0;
  const selected = roles.find((role) => role.id === value);

  const pick = (role: DiscordRole) => {
    onChange(role.id);
    // `@everyone` is every member, so adopting it as a tier label would name the
    // tier after the absence of a role.
    if (role.name !== "@everyone") onRoleNameSelected?.(role.name);
    setOpen(false);
    setSearch("");
  };

  return (
    <DiscordEntitySelect
      size="sm"
      id={id}
      value={value}
      onChange={onChange}
      disabled={disabled}
      placeholder={placeholder}
      ariaLabel={ariaLabel}
      className={className}
      isLoading={isLoading}
      hasEntities={hasRoles}
      onRefetch={() => refetch()}
      manualMode={manualMode}
      onManualModeChange={setManualMode}
      open={open}
      onOpenChange={setOpen}
      search={search}
      onSearchChange={setSearch}
      groups={[{ entities: roles }]}
      selected={selected}
      onPick={pick}
      renderOption={(role) => (
        <span className="flex min-w-0 flex-1 items-center gap-2">
          <RoleDot color={role.color} />
          <span className="truncate">{role.name}</span>
          {role.managed && <ComboboxMeta className="ms-auto">{t("managed")}</ComboboxMeta>}
        </span>
      )}
      renderSelectedLabel={(role) => (
        <span className="flex items-center gap-2 truncate">
          <RoleDot color={role.color} />
          <span className="truncate">{role.name}</span>
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
