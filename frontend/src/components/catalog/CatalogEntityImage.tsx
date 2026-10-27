"use client";

import React from "react";

import { AvatarStack } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import Image from "@/components/ui/image";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useHoverIntent } from "@/hooks/useHoverIntent";
import { catalogInitials } from "@/lib/catalog/initials";
import { cn } from "@/lib/utils";
import type { CatalogEntityRead } from "@/types/catalog.types";

export type CatalogEntityImageSize = "sm" | "md" | "lg";

const SIZE_PX: Record<CatalogEntityImageSize, number> = { sm: 26, md: 30, lg: 40 };

/** What the image reads from an entity: enough for embedded relationships that carry only these fields. */
type ImageEntity = Pick<CatalogEntityRead, "name" | "image_path">;

interface CatalogEntityImageProps {
  /** `null` renders the neutral placeholder (an unresolved or missing reference). */
  entity: ImageEntity | null;
  /** Named size ("sm" | "md" | "lg") or an explicit pixel size; the height of a `wide` image. */
  size?: CatalogEntityImageSize | number;
  /** Next to its own name in the surrounding text: hide it from assistive technology instead of repeating the name. */
  decorative?: boolean;
  className?: string;
  title?: string;
  /** Ignored by `wide`, which is always `rounded-md`. */
  rounded?: "full" | "lg";
  /**
   * `square` for a portrait; `wide` for a map still, 4:3 at `size` tall and cropped to fill: a square crops a map
   * to an unrecognisable patch of skybox.
   */
  shape?: "square" | "wide";
  /** Hover/focus content (a statistics card); makes the image an interactive trigger. */
  popover?: React.ReactNode;
}

/**
 * Portrait of a character, map or mode of any discipline, with an initials fallback on a neutral tile. It paints
 * the entity only: it never derives a player's assigned role (or its colour) from a character's `class`.
 *
 * Through the image optimizer (`Image`): the portraits are 256px originals shown at 26–40px, and one screen can carry
 * dozens of them. Not Radix `AvatarImage`, which preloads regardless of `loading`.
 */
export default function CatalogEntityImage({
  entity,
  size = "md",
  decorative = false,
  className,
  title,
  rounded = "full",
  shape = "square",
  popover
}: Readonly<CatalogEntityImageProps>) {
  const px = typeof size === "number" ? size : SIZE_PX[size];
  const wide = shape === "wide";
  const width = wide ? Math.round((px * 4) / 3) : px;
  const radiusClass = rounded === "full" && !wide ? "rounded-full" : "rounded-md";
  const src = entity?.image_path || null;
  // Keyed by src so a row recycled onto another entity re-tries its portrait.
  const [brokenSrc, setBrokenSrc] = React.useState<string | null>(null);
  const showImage = src !== null && brokenSrc !== src;
  const name = entity?.name ?? "";

  const tile = (
    <span
      className={cn(
        "relative flex shrink-0 overflow-hidden border border-[color:var(--aqt-border-2)]",
        radiusClass,
        className
      )}
      style={{ width, height: px }}
      title={decorative ? undefined : (title ?? (name || undefined))}
      aria-hidden={decorative || entity === null ? true : undefined}
    >
      {showImage ? (
        <Image
          src={src}
          alt={decorative ? "" : name}
          width={width}
          height={px}
          loading="lazy"
          decoding="async"
          onError={() => setBrokenSrc(src)}
          className={cn("h-full w-full select-none", wide ? "object-cover" : "object-contain", radiusClass)}
        />
      ) : (
        <span
          className={cn("aqt-display flex h-full w-full items-center justify-center font-extrabold", radiusClass)}
          // Initials stand in for the portrait, so they hold the 11px floor rather than scaling below it.
          style={{
            fontSize: Math.max(11, Math.round(px * 0.4)),
            color: "var(--aqt-fg-muted)",
            background: "var(--aqt-card-2)"
          }}
        >
          {catalogInitials(name)}
        </span>
      )}
    </span>
  );

  if (!popover) return tile;
  return <HoverPopover trigger={tile} content={popover} label={name || undefined} />;
}

/**
 * Popover with mouse hover-intent (opens on hover, stays open while the cursor moves into the content, closes after a
 * short delay on leave) and keyboard focus: the trigger is a real button, labelled by the entity's name.
 */
function HoverPopover({
  trigger,
  content,
  label
}: Readonly<{ trigger: React.ReactNode; content: React.ReactNode; label?: string }>) {
  const { open, setOpen, cancel, scheduleOpen, scheduleClose } = useHoverIntent({ closeDelay: 120, exclusive: true });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="inline"
          aria-label={label}
          // Hover brightens a ring rather than scaling: a size change on hover shifts neighbours in an avatar stack.
          className="rounded-full leading-none hover:bg-transparent hover:ring-2 hover:ring-[color:color-mix(in_srgb,var(--aqt-teal)_45%,transparent)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
          onPointerEnter={(e) => {
            if (e.pointerType === "mouse") scheduleOpen();
          }}
          onPointerLeave={(e) => {
            if (e.pointerType === "mouse") scheduleClose();
          }}
          onFocus={() => scheduleOpen(0)}
          onBlur={() => scheduleClose(0)}
        >
          {trigger}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-80"
        animate={false}
        onOpenAutoFocus={(e) => e.preventDefault()}
        // Focus never enters the card, so there is none to return. Radix would focus the trigger on close, and the
        // trigger opens on focus: every hover-out reopened the card (and two cards ping-ponged through `exclusive`).
        onCloseAutoFocus={(e) => e.preventDefault()}
        onPointerEnter={(e) => {
          if (e.pointerType === "mouse") cancel();
        }}
        onPointerLeave={(e) => {
          if (e.pointerType === "mouse") scheduleClose();
        }}
      >
        {content}
      </PopoverContent>
    </Popover>
  );
}

/**
 * Several entities as one overlapping stack (a player's characters), collapsing to "+N" after `limit`. Each portrait
 * may carry its own hover card through `renderPopover`.
 */
export function CatalogEntityStrip<E extends ImageEntity>({
  entities,
  size = "sm",
  limit = 5,
  className,
  renderPopover
}: Readonly<{
  entities: readonly E[];
  size?: CatalogEntityImageSize | number;
  limit?: number;
  className?: string;
  renderPopover?: (entity: E, index: number) => React.ReactNode;
}>) {
  return (
    <AvatarStack max={limit} size={typeof size === "number" ? size : SIZE_PX[size]} className={className}>
      {entities.map((entity, index) => (
        <CatalogEntityImage
          key={`${entity.name}-${index}`}
          entity={entity}
          size={size}
          popover={renderPopover?.(entity, index)}
        />
      ))}
    </AvatarStack>
  );
}
