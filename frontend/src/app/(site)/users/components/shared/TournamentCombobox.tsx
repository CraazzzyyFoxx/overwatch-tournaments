"use client";

import { useTranslations } from "next-intl";

import SearchableImageSelect, { type SearchableImageOption } from "@/components/ui/searchable-image-select";

interface TournamentComboboxProps<E extends string = never> {
  tournaments: readonly { id: number; name: string }[];
  /** Selected tournament id, an `extraOptions` value, or `undefined` for "All tournaments". */
  value: NoInfer<number | E> | undefined;
  onValueChange: (value: NoInfer<number | E> | undefined) => void;
  /** Non-tournament rows listed above the tournaments; values must not be numeric. */
  extraOptions?: readonly { value: E; label: string }[];
  /** `false` drops the "All tournaments" row, for pickers that always show one tournament. */
  clearable?: boolean;
  /** Trigger's accessible name; defaults to "All tournaments". */
  ariaLabel?: string;
  isLoading?: boolean;
  disabled?: boolean;
  triggerClassName?: string;
}

/**
 * The profile's tournament picker: searchable, "All tournaments" on top, ids
 * de-duplicated (a player with several roster rows in one event appears once).
 */
export function TournamentCombobox<E extends string = never>({
  tournaments,
  value,
  onValueChange,
  extraOptions = [],
  clearable,
  ariaLabel,
  isLoading,
  disabled,
  triggerClassName
}: Readonly<TournamentComboboxProps<E>>) {
  const t = useTranslations();

  const options: SearchableImageOption[] = extraOptions.map((o) => ({ value: o.value, label: o.label }));
  const seen = new Set<number>();
  for (const tournament of tournaments) {
    if (seen.has(tournament.id)) continue;
    seen.add(tournament.id);
    options.push({ value: String(tournament.id), label: tournament.name });
  }

  return (
    <SearchableImageSelect
      value={value === undefined ? undefined : String(value)}
      onValueChange={(raw) => {
        if (raw === undefined) return onValueChange(undefined);
        const extra = extraOptions.find((o) => o.value === raw);
        onValueChange(extra ? extra.value : Number(raw));
      }}
      options={options}
      placeholder={t("users.tournamentPicker.all")}
      searchPlaceholder={t("users.tournamentPicker.search")}
      clearable={clearable}
      ariaLabel={ariaLabel}
      isLoading={isLoading}
      disabled={disabled}
      triggerClassName={triggerClassName}
    />
  );
}
