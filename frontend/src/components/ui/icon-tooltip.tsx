"use client";

import type { ReactNode } from "react";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface IconTooltipProps {
  /** Tooltip title and the glyph's accessible name. */
  label: string;
  /** Optional second, dimmer tooltip line. */
  hint?: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  className?: string;
  /** The glyph; mark it `aria-hidden`, `label` already names it. Omit for a glyph drawn by `className` alone. */
  children?: ReactNode;
}

/**
 * Any icon with the admin's tooltip.
 *
 * The wrapper carries `role="img"` so `aria-label` is honoured — on a bare
 * `<span>` ARIA prohibits it and the name is silently dropped — which keeps the
 * label reachable for keyboard and screen-reader users the pointer-only tooltip
 * never shows to. Brings its own provider, so it works on any page, not only
 * under the admin shell's.
 */
export function IconTooltip({ label, hint, side = "top", className, children }: Readonly<IconTooltipProps>) {
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className={cn("inline-flex cursor-default", className)} role="img" aria-label={label}>
            {children}
          </span>
        </TooltipTrigger>
        <TooltipContent side={side}>
          {hint ? (
            <>
              <div className="font-semibold">{label}</div>
              <div className="opacity-75">{hint}</div>
            </>
          ) : (
            label
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
