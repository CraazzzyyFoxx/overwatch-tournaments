"use client";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { MappingTargetMode } from "@/types/balancer-admin.types";

const MODE_LABELS: Record<MappingTargetMode, string> = {
  columns: "Map",
  constant: "Constant",
  disabled: "Disabled",
};

const MODE_ORDER: MappingTargetMode[] = ["columns", "constant", "disabled"];

interface ModeToggleProps {
  value: MappingTargetMode;
  onChange: (mode: MappingTargetMode) => void;
  disabled?: boolean;
}

export function ModeToggle({ value, onChange, disabled }: ModeToggleProps) {
  return (
    <ToggleGroup
      type="single"
      value={value}
      onValueChange={(next) => {
        if (next && next !== value) {
          onChange(next as MappingTargetMode);
        }
      }}
      variant="outline"
      size="sm"
    >
      {MODE_ORDER.map((mode) => (
        <ToggleGroupItem key={mode} value={mode} disabled={disabled} className="px-3 text-xs">
          {MODE_LABELS[mode]}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
