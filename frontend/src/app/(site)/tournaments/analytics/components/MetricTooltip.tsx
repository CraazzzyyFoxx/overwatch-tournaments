"use client";

import React from "react";
import { Info } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import { GlossaryTerm } from "../analytics-glossary";

interface MetricTooltipProps {
  term: GlossaryTerm;
  /** Custom trigger content; defaults to the glossary label. */
  children?: React.ReactNode;
  className?: string;
  /** Force-show the ⓘ icon. Defaults to true when rendering the plain label. */
  showIcon?: boolean;
  /**
   * Whether the trigger is its own tab stop. Default true. Set false when the
   * tooltip lives inside another interactive element (e.g. a clickable row) to
   * avoid a focusable-inside-a-button accessibility violation.
   */
  focusable?: boolean;
}

/**
 * A label (or any trigger) that reveals a one-sentence plain explanation of an
 * analytics term on hover/focus. The visible text stays jargon-free; the raw
 * meaning lives in the tooltip so nobody needs prior ML knowledge to read it.
 */
export default function MetricTooltip({
  term,
  children,
  className,
  showIcon,
  focusable = true,
}: MetricTooltipProps) {
  const t = useTranslations();
  const label = t(`analytics.glossary.${term}.label`);
  const plain = t(`analytics.glossary.${term}.plain`);
  const isPlainLabel = children == null;
  const withIcon = showIcon ?? isPlainLabel;

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            {...(focusable ? { tabIndex: 0 } : {})}
            aria-label={`${label}: ${plain}`}
            className={cn(
              "inline-flex items-center gap-1 align-middle",
              isPlainLabel &&
                "cursor-help underline decoration-dotted decoration-muted-foreground/40 underline-offset-2",
              className,
            )}
          >
            {children ?? label}
            {withIcon ? (
              <Info className="h-3 w-3 shrink-0 text-muted-foreground/70" aria-hidden="true" />
            ) : null}
          </span>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          className="max-w-[260px] border border-border bg-popover text-popover-foreground"
        >
          <span className="block text-xs font-semibold">{label}</span>
          <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
            {plain}
          </span>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
