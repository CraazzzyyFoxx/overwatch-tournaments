"use client";

import { type ReactNode } from "react";
import { Code2, RefreshCw } from "lucide-react";

import { Combobox, ComboboxCheck } from "@/components/ui/combobox";
import { Button } from "@/components/ui/button";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

/** A `CommandGroup` worth of entities. Omit `heading` for a single flat group
 *  (the role picker); the channel picker groups entities by category. */
interface DiscordEntitySelectGroup<T> {
  heading?: string;
  entities: T[];
}

/** The two footprints these pickers ship in: the channel picker's default
 *  size, and the role picker's tighter one for inline tier rows. */
type DiscordEntitySelectSize = "default" | "sm";

interface DiscordEntitySelectLabels {
  loading: string;
  dropdown: string;
  idAria: string;
  placeholder: string;
  searchPlaceholder: string;
  searchLabel: string;
  empty: string;
  refresh: string;
  manual: string;
}

export interface DiscordEntitySelectProps<T extends { id: string; name: string }> {
  size: DiscordEntitySelectSize;
  id?: string;
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
  placeholder?: string;
  /** Accessible name for the manual ID field, which has no visible label. */
  ariaLabel?: string;
  className?: string;
  isLoading: boolean;
  hasEntities: boolean;
  onRefetch: () => void;
  manualMode: boolean;
  onManualModeChange: (manual: boolean) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  search: string;
  onSearchChange: (search: string) => void;
  groups: DiscordEntitySelectGroup<T>[];
  selected: T | undefined;
  onPick: (entity: T) => void;
  /** Full row content -- icon, name, any trailing badge -- for a list item. */
  renderOption: (entity: T) => ReactNode;
  /** Full trigger label content once an entity is selected. */
  renderSelectedLabel: (entity: T) => ReactNode;
  labels: DiscordEntitySelectLabels;
  /** When set, the list opens with this "nothing picked" row, and picking it clears the value. */
  noneLabel?: string;
}

/**
 * Shared trigger + popover + manual-fallback shell for the Discord entity
 * pickers (`DiscordChannelSelect`, `DiscordRoleSelect`). Owns the combobox
 * structure and the id-entry fallback; callers own the entity shape, icon,
 * grouping, and row content.
 */
export function DiscordEntitySelect<T extends { id: string; name: string }>({
  size,
  id,
  value,
  onChange,
  disabled,
  placeholder,
  ariaLabel,
  className,
  isLoading,
  hasEntities,
  onRefetch,
  manualMode,
  onManualModeChange,
  open,
  onOpenChange,
  search,
  onSearchChange,
  groups,
  selected,
  onPick,
  renderOption,
  renderSelectedLabel,
  labels,
  noneLabel
}: Readonly<DiscordEntitySelectProps<T>>) {
  // The icon buttons match the trigger's height and carry a 14px glyph.
  const iconButtonSize = size === "sm" ? "icon-toolbar" : "icon";
  const iconButtonClass = "shrink-0 text-[color:var(--aqt-fg-muted)] [&_svg]:size-3.5";

  // `className` lands on the WRAPPER, not the trigger: this renders a row --
  // control plus one or two buttons -- into the caller's layout, so the
  // wrapper is what has to carry their width.
  //
  // Manual entry is the only way out when our bot cannot read the guild, so
  // it stays reachable -- but it is the fallback, never the advertised
  // workflow.
  if (manualMode || (!isLoading && !hasEntities)) {
    return (
      <div className={cn("flex min-w-0 items-center gap-1.5", className)}>
        <Input
          id={id}
          size={size}
          value={value}
          onChange={(event) => onChange(event.target.value.replace(/\D/g, ""))}
          disabled={disabled}
          aria-label={ariaLabel ?? labels.idAria}
          placeholder="123456789012345678"
          inputMode="numeric"
          autoComplete="off"
          maxLength={19}
          className="w-full min-w-0 font-mono"
        />
        {hasEntities && (
          <Button
            type="button"
            variant="ghost"
            size={size}
            className="shrink-0 px-2"
            onClick={() => onManualModeChange(false)}
          >
            {labels.dropdown}
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className={cn("flex min-w-0 items-center gap-1.5", className)}>
      {isLoading && !value ? (
        <div role="status" className="w-full min-w-0">
          <span className="sr-only">{labels.loading}</span>
          <Skeleton aria-hidden className={cn("w-full", size === "sm" ? "h-8" : "h-9")} />
        </div>
      ) : (
        <Combobox
          id={id}
          open={open}
          onOpenChange={onOpenChange}
          disabled={disabled || isLoading}
          size={size}
          triggerClassName="min-w-0"
          // The trigger names itself from its content: the chosen entity once
          // there is one, the purpose while there is not.
          label={
            selected ? (
              renderSelectedLabel(selected)
            ) : value ? (
              // A stored entity the guild no longer returns: the id is all we know.
              <span className="font-mono">{value}</span>
            ) : undefined
          }
          placeholder={placeholder ?? labels.placeholder}
          labelTitle={selected?.name ?? (value || undefined)}
          searchValue={search}
          onSearchValueChange={onSearchChange}
          searchPlaceholder={labels.searchPlaceholder}
          searchLabel={labels.searchLabel}
          emptyMessage={labels.empty}
          clear={
            noneLabel
              ? {
                  label: noneLabel,
                  value: noneLabel,
                  onSelect: () => {
                    onChange("");
                    onOpenChange(false);
                    onSearchChange("");
                  }
                }
              : undefined
          }
        >
          {groups.map((group, index) => (
            <CommandGroup key={group.heading ?? index} heading={group.heading}>
              {group.entities.map((entity) => (
                // The id joins the search text so a pasted snowflake still finds it.
                <CommandItem
                  key={entity.id}
                  value={`${entity.name} ${entity.id}`}
                  onSelect={() => onPick(entity)}
                >
                  {renderOption(entity)}
                  <ComboboxCheck selected={entity.id === value} />
                </CommandItem>
              ))}
            </CommandGroup>
          ))}
        </Combobox>
      )}
      <Button
        type="button"
        variant="ghost"
        size={iconButtonSize}
        className={iconButtonClass}
        onClick={onRefetch}
        disabled={isLoading}
        aria-label={labels.refresh}
        title={labels.refresh}
      >
        {isLoading ? <Spinner /> : <RefreshCw aria-hidden />}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size={iconButtonSize}
        className={iconButtonClass}
        onClick={() => onManualModeChange(true)}
        aria-label={labels.manual}
        title={labels.manual}
      >
        <Code2 aria-hidden />
      </Button>
    </div>
  );
}
