"use client";

import * as React from "react";
import * as SliderPrimitive from "@radix-ui/react-slider";

import { cn } from "@/lib/utils";

type SliderProps = Omit<
  React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root>,
  "aria-label" | "aria-labelledby"
> & {
  /**
   * A CSS colour (a role's tint): the filled track and the thumb are drawn in
   * it -- the rank slider of a role card. Without one, teal and a light thumb.
   */
  accent?: string;
} &
  // A slider has no labelable element, so a `<Label htmlFor>` cannot name it.
  (
    | { "aria-label": string; "aria-labelledby"?: never }
    | { "aria-labelledby": string; "aria-label"?: never }
  );

const Slider = React.forwardRef<React.ElementRef<typeof SliderPrimitive.Root>, SliderProps>(
  (
    {
      className,
      style,
      accent,
      "aria-label": ariaLabel,
      "aria-labelledby": ariaLabelledBy,
      ...props
    },
    ref
  ) => (
    <SliderPrimitive.Root
      ref={ref}
      className={cn(
        "relative flex w-full cursor-pointer touch-none select-none items-center data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50",
        className
      )}
      style={accent ? ({ "--slider-accent": accent, ...style } as React.CSSProperties) : style}
      {...props}
    >
      <SliderPrimitive.Track className="relative h-1 w-full grow overflow-hidden rounded-full bg-[color:var(--aqt-overlay-3)]">
        <SliderPrimitive.Range
          className={cn(
            "absolute h-full",
            accent ? "bg-[color:var(--slider-accent)]" : "bg-primary"
          )}
        />
      </SliderPrimitive.Track>
      {/* The thumb is the `role="slider"` element, so the accessible name has to
          land there -- on the root it would sit on a span with no role and be
          dropped. */}
      <SliderPrimitive.Thumb
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        className={cn(
          "block size-3.5 rounded-full transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          accent ? "bg-[color:var(--slider-accent)]" : "bg-[color:var(--aqt-fg)]"
        )}
      />
    </SliderPrimitive.Root>
  )
);
Slider.displayName = SliderPrimitive.Root.displayName;

export { Slider };
