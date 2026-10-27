"use client";

import React from "react";

import { Select, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

interface TooltipSelectProps {
  /** The control's name: its tooltip and accessible label. */
  tooltip: string;
  value: string;
  placeholder: string;
  disabled?: boolean;
  className?: string;
  size?: "sm" | "default";
  variant?: "default" | "surface";
  onValueChange: (value: string) => void;
  /** The `SelectContent`. */
  children: React.ReactNode;
}

/**
 * A compact Select whose label lives in a hover tooltip (and aria-label) rather
 * than a stacked caption — keeps a picker row tidy.
 */
export function TooltipSelect({
  tooltip,
  value,
  placeholder,
  disabled,
  className,
  size,
  variant,
  onValueChange,
  children
}: Readonly<TooltipSelectProps>) {
  return (
    <TooltipProvider>
      <Select value={value} onValueChange={onValueChange} disabled={disabled}>
        <Tooltip>
          <TooltipTrigger asChild>
            <SelectTrigger aria-label={tooltip} size={size} variant={variant} className={className}>
              <SelectValue placeholder={placeholder} />
            </SelectTrigger>
          </TooltipTrigger>
          <TooltipContent side="top">{tooltip}</TooltipContent>
        </Tooltip>
        {children}
      </Select>
    </TooltipProvider>
  );
}
