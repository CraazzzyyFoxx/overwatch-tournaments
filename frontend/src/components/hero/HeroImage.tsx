"use client";

import React from "react";
import { Hero } from "@/types/hero.types";
import { cn } from "@/lib/utils";
import { AvatarStack } from "@/components/ui/avatar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { heroInitials } from "@/components/hero/heroRole";
import { heroVariantFromRole } from "@/lib/roster/player-role";
import { useHoverIntent } from "@/hooks/useHoverIntent";

export type HeroImageSize = "sm" | "md" | "lg";

const SIZE_PX: Record<HeroImageSize, number> = {
  sm: 26,
  md: 30,
  lg: 40
};

const resolveHeroPx = (size: HeroImageSize | number): number =>
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
   * Optional content shown in a hover popover (e.g. <HeroUserStatsPopover/>).
   * When provided, the avatar becomes an interactive trigger.
   */
  popover?: React.ReactNode;
}

/**
 * Canonical single-hero renderer. Hero icons across the app MUST go through
 * this component (portrait image with an initials fallback). Attach
 * stats via `popover` — see HeroUserStatsPopover and the Maps tab for the pattern.
 *
 * Deliberately a plain `<img loading="lazy">`, not Radix `AvatarImage`: Radix
 * preloads the src with `new window.Image()` regardless of `loading`, and a
 * single screen can carry dozens of portraits (a user profile renders 33, the
 * players table three per row). `next/image` is out for the same reason in
 * reverse — the optimizer shares the one Node process the site runs on.
 */
const HeroImage = ({ hero, size = "md", className, title, rounded = "full", popover }: HeroImageProps) => {
  const px = resolveHeroPx(size);
  const variant = heroVariantFromRole(hero.type ?? hero.role);
  const radiusClass = rounded === "full" ? "rounded-full" : "rounded-md";
  // Keyed by src so a row recycled onto another hero re-tries its portrait.
  const [brokenSrc, setBrokenSrc] = React.useState<string | null>(null);
  const showImage = Boolean(hero.image_path) && brokenSrc !== hero.image_path;

  const avatar = (
    <span
      className={cn("relative flex shrink-0 overflow-hidden", radiusClass, "border border-[color:var(--aqt-border-2)]", className)}
      style={{ width: px, height: px }}
      title={title ?? hero.name}
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={hero.image_path}
          alt={hero.name}
          width={px}
          height={px}
          loading="lazy"
          decoding="async"
          onError={() => setBrokenSrc(hero.image_path)}
          className={cn("h-full w-full select-none object-contain", radiusClass)}
        />
      ) : (
        <span
          className={cn("aqt-display flex h-full w-full items-center justify-center font-extrabold", radiusClass)}
          style={{
            // Initials stand in for the portrait, so they hold the 11px floor
            // rather than scaling below it on the smallest avatars.
            fontSize: Math.max(11, Math.round(px * 0.4)),
            color: "var(--aqt-bg)",
            background: `var(--aqt-${variant})`
          }}
        >
          {heroInitials(hero.name)}
        </span>
      )}
    </span>
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
  /** Optional per-hero stats popover (e.g. (hero, i) => <HeroUserStatsPopover/>). */
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
 * moves into the content, closes after a short delay on leave). The timer logic
 * lives in `useHoverIntent`, shared with the workspace switcher.
 */
const HoverPopover = ({ trigger, content }: { trigger: React.ReactNode; content: React.ReactNode }) => {
  const { open, setOpen, cancel, scheduleOpen, scheduleClose } = useHoverIntent({
    closeDelay: 120,
    exclusive: true
  });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          // Hover brightens a ring rather than scaling: a size change on hover
          // shifts neighbouring portraits in an avatar stack.
          className="inline-flex appearance-none border-0 bg-transparent p-0 leading-none rounded-full transition-shadow hover:ring-2 hover:ring-[color:color-mix(in_srgb,var(--aqt-teal)_45%,transparent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
          onPointerEnter={(e) => {
            if (e.pointerType !== "mouse") return;
            scheduleOpen();
          }}
          onPointerLeave={(e) => {
            if (e.pointerType !== "mouse") return;
            scheduleClose();
          }}
          onFocus={() => scheduleOpen(0)}
          onBlur={() => scheduleClose(0)}
        >
          {trigger}
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-80"
        animate={false}
        onOpenAutoFocus={(e) => e.preventDefault()}
        onPointerEnter={(e) => {
          if (e.pointerType !== "mouse") return;
          cancel();
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
