"use client";

import { type ReactNode } from "react";
import { Code2, RefreshCw } from "lucide-react";

import { AdminCombobox, AdminComboboxCheck } from "@/components/kit/AdminCombobox";
import { Button } from "@/components/ui/button";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/** A `CommandGroup` worth of entities. Omit `heading` for a single flat group
 *  (the role picker); the channel picker groups entities by category. */
export interface DiscordEntitySelectGroup<T> {
  heading?: string;
  entities: T[];
}

/** The two footprints these pickers ship in: the channel picker's default
 *  size, and the role picker's tighter one for inline tier rows. */
export type DiscordEntitySelectSize = "default" | "sm";

const SIZE_CLASSES: Record<
  DiscordEntitySelectSize,
  { input: string; dropdownButton: string; trigger: string; iconButton: string }
> = {
  default: {
    input: "w-full min-w-0 font-mono",
    dropdownButton: "shrink-0 px-2 text-xs",
    trigger: "h-9 min-w-0 border-input bg-transparent hover:bg-transparent",
    iconButton: "size-9 shrink-0 text-muted-foreground hover:text-foreground"
  },
  sm: {
    input: "h-8 w-full min-w-0 font-mono",
    dropdownButton: "h-8 shrink-0 px-2 text-xs",
    trigger: "h-8 min-w-0 border-input bg-transparent text-sm hover:bg-transparent",
    iconButton: "size-8 shrink-0 text-muted-foreground hover:text-foreground"
  }
};

export interface DiscordEntitySelectLabels {
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
  labels
}: Readonly<DiscordEntitySelectProps<T>>) {
  const sizeClasses = SIZE_CLASSES[size];

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
          value={value}
          onChange={(event) => onChange(event.target.value.replace(/\D/g, ""))}
          disabled={disabled}
          aria-label={ariaLabel ?? labels.idAria}
          placeholder="123456789012345678"
          inputMode="numeric"
          autoComplete="off"
          maxLength={19}
          className={sizeClasses.input}
        />
        {hasEntities && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className={sizeClasses.dropdownButton}
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
      <AdminCombobox
        id={id}
        open={open}
        onOpenChange={onOpenChange}
        disabled={disabled || isLoading}
        triggerClassName={sizeClasses.trigger}
        // The trigger names itself from its content: the chosen entity once
        // there is one, the purpose while there is not.
        label={
          selected ? (
            renderSelectedLabel(selected)
          ) : value ? (
            // A stored entity the guild no longer returns: the id is all we know.
            <span className="font-mono text-xs">{value}</span>
          ) : isLoading ? (
            labels.loading
          ) : (
            (placeholder ?? labels.placeholder)
          )
        }
        labelTitle={selected?.name ?? value ?? undefined}
        searchValue={search}
        onSearchValueChange={onSearchChange}
        searchPlaceholder={labels.searchPlaceholder}
        searchLabel={labels.searchLabel}
        emptyMessage={labels.empty}
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
                <AdminComboboxCheck selected={entity.id === value} />
              </CommandItem>
            ))}
          </CommandGroup>
        ))}
      </AdminCombobox>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className={sizeClasses.iconButton}
        onClick={onRefetch}
        disabled={isLoading}
        aria-label={labels.refresh}
        title={labels.refresh}
      >
        <RefreshCw
          aria-hidden
          className={cn("size-3.5", isLoading && "animate-spin motion-reduce:animate-none")}
        />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className={sizeClasses.iconButton}
        onClick={() => onManualModeChange(true)}
        aria-label={labels.manual}
        title={labels.manual}
      >
        <Code2 aria-hidden className="size-3.5" />
      </Button>
    </div>
  );
}
