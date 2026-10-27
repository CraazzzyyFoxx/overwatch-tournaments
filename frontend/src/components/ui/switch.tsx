"use client";

import * as React from "react";
import * as SwitchPrimitives from "@radix-ui/react-switch";

import { cn } from "@/lib/utils";

// The 2px border is the track's padding: the thumb fills the inner box
// (40×20, `sm` 24×12) and travels its own width, so it sits centred both ways.
const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitives.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root> & {
    /** `sm`: a 16px switch for a dense card header. */
    size?: "default" | "sm";
  }
>(({ className, size = "default", ...props }, ref) => (
  <SwitchPrimitives.Root
    className={cn(
      "peer inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] transition-colors",
      "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
      "disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:border-transparent data-[state=checked]:bg-primary aria-invalid:border-destructive",
      size === "sm" && "h-4 w-7",
      className
    )}
    {...props}
    ref={ref}
  >
    <SwitchPrimitives.Thumb
      className={cn(
        "pointer-events-none block size-5 rounded-full bg-[color:var(--aqt-fg)] transition-transform data-[state=checked]:translate-x-5 data-[state=unchecked]:translate-x-0",
        size === "sm" && "size-3 data-[state=checked]:translate-x-3"
      )}
    />
  </SwitchPrimitives.Root>
));

Switch.displayName = SwitchPrimitives.Root.displayName;

export { Switch };
