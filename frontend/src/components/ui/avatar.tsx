"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import * as AvatarPrimitive from "@radix-ui/react-avatar";

import { cn } from "@/lib/utils";

const Avatar = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Root>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Root
    ref={ref}
    className={cn("relative flex h-10 w-10 shrink-0 overflow-hidden rounded-full", className)}
    {...props}
  />
));
Avatar.displayName = AvatarPrimitive.Root.displayName;

const AvatarImage = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Image>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Image>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Image
    ref={ref}
    className={cn("aspect-square h-full w-full object-contain select-none", className)}
    {...props}
  />
));
AvatarImage.displayName = AvatarPrimitive.Image.displayName;

const AvatarFallback = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Fallback>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Fallback>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Fallback
    ref={ref}
    className={cn(
      "flex h-full w-full items-center justify-center rounded-full bg-[color:var(--aqt-overlay-3)] text-label font-medium text-[color:var(--aqt-fg-muted)]",
      className
    )}
    {...props}
  />
));
AvatarFallback.displayName = AvatarPrimitive.Fallback.displayName;

interface AvatarStackProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Max avatars shown before collapsing the remainder into a "+N" bubble. Default 5. */
  max?: number;
  /** Avatar size in px — used to size the "+N" bubble and default overlap. Default 26. */
  size?: number;
  /** Overlap between adjacent avatars in px. Defaults to ~32% of `size`. */
  overlap?: number;
  /** Separation ring color drawn around each avatar. Defaults to the card surface. */
  ringColor?: string;
  children: React.ReactNode;
}

/**
 * Lays out avatar children as an overlapping stack and collapses any beyond
 * `max` into a trailing "+N" bubble. Children are expected to be `Avatar`
 * (or `HeroImage`) elements that size themselves.
 */
const AvatarStack = ({
  max = 5,
  size = 26,
  overlap,
  ringColor = "var(--aqt-card)",
  className,
  children,
  ...rest
}: AvatarStackProps) => {
  const t = useTranslations("kit.ui");
  const items = React.Children.toArray(children).filter(Boolean);
  const shown = max && max > 0 ? items.slice(0, max) : items;
  const extra = items.length - shown.length;
  const ov = overlap ?? Math.round(size * 0.32);
  const ring = `0 0 0 2px ${ringColor}`;

  return (
    <div className={cn("flex items-center", className)} {...rest}>
      {shown.map((child, i) => (
        // `Children.toArray` stamps every element with a key derived from the
        // caller's own (`.$playerId`), so the wrapper reuses it: keying the
        // wrapper by position would pin a removed avatar's ring/stacking slot
        // to whichever avatar slid into it.
        <div
          key={(React.isValidElement(child) ? child.key : null) ?? i}
          className="relative inline-flex rounded-full"
          style={{ marginLeft: i === 0 ? 0 : -ov, zIndex: shown.length - i, boxShadow: ring }}
        >
          {child}
        </div>
      ))}
      {extra > 0 ? (
        // The `+N` collapse carries a real count, so it keeps the 12px label
        // size rather than shrinking with the stack.
        <div
          className="relative flex items-center justify-center rounded-full bg-[color:var(--aqt-overlay-4)] text-label font-semibold tabular-nums text-[color:var(--aqt-fg-muted)]"
          style={{ marginLeft: -ov, width: size, height: size, boxShadow: ring }}
          title={t("extraMore", { count: extra })}
        >
          +{extra}
        </div>
      ) : null}
    </div>
  );
};

export { Avatar, AvatarImage, AvatarFallback, AvatarStack };
