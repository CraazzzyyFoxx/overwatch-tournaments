"use client";

import { type ReactElement, type ReactNode } from "react";
import { Check, ChevronDown } from "lucide-react";

import { selectTriggerClass, triggerChevronClass } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/**
 * The "nothing chosen" row: first in the list, its own group, muted, ticked
 * while nothing is chosen. Wording differs per domain ("None", "All
 * tournaments", "Unmapped").
 */
interface ComboboxClearAction {
  label: string;
  /** cmdk search value for the row; keep it unique inside the list. */
  value: string;
  onSelect: () => void;
  /**
   * Whether nothing is chosen. Defaults to the default trigger showing its
   * placeholder; a custom `trigger` has no placeholder, so pass it.
   */
  selected?: boolean;
}

/**
 * Trigger surface: `default` the outline button's tonal surface, `surface` the
 * public form control skin (red once `aria-invalid`). The trigger is the
 * `SelectTrigger`'s own (`selectTriggerClass`), so both pickers look alike.
 */
type ComboboxVariant = "default" | "surface";

interface ComboboxDefaultTrigger {
  trigger?: undefined;
  /** Forwarded to the trigger so a `<Label htmlFor>` can point at it. */
  id?: string;
  /** Trigger content once something is chosen; empty shows `placeholder`. */
  label?: ReactNode;
  /** Shown dimmed while `label` is empty, like `SelectValue`'s placeholder. */
  placeholder?: string;
  /**
   * Plain-text form of `label`, for the trigger's `title`. Only needed when
   * `label` is not a string, since a `ReactNode` cannot be a tooltip.
   */
  labelTitle?: string;
  /**
   * Accessible name for the trigger, when `label` alone cannot identify it.
   * A table of per-row comboboxes renders the same placeholder in every row, so
   * the visible label is not a usable name there; prefer `id` + a visible
   * `<Label htmlFor>` wherever one exists.
   */
  triggerAriaLabel?: string;
  /** Merged after the trigger's own classes, so width and surface can be overridden. */
  triggerClassName?: string;
  variant?: ComboboxVariant;
  /** `sm` is the 32px toolbar row (13px text); `default` the 36px form row (14px). */
  size?: "sm" | "default";
  disabled?: boolean;
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
}

interface ComboboxCustomTrigger {
  /**
   * Replaces the input-like trigger — a toolbar toggle, a chip. One element
   * that forwards its ref; Radix wires `aria-expanded`/`aria-controls` onto it.
   */
  trigger: ReactElement;
}

export type ComboboxProps = (ComboboxDefaultTrigger | ComboboxCustomTrigger) & {
  /** Omit both for an uncontrolled popover (a multi-select that stays open while toggling). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Omit both for an uncontrolled search field; it resets whenever the popover closes. */
  searchValue?: string;
  onSearchValueChange?: (value: string) => void;
  searchPlaceholder: string;
  /**
   * Accessible name for the search field. Defaults to `searchPlaceholder` — a
   * placeholder alone is not an accessible name, and cmdk's `aria-labelledby`
   * points at a `Command.Label` this primitive does not render.
   */
  searchLabel?: string;
  emptyMessage: ReactNode;
  /** Pass `false` for server-filtered results so cmdk does not filter them again. */
  shouldFilter?: boolean;
  clear?: ComboboxClearAction;
  /** Rendered above the search field, e.g. a facet filter row or a back button. */
  header?: ReactNode;
  /** `end` for a trigger at the right edge of a toolbar. */
  align?: "start" | "end";
  /** `CommandGroup`s holding the options. */
  children: ReactNode;
};

/**
 * The one searchable picker: trigger + popover + cmdk list. Owns the ARIA
 * contract — the `combobox` trigger wired to the popup it controls, and a real
 * accessible name on the search field — so domain pickers only have to
 * describe their own options.
 */
