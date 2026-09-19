"use client";

import { Check, Circle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
} from "@/components/ui/context-menu";
import { cn } from "@/lib/utils";
import type { StatusMeta } from "@/types/registration.types";

export type StatusOptionGroups = {
  system: StatusMeta[];
  custom: StatusMeta[];
};

/** `ready`/`incomplete` are derived from role ranks -- never a manual pick.
 * Every status *picker* (menu, dropdown, select) must filter them out of the
 * system list; read-only badges elsewhere still render them normally. */
function pickableBalancerStatusOptions(options: StatusOptionGroups | undefined): StatusOptionGroups {
  if (!options) return { system: [], custom: [] };
  return {
    system: options.system.filter((option) => option.value !== "ready" && option.value !== "incomplete"),
    custom: options.custom,
  };
}

function flattenStatusOptions(statusOptions?: StatusOptionGroups): StatusMeta[] {
  return statusOptions ? [...statusOptions.system, ...statusOptions.custom] : [];
}

function getStatusName(statusOptions: StatusOptionGroups | undefined, value: string | null | undefined): string {
  if (!value) {
    return "No status";
  }

  return flattenStatusOptions(statusOptions).find((option) => option.value === value)?.name ?? value;
}

type StatusPickerProps = {
  value: string | null | undefined;
  statusOptions?: StatusOptionGroups;
  disabled?: boolean;
  onChange?: (status: string) => void;
};

/** Dropdown-menu status picker. `size` controls the trigger's max width for
 * the compact (table row) vs default (card) layouts. */
export function BalancerStatusMenu({
  value,
  statusOptions,
  disabled,
  onChange,
  size = "default",
}: StatusPickerProps & { size?: "default" | "compact" }) {
  const options = pickableBalancerStatusOptions(statusOptions);
  if (!statusOptions || !onChange) {
    return null;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          className={cn(
            "h-7 justify-start rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] px-2 text-label text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]",
            size === "compact" ? "max-w-[128px]" : "max-w-[110px]"
          )}
          title={`Balancer status: ${getStatusName(statusOptions, value)}`}
        >
          <span className="truncate">{getStatusName(statusOptions, value)}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>Balancer status</DropdownMenuLabel>
        {options.system.map((option) => (
          <DropdownMenuItem key={option.value} onClick={() => onChange(option.value)}>
            {option.value === value ? <Check className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
            {option.name}
          </DropdownMenuItem>
        ))}
        {options.custom.length > 0 ? <DropdownMenuSeparator /> : null}
        {options.custom.map((option) => (
          <DropdownMenuItem key={option.value} onClick={() => onChange(option.value)}>
            {option.value === value ? <Check className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
            {option.name}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Context-menu submenu variant of the same picker, for right-click actions. */
export function BalancerStatusContextMenuItems({ value, statusOptions, disabled, onChange }: Readonly<StatusPickerProps>) {
  const options = pickableBalancerStatusOptions(statusOptions);
  if (!statusOptions || !onChange) {
    return null;
  }

  return (
    <ContextMenuSub>
      <ContextMenuSubTrigger disabled={disabled}>Set balancer status</ContextMenuSubTrigger>
      <ContextMenuSubContent className="w-52">
        {options.system.map((option) => (
          <ContextMenuItem key={option.value} onClick={() => onChange(option.value)}>
            {option.value === value ? <Check className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
            {option.name}
          </ContextMenuItem>
        ))}
        {options.custom.length > 0 ? <ContextMenuSeparator /> : null}
        {options.custom.map((option) => (
          <ContextMenuItem key={option.value} onClick={() => onChange(option.value)}>
            {option.value === value ? <Check className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
            {option.name}
          </ContextMenuItem>
        ))}
      </ContextMenuSubContent>
    </ContextMenuSub>
  );
}
