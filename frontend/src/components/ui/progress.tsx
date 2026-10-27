"use client";

import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";

import { TONE_TEXT, type Tone } from "@/components/ui/tone";
import { cn } from "@/lib/utils";

const SIZE_CLASS = {
  /** The leader-scaled bar of a row or a card (DESIGN §7). */
  sm: "h-1.5",
  md: "h-2"
} as const;

interface ProgressProps extends React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> {
  size?: keyof typeof SIZE_CLASS;
  /** The fill's meaning: `accent` (teal) by default, `warning`/`danger` near or over a limit. */
  tone?: Tone;
}

const Progress = React.forwardRef<React.ElementRef<typeof ProgressPrimitive.Root>, ProgressProps>(
  ({ className, value, size = "md", tone = "accent", ...props }, ref) => (
    // `value` reaches the root too: without it Radix reports the bar as indeterminate,
    // with no `aria-valuenow`/`aria-valuetext` for a screen reader to announce.
    <ProgressPrimitive.Root
      ref={ref}
      value={value}
      className={cn(
        "relative w-full overflow-hidden rounded-full bg-[color:var(--aqt-overlay-2)]",
        SIZE_CLASS[size],
        className
      )}
      {...props}
    >
      <ProgressPrimitive.Indicator
        className={cn("h-full w-full flex-1 bg-current transition-transform", TONE_TEXT[tone])}
        style={{ transform: `translateX(-${100 - (value || 0)}%)` }}
      />
    </ProgressPrimitive.Root>
  )
);
Progress.displayName = ProgressPrimitive.Root.displayName;

export { Progress };
