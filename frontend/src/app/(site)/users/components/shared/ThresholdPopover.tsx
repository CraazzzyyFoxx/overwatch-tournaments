"use client";

import { SlidersHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

/**
 * A sample floor behind a "Min X: N" trigger: the floor's choices as a pill
 * segment, named by `label`, with `hint` saying why the floor exists.
 */
export function ThresholdPopover({
  label,
  hint,
  triggerLabel,
  value,
  options,
  onChange,
  align = "start"
}: Readonly<{
  /** Names the segment: its eyebrow and the radiogroup's accessible name. */
  label: string;
  hint: string;
  /** The trigger's text, e.g. "Min games: 5". */
  triggerLabel: string;
  value: number;
  options: readonly number[];
  onChange: (value: number) => void;
  align?: "start" | "end";
}>) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="justify-start">
          <SlidersHorizontal aria-hidden className="opacity-70" />
          {triggerLabel}
        </Button>
      </PopoverTrigger>
      <PopoverContent align={align} className="w-64 space-y-2">
        <Eyebrow as="p">{label}</Eyebrow>
        <ToggleGroup
          variant="pill"
          size="sm"
          value={String(value)}
          onValueChange={(next) => next && onChange(Number(next))}
          aria-label={label}
          className="w-full"
        >
          {options.map((option) => (
            <ToggleGroupItem key={option} value={String(option)} className="flex-1">
              {option}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <p className="text-caption text-[color:var(--aqt-fg-dim)]">{hint}</p>
      </PopoverContent>
    </Popover>
  );
}
