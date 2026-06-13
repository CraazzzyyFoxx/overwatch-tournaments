"use client";

import React, { useEffect, useRef, useState } from "react";
import { Hero } from "@/types/hero.types";
import { cn } from "@/lib/utils";
import { Avatar, AvatarImage, AvatarFallback, AvatarStack } from "@/components/ui/avatar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { heroVariantFromRole, heroInitials } from "@/app/(site)/users/components/redesign/atoms";

export type HeroImageSize = "sm" | "md" | "lg";

const SIZE_PX: Record<HeroImageSize, number> = {
  sm: 26,
  md: 30,
  lg: 40
};

export const resolveHeroPx = (size: HeroImageSize | number): number =>
  typeof size === "number" ? size : SIZE_PX[size];

type HeroLike = Pick<Hero, "name" | "image_path" | "role"> & { type?: string; color?: string };

interface HeroImageProps {
  hero: HeroLike;
  /** Named size ("sm" | "md" | "lg") or an explicit pixel size. */
  size?: HeroImageSize | number;
  className?: string;
  title?: string;
  rounded?: "full" | "lg";
  /**
   * Kept for backward compatibility. The Avatar renders images without an
   * accent frame already, so this is a no-op.
   */
  bare?: boolean;
  /**
   * Optional content shown in a hover popover (e.g. <HeroStatsPopover/>).
   * When provided, the avatar becomes an interactive trigger.
   */
  popover?: React.ReactNode;
}

/**
 * Canonical single-hero renderer. Hero icons across the app MUST go through
 * this component (Avatar-based: image with an initials fallback). Attach
 * stats via `popover` — see HeroStatsPopover and the Maps tab for the pattern.
 */
const HeroImage = ({ hero, size = "md", className, title, rounded = "full", popover }: HeroImageProps) => {
  const px = resolveHeroPx(size);
  const variant = heroVariantFromRole(hero.type ?? hero.role);
  const radiusClass = rounded === "full" ? "rounded-full" : "rounded-md";

  const avatar = (
    <Avatar className={cn(radiusClass, className)} style={{ width: px, height: px }} title={title ?? hero.name}>
      {hero.image_path ? <AvatarImage src={hero.image_path} alt={hero.name} className={radiusClass} /> : null}
      <AvatarFallback
        className={cn("aqt-display font-extrabold", radiusClass)}
        style={{
          fontSize: Math.max(9, Math.round(px * 0.4)),
          color: "hsl(220 30% 8%)",
          background: `var(--aqt-${variant})`
        }}
      >
        {heroInitials(hero.name)}
      </AvatarFallback>
    </Avatar>
  );

  if (!popover) return avatar;
  return <HoverPopover trigger={avatar} content={popover} />;
};

interface HeroStripProps {
  heroes: HeroLike[];
  size?: HeroImageSize | number;
  /** Max avatars shown before a "+N" bubble. Default 5. */
  limit?: number;
  className?: string;
  /** Optional per-hero stats popover (e.g. (hero, i) => <HeroStatsPopover/>). */
  renderPopover?: (hero: HeroLike, index: number) => React.ReactNode;
}

/**
 * Canonical multi-hero renderer: an overlapping AvatarStack of HeroImage.
 * Collapses to "+N" after `limit` (default 5).
 */
export const HeroStrip = ({ heroes, size = "sm", limit = 5, className, renderPopover }: HeroStripProps) => (
  <AvatarStack max={limit} size={resolveHeroPx(size)} className={className}>
    {heroes.map((hero, idx) => (
      <HeroImage
        key={`${hero.name}-${idx}`}
        hero={hero}
        size={size}
        popover={renderPopover?.(hero, idx)}
      />
    ))}
  </AvatarStack>
);

/**
 * Popover with mouse hover-intent (opens on hover, stays open while the cursor
 * moves into the content, closes after a short delay on leave).
 */
const HoverPopover = ({ trigger, content }: { trigger: React.ReactNode; content: React.ReactNode }) => {
  const [open, setOpen] = useState(false);
  const closeRef = useRef<number | null>(null);

  const clearClose = () => {
    if (closeRef.current === null) return;
    window.clearTimeout(closeRef.current);
    closeRef.current = null;
  };
  const scheduleClose = (delayMs = 120) => {
    clearClose();
    closeRef.current = window.setTimeout(() => setOpen(false), delayMs);
  };

  useEffect(() => clearClose, []);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="inline-flex transition-transform hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
          onPointerEnter={(e) => {
            if (e.pointerType !== "mouse") return;
            clearClose();
          }}
          onPointerMove={(e) => {
            if (e.pointerType !== "mouse") return;
            clearClose();
            if (!open) setOpen(true);
          }}
          onPointerLeave={(e) => {
            if (e.pointerType !== "mouse") return;
            scheduleClose();
          }}
          onFocus={() => {
            clearClose();
            setOpen(true);
          }}
          onBlur={() => scheduleClose(0)}
        >
          {trigger}
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-80 data-[state=open]:animate-none data-[state=closed]:animate-none"
        onOpenAutoFocus={(e) => e.preventDefault()}
        onPointerEnter={(e) => {
          if (e.pointerType !== "mouse") return;
          clearClose();
        }}
        onPointerLeave={(e) => {
          if (e.pointerType !== "mouse") return;
          scheduleClose();
        }}
      >
        {content}
      </PopoverContent>
    </Popover>
  );
};

export default HeroImage;
