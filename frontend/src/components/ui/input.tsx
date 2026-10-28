import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * The control surface (DESIGN §5 "Controls") every text field wears: 8px
 * radius, `--aqt-overlay-2` fill, `--aqt-border-2` hairline, a dimmed
 * placeholder, the 2px offset focus ring, and a red border (only the border)
 * once the control is `aria-invalid`. Exported for a trigger that wears the
 * same skin — set `aria-invalid` on it for the error state.
 */
export const controlSurfaceClass =
  "w-full rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] px-3 " +
  "text-[color:var(--aqt-fg)] placeholder:text-[color:var(--aqt-fg-dim)] transition-colors " +
  "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 " +
  "focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive";

interface InputProps extends Omit<React.ComponentProps<"input">, "size"> {
  /** `sm` is the 32px toolbar row (13px text), `default` the 36px form row, `lg` the 40px one (14px). Below `sm` all are 40px. */
  size?: "sm" | "default" | "lg";
}

// Below `sm` every field stays at 16px: iOS Safari zooms the page on focus
// into anything smaller. The field grows to 40px there, so 16px text sits in
// it in proportion instead of filling a 32px box.
const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, size = "default", ...props }, ref) => {
    return (
      <input
        className={cn(
          controlSurfaceClass,
          "flex py-1 text-base",
          size === "sm"
            ? "h-10 sm:h-8 sm:text-caption"
            : size === "lg"
              ? "h-10 sm:text-sm"
              : "h-10 sm:h-9 sm:text-sm",
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Input.displayName = "Input";

export { Input };
