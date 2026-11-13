"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { DEFAULT_PRESET_CHOICE, PresetPicker, presetChoiceValid } from "@/components/admin/tournaments/PresetPicker";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@craazzzyyfoxx/admin-kit/ui/dialog";
import type { PresetId } from "@/lib/flow/presets";

export type PresetParams = { days: number; best: number };

/** The preset list in a dialog, for a tournament whose flow is still the untouched starter pair. */
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
  const [choice, setChoice] = useState(DEFAULT_PRESET_CHOICE);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription className="sr-only">{t("title")}</DialogDescription>
        </DialogHeader>
        <PresetPicker value={choice} onChange={setChoice} />
        <DialogFooter>
          <Button
            type="button"
            disabled={!presetChoiceValid(choice)}
            onClick={() => onApply(choice.preset, { days: choice.days ?? 3, best: choice.best ?? 2 })}
          >
            {t("apply")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
