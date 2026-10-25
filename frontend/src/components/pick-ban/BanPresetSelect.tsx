"use client";

import { useTranslations } from "next-intl";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useHeroBanPresets } from "@/hooks/useHeroBanPresets";

const NONE = "none";

/** A mix ban preset's name as players read it: its label, the code itself for one the copy lacks, or "no bans". */
export function useBanPresetName(): (code: string | null) => string {
  const tPreset = useTranslations("pickBan.rules.preset");
  const t = useTranslations("pickBan.mixBans");
  return (code) => {
    if (code == null) return t("none");
    const key = code as "hero_classic";
    return tPreset.has(key) ? tPreset(key) : code;
  };
}

/** A mix's hero ban preset (or a host's default for a game): one of the game's mix presets, or none. */
export function BanPresetSelect({
  discipline,
  value,
  onChange,
  disabled = false,
  id,
  label,
}: Readonly<{
  discipline: string;
  value: string | null;
  onChange: (preset: string | null) => void;
  disabled?: boolean;
  id?: string;
  label: string;
}>) {
  const nameOf = useBanPresetName();
  const presets = useHeroBanPresets(discipline);
  // A stored code the catalog no longer lists stays visible rather than reading as "none".
  const options = value != null && !presets.includes(value) ? [...presets, value] : presets;
  return (
    <Select value={value ?? NONE} disabled={disabled} onValueChange={(next) => onChange(next === NONE ? null : next)}>
      <SelectTrigger id={id} aria-label={label} size="sm" className="w-64">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>{nameOf(null)}</SelectItem>
        {options.map((code) => (
          <SelectItem key={code} value={code}>
            {nameOf(code)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
