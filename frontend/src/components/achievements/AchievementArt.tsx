"use client";

import { useState } from "react";
import Image from "@/components/ui/image";

import { cn } from "@/lib/utils";
import type { Achievement } from "@/types/achievement.types";

import { ACHIEVEMENT_ART_SLUGS } from "./achievementArtSlugs";

interface AchievementArtProps {
  achievement: Pick<Achievement, "name" | "slug" | "image_url">;
  /** `next/image` sizes hint for the rendered box. */
  sizes: string;
  /** Box classes (size, radius, positioning). The box is always `relative overflow-hidden`. */
  className?: string;
  imgClassName?: string;
  /** Empty by default: every call site prints the name next to (or over) the art. */
  alt?: string;
}

/**
 * Badge art with a designed fallback. A rule without an uploaded image uses
 * `/achievements/<slug>.webp` only when that file ships (`ACHIEVEMENT_ART_SLUGS`);
 * every other rule -- and any image that fails to load -- gets a monogram panel
 * tinted by the nearest `--rar` (`rarityVarClass`), never a request for a file that
 * is not there or a broken image with spilled alt text.
 */
export function AchievementArt({ achievement, sizes, className, imgClassName, alt = "" }: AchievementArtProps) {
  const src =
    achievement.image_url ??
    (ACHIEVEMENT_ART_SLUGS.has(achievement.slug) ? `/achievements/${achievement.slug}.webp` : null);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  return (
    <span className={cn("relative block overflow-hidden bg-[color:var(--aqt-card-2)] [container-type:inline-size]", className)}>
      {src === null || failedSrc === src ? (
        <span
          aria-hidden
          className="absolute inset-0 grid place-items-center font-onest font-bold uppercase leading-none text-[40cqw]"
          style={{
            color: "hsl(var(--rar, 215 14% 60%) / 0.75)",
            background:
              "radial-gradient(120% 90% at 30% 15%, hsl(var(--rar, 215 14% 60%) / 0.26), transparent 65%), var(--aqt-card-2, transparent)"
          }}
        >
          {Array.from(achievement.name.trim())[0] ?? "?"}
        </span>
      ) : (
        <Image
          src={src}
          alt={alt}
          fill
          sizes={sizes}
          className={cn("object-cover", imgClassName)}
          // A server-rendered <img> can fail before hydration attaches onError;
          // the ref sees that already-broken state on mount.
          ref={(img) => {
            if (img?.complete && img.naturalWidth === 0) setFailedSrc(src);
          }}
          onError={() => setFailedSrc(src)}
        />
      )}
    </span>
  );
}