export function Combobox(props: Readonly<ComboboxProps>) {
  const {
    open,
    onOpenChange,
    searchValue,
    onSearchValueChange,
    searchPlaceholder,
    searchLabel,
    emptyMessage,
    shouldFilter,
    clear,
    header,
    align = "start",
    children
  } = props;

  // `aria-expanded`/`aria-controls` come from Radix's PopoverTrigger (it points
  // at the content id it also stamps on PopoverContent). Overriding them here
  // would break that link, and cmdk ignores an `id` passed to CommandList.
  // So does `aria-haspopup="dialog"`: the popup is a dialog holding a search
  // field and its listbox, not a bare listbox.
  let trigger: ReactElement;
  // `x && <Label/>` call sites hand over `false`: nothing chosen, like null or "".
  let empty = false;
  if (props.trigger === undefined) {
    empty = props.label == null || props.label === "" || props.label === false;
    trigger = (
      <button
        id={props.id}
        type="button"
        // eslint-disable-next-line jsx-a11y/role-has-required-aria-props -- PopoverTrigger stamps both (see above)
        role="combobox"
        aria-label={props.triggerAriaLabel}
        disabled={props.disabled}
        aria-invalid={props["aria-invalid"]}
        aria-describedby={props["aria-describedby"]}
        data-placeholder={empty ? "" : undefined}
        className={cn(selectTriggerClass(props.size, props.variant), props.triggerClassName)}
      >
        <span
          title={
            props.labelTitle ??
            (empty ? props.placeholder : typeof props.label === "string" ? props.label : undefined)
          }
        >
          {empty ? props.placeholder : props.label}
        </span>
        <ChevronDown aria-hidden className={triggerChevronClass} />
      </button>
    );
  } else {
    trigger = props.trigger;
  }

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent
        align={align}
        // Trigger-width by default, but a compact trigger must not produce a
        // list too narrow to read; the inner min() keeps it inside the viewport.
        className="w-[var(--radix-popover-trigger-width)] min-w-[min(16rem,var(--radix-popover-content-available-width))] p-0"
      >
        <Command
          shouldFilter={shouldFilter}
          // Rows take the trigger's text, like `SelectItem` (DESIGN §3, Control text).
          className={
            props.trigger === undefined && props.size === "sm"
              ? "[&_[cmdk-item]]:text-caption"
              : undefined
          }
        >
          {header}
          <CommandInput
            value={searchValue}
            onValueChange={onSearchValueChange}
            placeholder={searchPlaceholder}
            aria-label={searchLabel ?? searchPlaceholder}
          />
          <CommandList>
            <CommandEmpty>{emptyMessage}</CommandEmpty>
            {clear ? (
              <>
                <CommandGroup>
                  <CommandItem
                    value={clear.value}
                    onSelect={clear.onSelect}
                    className="text-[color:var(--aqt-fg-muted)]"
                  >
                    <span className="min-w-0 flex-1 truncate">{clear.label}</span>
                    <ComboboxCheck selected={clear.selected ?? empty} />
                  </CommandItem>
                </CommandGroup>
                <CommandSeparator />
              </>
            ) : null}
            {children}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

/** Selection tick for a `CommandItem`, last in the row; keeps the row height stable when unselected. */
export function ComboboxCheck({ selected }: Readonly<{ selected: boolean }>) {
  return (
    <Check
      aria-hidden
      className={cn(
        "h-4 w-4 shrink-0 text-[color:var(--aqt-teal)]",
        selected ? "opacity-100" : "opacity-0"
      )}
    />
  );
}

/** A row's meta (a facet count, an id, a UTC offset, an email): the one dim caption every picker uses. */
export function ComboboxMeta({
  className,
  children
}: Readonly<{ className?: string; children: ReactNode }>) {
  return (
    <span
      className={cn("shrink-0 text-caption tabular-nums text-[color:var(--aqt-fg-dim)]", className)}
    >
      {children}
    </span>
  );
}
