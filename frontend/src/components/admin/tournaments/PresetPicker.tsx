"use client";

import { useTranslations } from "next-intl";

import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { PRESET_IDS, type PresetId } from "@/lib/flow/presets";

export type PresetChoice = { preset: PresetId; days: number | null; best: number | null };

export const DEFAULT_PRESET_CHOICE: PresetChoice = { preset: "single", days: 3, best: 2 };

/** The league needs 2..10 days and 1..days counted results; every other preset takes no parameters. */
export const presetChoiceValid = ({ preset, days, best }: PresetChoice): boolean =>
  preset !== "league" || (days !== null && best !== null && days >= 2 && days <= 10 && best >= 1 && best <= days);

/** The preset list; the league also asks for its length and how many results count. */
export function PresetPicker({
  value,
  onChange
}: Readonly<{ value: PresetChoice; onChange: (next: PresetChoice) => void }>) {
  const t = useTranslations("adminTournament.flow.presets");
  return (
    <>
      <RadioGroup value={value.preset} onValueChange={(preset) => onChange({ ...value, preset: preset as PresetId })}>
        {PRESET_IDS.map((id) => (
          <Label key={id} className="flex items-center gap-2 font-normal">
            <RadioGroupItem value={id} />
            {t(`ids.${id}`)}
          </Label>
        ))}
      </RadioGroup>
      {value.preset === "league" ? (
        <div className="grid grid-cols-2 gap-3">
          <Label className="grid gap-1.5">
            {t("days")}
            <NumberInput integer min={2} max={10} value={value.days} onValueChange={(days) => onChange({ ...value, days })} />
          </Label>
          <Label className="grid gap-1.5">
            {t("best")}
            <NumberInput
              integer
              min={1}
              max={value.days ?? 10}
              value={value.best}
              onValueChange={(best) => onChange({ ...value, best })}
            />
          </Label>
        </div>
      ) : null}
    </>
  );
}
