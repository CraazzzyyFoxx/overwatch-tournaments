"use client";

import { cn } from "@/lib/utils";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";

export const AqtSelect = ({
  value,
  onChange,
  options,
  title,
  width = "w-[150px]"
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  title?: string;
  width?: string;
}) => (
  <Select value={value} onValueChange={onChange}>
    <SelectTrigger
      title={title}
      className={cn(
        "aqt-tnum h-8 shadow-none border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-caption text-[color:var(--aqt-fg-muted)] hover:border-[color:var(--aqt-border-2)] hover:bg-[hsl(0_0%_100%/0.04)] focus:ring-1 focus:ring-[color:var(--aqt-teal)] focus:ring-offset-0",
        width
      )}
    >
      <SelectValue />
    </SelectTrigger>
    <SelectContent className="max-h-[min(var(--radix-select-content-available-height),20rem)]">
      {options.map((o) => (
        <SelectItem key={o.value} value={o.value}>
          {o.label}
        </SelectItem>
      ))}
    </SelectContent>
  </Select>
);
