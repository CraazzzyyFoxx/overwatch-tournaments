"use client";

import Image from "next/image";
import { ImageOff } from "lucide-react";

import { cn } from "@/lib/utils";
import type { MapRead } from "@/types/map.types";

export type MapCardProps = {
  map: MapRead;
  /** `md` — the pool grid; `sm` — the per-round strips: a wider 2:1 crop, so a Bo5's five rows stay short. */
  size?: "sm" | "md";
  className?: string;
};

/**
 * A map, recognised by its picture.
 *
 * The pool used to be columns of names, which is the one thing a player never
 * reads a map by: Ilios and Nepal are a lighthouse and a temple long before
 * they are two words under "CONTROL". The name stays, inside the image on a
 * scrim, so the card is one object instead of a picture plus a caption.
 */
export function MapCard({ map, size = "md", className }: Readonly<MapCardProps>) {
  const small = size === "sm";

  return (
    <figure
      title={map.name}
      className={cn(
        "relative overflow-hidden rounded-md border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)]",
        className
      )}
    >
      <div className={cn("relative", small ? "aspect-[2/1]" : "aspect-video")}>
        {map.image_path ? (
          <Image
            src={map.image_path}
            alt=""
            fill
            sizes={small ? "160px" : "260px"}
            className="object-cover"
          />
        ) : (
          <div className="grid h-full place-items-center text-[color:var(--aqt-fg-faint)]">
            <ImageOff aria-hidden width={18} height={18} />
          </div>
        )}
        {/* Scrim, not a solid bar: the map stays readable while its name keeps
            4.5:1 over the darkest part of the image. */}
        <span
          aria-hidden
          className="absolute inset-x-0 bottom-0 h-1/2"
          style={{
            background:
              "linear-gradient(to top, color-mix(in srgb, #000 82%, transparent), transparent)"
          }}
        />
        {map.gamemode?.image_path ? (
          <span className="absolute left-1.5 top-1.5 grid size-5 place-items-center rounded bg-black/55 backdrop-blur-sm">
            <Image
              src={map.gamemode.image_path}
              alt=""
              width={small ? 11 : 13}
              height={small ? 11 : 13}
              aria-hidden
            />
          </span>
        ) : null}
        {/* No play counts here: this section is the pool, and how often a map
            was played is a statistic. */}
        <figcaption
          className={cn(
            "absolute inset-x-0 bottom-0 truncate px-2 pb-1.5 font-semibold text-white drop-shadow",
            small ? "text-label" : "text-caption"
          )}
        >
          {map.name}
        </figcaption>
      </div>
    </figure>
  );
}

export default MapCard;
