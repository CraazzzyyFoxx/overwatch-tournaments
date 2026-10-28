"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Dices } from "lucide-react";

import { rollNextMap, rollableModes } from "@/app/balancer/mix/pickup-map-roll";
import { CAPTION_CLASS } from "@/app/balancer/mix/pickup-chrome";
import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { Button } from "@/components/ui/button";
import { Combobox, ComboboxCheck } from "@/components/ui/combobox";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { Eyebrow } from "@/components/ui/eyebrow";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { Spinner } from "@/components/ui/spinner";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type { CustomGameMatch } from "@/services/custom-game.service";
import type { CatalogEntityRead } from "@/types/catalog.types";

/**
 * The map the next match is on, and how a host gets one (`NextMapRoll`). The
 * verdict is the lobby's `next_map_id`, so every viewer reads the same map and
 * the next recorded result carries it.
 *
 * Hidden from the screenshot when nothing is rolled: "Not rolled yet" beside
 * two teams is noise in the channel the image is pasted into.
 */
export function NextMapStrip({
  nextMapId,
  maps,
  matches,
  canWrite,
  saving,
  capturing,
  onNextMapChange
}: Readonly<{
  /** This lobby's own `next_map_id`, not the mix's -- the mix has none. */
  nextMapId: number | null;
  maps: CatalogEntityRead[];
  matches: CustomGameMatch[];
  canWrite: boolean;
  saving: boolean;
  capturing: boolean;
  onNextMapChange: (mapId: number | null) => void;
}>) {
  const t = useTranslations("mixes.room");
  const nextMap = nextMapId == null ? null : (maps.find((map) => map.id === nextMapId) ?? null);

  if (!canWrite && nextMap == null) return null;

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-3 border-b border-[color:var(--aqt-border)] px-4 py-3",
        capturing && nextMap == null && "hidden"
      )}
    >
      {nextMap ? (
        <CatalogEntityImage entity={nextMap} size={40} shape="wide" decorative />
      ) : (
        <span className="relative flex h-10 w-[53px] shrink-0 items-center justify-center rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card-2)]">
          <Dices className="size-4 text-[color:var(--aqt-fg-faint)]" aria-hidden="true" />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <Eyebrow>{t("nextMapLabel")}</Eyebrow>
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span
            className={cn(
              "truncate font-display text-ui font-bold",
              nextMap ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-dim)]"
            )}
          >
            {nextMap?.name ?? t("notRolled")}
          </span>
          {nextMap?.parent ? (
            <span className={CAPTION_CLASS}>{nextMap.parent.name}</span>
          ) : null}
        </div>
      </div>

      {canWrite ? (
        <NextMapRoll
          nextMapId={nextMapId}
          maps={maps}
          matches={matches}
          saving={saving}
          onNextMapChange={onNextMapChange}
          className={cn(capturing && "invisible")}
        />
      ) : null}
    </div>
  );
}

/**
 * A host's ways to the next map: roll it (inside one mode, or mode-first across
 * all of them -- see `rollNextMap`), or pick it by hand. Only the mode filter is
 * local: it is a preference of whoever is rolling, not a fact about the mix.
 */
export function NextMapRoll({
  nextMapId,
  maps,
  matches,
  saving,
  onNextMapChange,
  className
}: Readonly<{
  nextMapId: number | null;
  maps: CatalogEntityRead[];
  matches: CustomGameMatch[];
  saving: boolean;
  onNextMapChange: (mapId: number | null) => void;
  className?: string;
}>) {
  const t = useTranslations("mixes.room");
  const tCommon = useTranslations("common");
  const [modeId, setModeId] = useState<number | null>(null);
  const [mapPickerOpen, setMapPickerOpen] = useState(false);
  const modes = rollableModes(maps);
  const nextMap = nextMapId == null ? null : (maps.find((map) => map.id === nextMapId) ?? null);

  const roll = () => {
    const rolled = rollNextMap(maps, {
      gamemodeId: modeId,
      playedMapIds: matches.flatMap((match) => (match.map_id == null ? [] : [match.map_id]))
    });
    if (rolled == null) {
      notify.error(t("noMapsToRoll"));
      return;
    }
    onNextMapChange(rolled.id);
  };

  const pickMap = (mapId: number | null) => {
    onNextMapChange(mapId);
    setMapPickerOpen(false);
  };

  return (
    <div data-export-hide className={cn("flex flex-wrap items-center gap-1.5", className)}>
      <FilterChipGroup label={t("rollMode")} className="gap-1">
        <FilterChip active={modeId == null} onClick={() => setModeId(null)}>
          {tCommon("any")}
        </FilterChip>
        {modes.map((mode) => (
          <FilterChip key={mode.id} active={modeId === mode.id} onClick={() => setModeId(mode.id)}>
            {mode.name}
          </FilterChip>
        ))}
      </FilterChipGroup>
      <Button type="button" variant="outline" size="sm" disabled={saving || maps.length === 0} onClick={roll}>
        {saving ? <Spinner className="mr-1.5 size-3.5" /> : <Dices className="mr-1.5 size-3.5" aria-hidden="true" />}
        {t("roll")}
      </Button>
      <Combobox
        open={mapPickerOpen}
        onOpenChange={setMapPickerOpen}
        label={nextMap?.name}
        placeholder={t("noMap")}
        variant="surface"
        size="sm"
        triggerClassName="w-40"
        searchPlaceholder={t("searchMaps")}
        emptyMessage={t("noMapsMatch")}
        clear={{ label: t("noMap"), value: t("noMap"), onSelect: () => pickMap(null), selected: nextMapId == null }}
      >
        <CommandGroup>
          {maps.map((map) => (
            <CommandItem key={map.id} value={map.name} onSelect={() => pickMap(map.id)}>
              <span className="min-w-0 flex-1 truncate">{map.name}</span>
              <ComboboxCheck selected={nextMapId === map.id} />
            </CommandItem>
          ))}
        </CommandGroup>
      </Combobox>
    </div>
  );
}
