"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { PRESET_IDS, type PresetId } from "@/lib/flow/presets";

export type PresetParams = { days: number; best: number };

/** The preset list; the league also asks for its length and how many results count. */
export function PresetDialog({
  open,
  onOpenChange,
  onApply
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onApply: (preset: PresetId, params: PresetParams) => void;
}>) {
  const t = useTranslations("adminTournament.flow.presets");
  const [preset, setPreset] = useState<PresetId>("single");
  const [days, setDays] = useState<number | null>(3);
  const [best, setBest] = useState<number | null>(2);

  const valid = preset !== "league" || (days !== null && best !== null && days >= 2 && days <= 10 && best >= 1 && best <= days);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription className="sr-only">{t("title")}</DialogDescription>
        </DialogHeader>
        <RadioGroup value={preset} onValueChange={(value) => setPreset(value as PresetId)}>
          {PRESET_IDS.map((id) => (
            <Label key={id} className="flex items-center gap-2 font-normal">
              <RadioGroupItem value={id} />
              {t(`ids.${id}`)}
            </Label>
          ))}
        </RadioGroup>
        {preset === "league" ? (
          <div className="grid grid-cols-2 gap-3">
            <Label className="grid gap-1.5">
              {t("days")}
              <NumberInput integer min={2} max={10} value={days} onValueChange={setDays} />
            </Label>
            <Label className="grid gap-1.5">
              {t("best")}
              <NumberInput integer min={1} max={days ?? 10} value={best} onValueChange={setBest} />
            </Label>
          </div>
        ) : null}
        <DialogFooter>
          <Button
            type="button"
            disabled={!valid}
            onClick={() => onApply(preset, { days: days ?? 3, best: best ?? 2 })}
          >
            {t("apply")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
