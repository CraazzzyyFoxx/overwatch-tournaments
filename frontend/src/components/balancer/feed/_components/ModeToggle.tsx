"use client";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useTranslations } from "next-intl";
import type { MappingTargetMode } from "@/types/balancer-admin.types";

const DEFAULT_MODES: MappingTargetMode[] = ["columns", "constant", "disabled"];

interface ModeToggleProps {
  value: MappingTargetMode;
  onChange: (mode: MappingTargetMode) => void;
  /** The mapped field's label; names the group ("Rank: value source"). */
  fieldLabel: string;
  availableModes?: MappingTargetMode[];
  disabled?: boolean;
}

export function ModeToggle({ value, onChange, fieldLabel, availableModes, disabled }: Readonly<ModeToggleProps>) {
  const t = useTranslations("sheetsFeed.controls");
  const modes = availableModes ?? DEFAULT_MODES;
  return (
    <ToggleGroup
      value={value}
      onValueChange={(next) => {
        if (next && next !== value) {
          onChange(next as MappingTargetMode);
        }
      }}
      size="sm"
      aria-label={t("modeFor", { field: fieldLabel })}
    >
      {modes.map((mode) => (
        <ToggleGroupItem key={mode} value={mode} disabled={disabled}>
          {t(`modes.${mode}`)}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
