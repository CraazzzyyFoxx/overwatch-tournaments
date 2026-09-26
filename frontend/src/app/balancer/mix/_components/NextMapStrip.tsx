"use client";

import { useState } from "react";

import Image from "next/image";

import { Dices } from "lucide-react";

import { rollNextMap, rollableModes } from "@/app/balancer/mix/pickup-map-roll";
import { CAPTION_CLASS, EYEBROW_CLASS } from "@/app/balancer/mix/pickup-chrome";
import { MapCombobox } from "@/components/MapCombobox";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type { CustomGame, CustomGameMatch } from "@/services/custom-game.service";
import type { MapRead } from "@/types/map.types";

/**
 * The map the next match is on, and how a host gets one: roll it (inside one
 * mode, or mode-first across all of them -- see `rollNextMap`), or pick it by
 * hand. The verdict is the mix's `next_map_id`, so every viewer reads the same
 * map and the next recorded result carries it. Only the mode filter is local:
 * it is a preference of whoever is rolling, not a fact about the mix.
 *
 * Hidden from the screenshot when nothing is rolled: "Not rolled yet" beside
 * two teams is noise in the channel the image is pasted into.
 */
export function NextMapStrip({
  game,
  maps,
  matches,
  canWrite,
  saving,
  capturing,
  onNextMapChange
}: Readonly<{
  game: CustomGame;
  maps: MapRead[];
  matches: CustomGameMatch[];
  canWrite: boolean;
  saving: boolean;
  capturing: boolean;
  onNextMapChange: (mapId: number | null) => void;
}>) {
  const [modeId, setModeId] = useState<number | null>(null);
  const modes = rollableModes(maps);
  const nextMap =
    game.next_map_id == null ? null : (maps.find((map) => map.id === game.next_map_id) ?? null);

  if (!canWrite && nextMap == null) return null;

  const roll = () => {
    const rolled = rollNextMap(maps, {
      gamemodeId: modeId,
      playedMapIds: matches.flatMap((match) => (match.map_id == null ? [] : [match.map_id]))
    });
    if (rolled == null) {
      notify.error("No competitive maps to roll from");
      return;
    }
    onNextMapChange(rolled.id);
  };

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-3 rounded-xl border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] px-3 py-2.5",
        capturing && nextMap == null && "hidden"
      )}
    >
      <div className="relative h-10 w-[72px] shrink-0 overflow-hidden rounded-md border border-[color:var(--aqt-border-2)] bg-[linear-gradient(135deg,var(--aqt-card-2),var(--aqt-bg-2))]">
        {nextMap?.image_path ? (
          <Image src={nextMap.image_path} alt="" fill sizes="72px" className="object-cover" />
        ) : (
          <Dices
            className="absolute inset-0 m-auto size-4 text-[color:var(--aqt-fg-faint)]"
            aria-hidden="true"
          />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <span className={EYEBROW_CLASS}>Next map</span>
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span
            className={cn(
              "truncate font-display text-base font-bold tracking-[-0.01em]",
              nextMap ? "text-[color:var(--aqt-fg)]" : "text-[color:var(--aqt-fg-dim)]"
            )}
          >
            {nextMap?.name ?? "Not rolled yet"}
          </span>
          {nextMap?.gamemode ? (
            <span className={CAPTION_CLASS}>{nextMap.gamemode.name}</span>
          ) : null}
        </div>
      </div>

      {canWrite ? (
        <div
          data-export-hide
          className={cn("flex flex-wrap items-center gap-1.5", capturing && "invisible")}
        >
          <div
            role="group"
            aria-label="Roll within mode"
            className="flex flex-wrap items-center gap-1"
          >
            <ModeChip label="Any" active={modeId == null} onClick={() => setModeId(null)} />
            {modes.map((mode) => (
              <ModeChip
                key={mode.id}
                label={mode.name}
                active={modeId === mode.id}
                onClick={() => setModeId(mode.id)}
              />
            ))}
          </div>
          <Button
            type="button"
            variant="outline"
            className="h-8"
            disabled={saving || maps.length === 0}
            onClick={roll}
          >
            {saving ? (
              <Spinner className="mr-1.5 size-3.5" />
            ) : (
              <Dices className="mr-1.5 size-3.5" aria-hidden="true" />
            )}
            Roll
          </Button>
          <MapCombobox maps={maps} mapId={game.next_map_id} onMapIdChange={onNextMapChange} />
        </div>
      ) : null}
    </div>
  );
}

/** One mode the roll can stay inside; the same pressed-pill the add-players filters use. */
function ModeChip({
  label,
  active,
  onClick
}: Readonly<{ label: string; active: boolean; onClick: () => void }>) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 shrink-0 items-center rounded-full border px-2.5 text-label transition-colors",
        active
          ? "border-[color:color-mix(in_srgb,var(--aqt-teal)_38%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)] text-[color:var(--aqt-teal)]"
          : "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] text-[color:var(--aqt-fg-muted)] hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
      )}
    >
      {label}
    </button>
  );
}
