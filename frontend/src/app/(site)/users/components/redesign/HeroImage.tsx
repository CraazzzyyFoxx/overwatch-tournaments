import React from "react";
import Image from "next/image";
import { Hero } from "@/types/hero.types";
import { cn } from "@/lib/utils";
import { heroVariantFromRole, heroInitials } from "@/app/(site)/users/components/redesign/atoms";

export type HeroImageSize = "sm" | "md" | "lg";

const SIZE_PX: Record<HeroImageSize, number> = {
  sm: 26,
  md: 30,
  lg: 40
};

interface HeroImageProps {
  hero: Pick<Hero, "name" | "image_path" | "role"> & { type?: string; color?: string };
  size?: HeroImageSize;
  className?: string;
  title?: string;
  rounded?: "full" | "lg";
  /** Если true — иконка без аккентного фона/border, только картинка */
  bare?: boolean;
}

const HeroImage = ({ hero, size = "md", className, title, rounded = "full", bare = false }: HeroImageProps) => {
  const px = SIZE_PX[size];
  const variant = heroVariantFromRole(hero.type ?? hero.role);
  const radius = rounded === "full" ? "rounded-full" : "rounded-md";

  if (!hero.image_path) {
    return (
      <span
        className={cn("aqt-hero-av", size === "sm" && "sm", size === "lg" && "lg", variant, className)}
        title={title ?? hero.name}
        style={radius === "rounded-md" ? { borderRadius: 6 } : undefined}
      >
        {heroInitials(hero.name)}
      </span>
    );
  }

  return (
    <span
      className={cn(
        "relative inline-flex items-center justify-center overflow-hidden flex-shrink-0",
        radius,
        !bare && "border border-[color:var(--aqt-border-2)]",
        !bare && `aqt-bg-${variant}`,
        className
      )}
      style={{ width: px, height: px }}
      title={title ?? hero.name}
    >
      <Image src={hero.image_path} alt={hero.name} fill sizes={`${px}px`} className="object-cover" />
    </span>
  );
};

interface HeroStripProps {
  heroes: Array<Pick<Hero, "name" | "image_path" | "role"> & { type?: string; color?: string }>;
  size?: HeroImageSize;
  limit?: number;
  className?: string;
  bare?: boolean;
}

export const HeroStrip = ({ heroes, size = "sm", limit = 4, className, bare }: HeroStripProps) => {
  const list = heroes.slice(0, limit);
  return (
    <span className={cn("aqt-hero-strip", className)}>
      {list.map((hero, idx) => (
        <HeroImage key={`${hero.name}-${idx}`} hero={hero} size={size} bare={bare} />
      ))}
    </span>
  );
};

export default HeroImage;
