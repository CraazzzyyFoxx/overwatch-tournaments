"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";

import { cn } from "@/lib/utils";

/**
 * A whole list row that is one action — select a team, open a player; with
 * `asChild`, a row that is one link. The caller lays the cells out; the
 * primitive owns the reset, the row hover (`--aqt-overlay-2`, never on a
 * disabled row), the selected state (`aria-current`, `--aqt-overlay-3`) and the
 * inset focus ring (DESIGN.md §5, §12).
 */
const RowButton = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { asChild?: boolean }
>(({ className, asChild = false, type, ...props }, ref) => {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      ref={ref}
      type={type ?? (asChild ? undefined : "button")}
      className={cn(
        "w-full cursor-pointer text-left transition-colors",
        // `:where` keeps the hover at a bare class's weight, so a caller's own
        // `hover:` and `aria-[current=true]:` fills still win over it.
        "[@media(hover:hover)]:[&:where(:hover:not(:disabled))]:bg-[color:var(--aqt-overlay-2)] aria-[current=true]:bg-[color:var(--aqt-overlay-3)]",
        "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  );
});
RowButton.displayName = "RowButton";

export { RowButton };
