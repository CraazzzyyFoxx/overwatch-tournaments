"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { MapRead } from "@/types/map.types";
import type { EncounterMapPoolEntry, MapPoolEntryStatus } from "@/types/tournament.types";

import { pickedMapsInOrder } from "./veto-model";

interface VetoMapGridProps {
  pool: EncounterMapPoolEntry[];
  mapsById: Record<number, MapRead | undefined>;
  selectedMapId: number | null;
  /** Whether available maps can currently be selected by this viewer. */
  canSelect: boolean;
  onSelect: (mapId: number) => void;
}

const STATUS_BADGE_VARIANT: Record<MapPoolEntryStatus, "secondary" | "destructive" | "default" | "outline"> = {
  available: "outline",
  banned: "destructive",
  picked: "default",
  played: "secondary",
};

export function VetoMapGrid({ pool, mapsById, selectedMapId, canSelect, onSelect }: VetoMapGridProps) {
  const t = useTranslations("encounters.veto.room");
  const orderedPicks = pickedMapsInOrder(pool);
  const mapName = (mapId: number) => mapsById[mapId]?.name ?? t("maps.mapNumber", { id: mapId });

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t("maps.title")}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
          {pool.map((entry) => {
            const map = mapsById[entry.map_id];
            const selectable = canSelect && entry.status === "available";
            const selected = selectedMapId === entry.map_id;
            const dimmed = entry.status === "banned";

            return (
              <button
                key={entry.id}
                type="button"
                disabled={!selectable}
                aria-pressed={selected}
                onClick={() => onSelect(entry.map_id)}
                className={cn(
                  "group relative flex flex-col overflow-hidden rounded-xl border text-left outline-none transition-shadow",
                  selected
                    ? "border-[color:var(--aqt-teal)] ring-2 ring-[color:var(--aqt-teal)]/45"
                    : "border-[color:var(--aqt-border)]",
                  selectable
                    ? "cursor-pointer hover:border-[color:var(--aqt-teal)]/60 focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
                    : "cursor-default",
                )}
              >
                <div className="relative h-20 w-full bg-[color:var(--aqt-card-2)] sm:h-24">
                  {map?.image_path ? (
                    <Image
                      src={map.image_path}
                      alt={map.name}
                      fill
                      sizes="(max-width: 640px) 50vw, (max-width: 1280px) 33vw, 25vw"
                      className={cn(
                        "object-cover transition-opacity",
                        dimmed ? "opacity-30 grayscale" : null,
                        entry.status === "played" ? "opacity-60" : null,
                      )}
                    />
                  ) : (
                    <span className="absolute inset-0 grid place-items-center font-onest text-lg font-semibold text-[color:var(--aqt-fg-faint)]">
                      {mapName(entry.map_id)
                        .split(/\s+/)
                        .map((word) => word[0])
                        .slice(0, 2)
                        .join("")
                        .toUpperCase()}
                    </span>
                  )}
                  {entry.action_index != null ? (
                    <span className="absolute left-1.5 top-1.5 grid h-6 w-6 place-items-center rounded-md bg-black/65 font-mono text-xs font-semibold text-white">
                      {entry.action_index + 1}
                    </span>
                  ) : null}
                </div>
                <div className="flex flex-col gap-1.5 p-2.5">
                  <span className={cn("truncate text-sm font-medium", dimmed ? "line-through opacity-70" : null)}>
                    {mapName(entry.map_id)}
                  </span>
                  <span className="flex flex-wrap items-center gap-1.5">
                    <Badge variant={STATUS_BADGE_VARIANT[entry.status]} className="px-1.5 py-0 text-[10px]">
                      {t(`maps.status.${entry.status}`)}
                    </Badge>
                    {entry.picked_by ? (
                      <Badge variant="outline" className="px-1.5 py-0 text-[10px] font-normal text-[color:var(--aqt-fg-muted)]">
                        {t(`maps.by.${entry.picked_by}`)}
                      </Badge>
                    ) : null}
                  </span>
                </div>
              </button>
            );
          })}
        </div>

        {orderedPicks.length > 0 ? (
          <div>
            <div className="mb-1.5 text-sm font-medium">{t("order.title")}</div>
            <div className="flex flex-wrap gap-2">
              {orderedPicks.map((entry, index) => (
                <Badge key={entry.id} variant="secondary">
                  {index + 1}. {mapName(entry.map_id)}
                  {entry.picked_by === "decider" ? ` · ${t("maps.by.decider")}` : ""}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
