"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { SearchableImageSelect } from "@/components/ui/searchable-image-select";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { type DivisionGridLike, sortTiersDescending } from "@/lib/divisions/grid";

interface DivisionComboboxBaseProps {
  /** Grid to list; defaults to the current workspace's. Pass the tournament's
   *  grid, or the reference grid for cross-workspace reads. */
  grid?: DivisionGridLike;
  /** Empty-state text and the clear row's label; defaults to "Any". */
  placeholder?: string;
  /** `false` drops the clear row, for pickers that always hold a division. */
  clearable?: boolean;
  /** Facet counts per division number, shown beside each tier. */
  counts?: Record<number, number>;
  ariaLabel?: string;
  disabled?: boolean;
  size?: "sm" | "default";
  triggerClassName?: string;
}

type DivisionComboboxProps = DivisionComboboxBaseProps &
  (
    | {
        multiple?: false;
        /** Selected division number, or `undefined` for "any". */
        value?: number;
        onValueChange: (division: number | undefined) => void;
      }
    | {
        multiple: true;
        /** Selected division numbers; empty means "any". */
        values: number[];
        onValuesChange: (divisions: number[]) => void;
      }
  );

/**
 * Searchable division picker, single or multi. Tiers come from a division grid,
 * best first by `rank_min`: grids number their tiers in either direction, so
 * the number alone does not say which end is the top.
 */
export function DivisionCombobox(props: Readonly<DivisionComboboxProps>) {
  const { grid, placeholder, clearable, counts, ariaLabel, disabled, size, triggerClassName } = props;
  const t = useTranslations();
  const workspaceGrid = useDivisionGrid();
  const resolvedGrid = grid ?? workspaceGrid;

  const options = useMemo(
    () =>
      sortTiersDescending(resolvedGrid).map((tier) => ({
        value: String(tier.number),
        label: tier.name,
        imageSrc: tier.icon_url,
        count: counts?.[tier.number]
      })),
    [resolvedGrid, counts]
  );

  const shared = {
    options,
    placeholder: placeholder ?? t("common.any"),
    searchPlaceholder: t("common.searchDivision"),
    clearable,
    ariaLabel,
    disabled,
    size,
    triggerClassName
  };

  return props.multiple ? (
    <SearchableImageSelect
      {...shared}
      multiple
      // In multi the trigger keeps showing the facet name, so a clear row
      // labelled the same would read as "this division is selected".
      clearLabel={t("common.anyDivision")}
      values={props.values.map(String)}
      onValuesChange={(raw) => props.onValuesChange(raw.map(Number))}
    />
  ) : (
    <SearchableImageSelect
      {...shared}
      value={props.value === undefined ? undefined : String(props.value)}
      onValueChange={(raw) => props.onValueChange(raw === undefined ? undefined : Number(raw))}
    />
  );
}
