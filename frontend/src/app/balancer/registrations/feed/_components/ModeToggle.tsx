"use client";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { MappingTargetMode } from "@/types/balancer-admin.types";

const MODE_LABELS: Record<MappingTargetMode, string> = {
  columns: "Map",
  constant: "Constant",
  disabled: "Disabled",
  auto: "Auto",
};

const DEFAULT_MODES: MappingTargetMode[] = ["columns", "constant", "disabled"];

interface ModeToggleProps {
  value: MappingTargetMode;
  onChange: (mode: MappingTargetMode) => void;
  availableModes?: MappingTargetMode[];
  disabled?: boolean;
}

export function ModeToggle({ value, onChange, availableModes, disabled }: ModeToggleProps) {
  const modes = availableModes ?? DEFAULT_MODES;
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
      {modes.map((mode) => (
        <ToggleGroupItem key={mode} value={mode} disabled={disabled} className="px-3 text-xs">
          {MODE_LABELS[mode]}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
