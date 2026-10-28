"use client";

import { useState, type ReactElement, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import { Combobox, ComboboxCheck, ComboboxMeta } from "@/components/ui/combobox";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import Image from "@/components/ui/image";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export interface SearchableImageOption {
  value: string;
  label: string;
  imageSrc?: string | null;
  icon?: ReactNode;
  /** Optional trailing facet count ("how many rows this option matches"). */
  count?: number;
}

interface SearchableImageSelectBaseProps {
  /** Forwarded to the trigger so a `<Label htmlFor>` can name it. */
  id?: string;
  /** Full list of selectable items. */
  options: SearchableImageOption[];
  /** Placeholder text shown when nothing is selected. */
  placeholder: string;
  /** Clear row's label; defaults to `placeholder`. */
  clearLabel?: string;
  /** Placeholder for the search input inside the popover. */
  searchPlaceholder?: string;
  /** `false` drops the clear row, for pickers that always hold a selection. */
  clearable?: boolean;
  /** Trigger's accessible name; defaults to `placeholder` unless `id` lets a label name it. */
  ariaLabel?: string;
  /** Whether the selector is in a loading state. */
  isLoading?: boolean;
  /** Whether the selector is disabled (loading or error). */
  disabled?: boolean;
  /** `sm` is the 32px toolbar row, `default` the 36px form row. */
  size?: "sm" | "default";
  /** `surface` is the public form control skin. */
  variant?: "default" | "surface";
  /** Merged over the trigger's classes (width). */
  triggerClassName?: string;
  /**
   * Replaces the input-like trigger (a heading that switches what the card
   * shows); one element that forwards its ref. The trigger props above are
   * then unused.
   */
  trigger?: ReactElement;
}

/**
 * Single- or multi-select, discriminated by `multiple` so a call site cannot
 * mix the two value shapes. Multi keeps the popover open while toggling —
 * closing after every pick makes a three-item selection a nine-click job.
 */
type SearchableImageSelectProps = SearchableImageSelectBaseProps &
  (
    | {
        multiple?: false;
        /** Currently selected value, or undefined when "all" / cleared. */
        value?: string;
        /** Called with the new value, or undefined when cleared. */
        onValueChange: (nextValue: string | undefined) => void;
      }
    | {
        multiple: true;
        /** Currently selected values; empty means "all" / no filter. */
        values: string[];
        onValuesChange: (nextValues: string[]) => void;
      }
  );

/** One picture size for the trigger and the rows. */
const IMAGE_CLASS = "size-5 shrink-0 select-none object-contain";

/** `ui/combobox` with an image (or icon) slot per option and an optional multi-select layer. */
export function SearchableImageSelect(props: SearchableImageSelectProps) {
  const {
    id,
    options,
    placeholder,
    clearLabel,
    searchPlaceholder,
    clearable = true,
    ariaLabel,
    isLoading = false,
    disabled = false,
    size = "default",
    variant,
    triggerClassName,
    trigger
  } = props;
  const t = useTranslations();
  const [open, setOpen] = useState(false);

  const selectedValues = props.multiple
    ? props.values
    : props.value === undefined
      ? []
      : [props.value];
  const selectedOptions = options.filter((option) => selectedValues.includes(option.value));

  const handleSelect = (nextValue: string | undefined) => {
    if (props.multiple) {
      if (nextValue === undefined) {
        props.onValuesChange([]);
        setOpen(false);
        return;
      }
      props.onValuesChange(
        selectedValues.includes(nextValue)
          ? selectedValues.filter((value) => value !== nextValue)
          : [...selectedValues, nextValue]
      );
      return;
    }
    props.onValueChange(nextValue);
    setOpen(false);
  };

  const labelText =
    props.multiple || selectedOptions.length !== 1 ? placeholder : selectedOptions[0].label;
  const labelNode = isLoading ? (
    <Skeleton className="h-4 w-28" />
  ) : (
    <span className="truncate">{labelText}</span>
  );

  const triggerProps = trigger
    ? { trigger }
    : {
        id,
        label:
          !isLoading && selectedOptions.length === 0 ? undefined : (
            <span className="flex items-center gap-2 overflow-hidden">
              {/* Single-select renames itself to the pick, so its crest leads the
                  label. Multi keeps the facet's own name ("Division") and lets
                  the crests trail it. */}
              {props.multiple ? labelNode : null}
              <span className={cn("flex items-center", props.multiple ? "-space-x-1.5" : "gap-2")}>
                {selectedOptions
                  .slice(0, 3)
                  .map((option) =>
                    option.imageSrc ? (
                      <Image
                        key={option.value}
                        src={option.imageSrc}
                        alt=""
                        width={20}
                        height={20}
                        className={IMAGE_CLASS}
                      />
                    ) : option.icon ? (
                      <span key={option.value}>{option.icon}</span>
                    ) : null
                  )}
              </span>
              {props.multiple ? null : labelNode}
              {selectedOptions.length > 3 ? (
                <span className="shrink-0 tabular-nums">+{selectedOptions.length - 3}</span>
              ) : null}
            </span>
          ),
        placeholder,
        labelTitle: labelText,
        triggerAriaLabel: ariaLabel ?? (id ? undefined : placeholder),
        size,
        variant,
        disabled,
        triggerClassName
      };

  return (
    <Combobox
      {...triggerProps}
      open={open}
      onOpenChange={setOpen}
      searchPlaceholder={searchPlaceholder ?? t("common.search")}
      emptyMessage={t("common.noResults")}
      clear={
        clearable
          ? {
              label: clearLabel ?? placeholder,
              value: `__clear__ ${clearLabel ?? placeholder}`,
              onSelect: () => handleSelect(undefined),
              selected: selectedValues.length === 0
            }
          : undefined
      }
    >
      <CommandGroup>
        {options.map((option) => (
          <CommandItem
            key={option.value}
            value={`${option.label} ${option.value}`}
            onSelect={() => handleSelect(option.value)}
          >
            {option.imageSrc ? (
              <Image src={option.imageSrc} alt="" width={20} height={20} className={IMAGE_CLASS} />
            ) : (
              (option.icon ?? null)
            )}
            <span className="min-w-0 flex-1 truncate">{option.label}</span>
            {option.count !== undefined ? <ComboboxMeta>{option.count}</ComboboxMeta> : null}
            <ComboboxCheck selected={selectedValues.includes(option.value)} />
          </CommandItem>
        ))}
      </CommandGroup>
    </Combobox>
  );
}
