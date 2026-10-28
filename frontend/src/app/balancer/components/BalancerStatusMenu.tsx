"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  ContextMenuRadioGroup,
  ContextMenuRadioItem,
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

/** The status's name in the catalog, or `null` when the registration has none. */
function getStatusName(statusOptions: StatusOptionGroups | undefined, value: string | null | undefined): string | null {
  if (!value) {
    return null;
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
  const t = useTranslations("balancerTool.page.statusMenu");
  const options = pickableBalancerStatusOptions(statusOptions);
  const statusName = getStatusName(statusOptions, value) ?? t("noStatus");
  if (!statusOptions || !onChange) {
    return null;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          className={cn("h-7 justify-start px-2", size === "compact" ? "max-w-[128px]" : "max-w-[110px]")}
          title={t("title", { status: statusName })}
        >
          <span className="truncate">{statusName}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>{t("label")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={value ?? ""} onValueChange={onChange}>
          {options.system.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value}>
              {option.name}
            </DropdownMenuRadioItem>
          ))}
          {options.custom.length > 0 ? <DropdownMenuSeparator /> : null}
          {options.custom.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value}>
              {option.name}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Context-menu submenu variant of the same picker, for right-click actions. */
export function BalancerStatusContextMenuItems({ value, statusOptions, disabled, onChange }: Readonly<StatusPickerProps>) {
  const t = useTranslations("balancerTool.page.statusMenu");
  const options = pickableBalancerStatusOptions(statusOptions);
  if (!statusOptions || !onChange) {
    return null;
  }

  return (
    <ContextMenuSub>
      <ContextMenuSubTrigger disabled={disabled}>{t("set")}</ContextMenuSubTrigger>
      <ContextMenuSubContent className="w-52">
        <ContextMenuRadioGroup value={value ?? ""} onValueChange={onChange}>
          {options.system.map((option) => (
            <ContextMenuRadioItem key={option.value} value={option.value}>
              {option.name}
            </ContextMenuRadioItem>
          ))}
          {options.custom.length > 0 ? <ContextMenuSeparator /> : null}
          {options.custom.map((option) => (
            <ContextMenuRadioItem key={option.value} value={option.value}>
              {option.name}
            </ContextMenuRadioItem>
          ))}
        </ContextMenuRadioGroup>
      </ContextMenuSubContent>
    </ContextMenuSub>
  );
}
