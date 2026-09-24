"use client";

import { useCallback, useMemo, useState } from "react";

import { Combobox, ComboboxCheck } from "@/components/kit/Combobox";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import type { LookupItem } from "@/types/pagination.types";

const TRIGGER_SIZE_CLASS = {
  sm: "h-8 w-[160px] rounded-lg border-[color:var(--aqt-border-2)] bg-black/15 text-caption",
  lg: "h-[38px] w-[170px] rounded-lg border-[color:var(--aqt-border)] bg-white/[0.015] text-caption",
} as const;

type MapComboboxProps = {
  /** The OW map catalogue. */
  maps: LookupItem[];
  mapId: number | null;
  onMapIdChange: (mapId: number | null) => void;
  /** "sm" matches inline panel controls, "lg" matches call-out/board screens. */
  size?: keyof typeof TRIGGER_SIZE_CLASS;
};

/**
 * The optional map picker behind a "record result" control — a searchable
 * "No map" + OW catalogue combobox, built on the same `Combobox` shell
 * every other picker in the app uses. Shared so every recording surface (the
 * mix panel, the fullscreen lobby board, …) stays in lockstep instead of
 * drifting as separate copies of the same dropdown.
 */
export function MapCombobox({ maps, mapId, onMapIdChange, size = "sm" }: Readonly<MapComboboxProps>) {
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");

  const selectedLabel = useMemo(
    () => (mapId == null ? "No map" : (maps.find((map) => map.id === mapId)?.name ?? "No map")),
    [maps, mapId],
  );

  const handleSelect = useCallback(
    (nextMapId: number | null) => {
      onMapIdChange(nextMapId);
      setOpen(false);
      setSearchValue("");
    },
    [onMapIdChange],
  );

  return (
    <Combobox
      open={open}
      onOpenChange={setOpen}
      label={selectedLabel}
      triggerClassName={TRIGGER_SIZE_CLASS[size]}
      searchValue={searchValue}
      onSearchValueChange={setSearchValue}
      searchPlaceholder="Search maps…"
      emptyMessage="No maps match that search."
    >
      <CommandGroup>
        <CommandItem value="no-map" onSelect={() => handleSelect(null)}>
          <span className="min-w-0 flex-1 truncate">No map</span>
          <ComboboxCheck selected={mapId == null} />
        </CommandItem>
        {maps.map((map) => (
          <CommandItem key={map.id} value={map.name} onSelect={() => handleSelect(map.id)}>
            <span className="min-w-0 flex-1 truncate">{map.name}</span>
            <ComboboxCheck selected={mapId === map.id} />
          </CommandItem>
        ))}
      </CommandGroup>
    </Combobox>
  );
}
