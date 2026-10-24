"use client";

import React, { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { analyticsQueryKeys } from "@/lib/analytics/query-keys";
import { notify } from "@/lib/notify";
import analyticsService from "@/services/analytics.service";
import type { PlayerAnalytics } from "@/types/analytics.types";

interface ChangeShiftDialogProps {
  player: PlayerAnalytics;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * The form inside the dialog. The dialog mounts its content only while open, so
 * every opening starts from the player's saved shift — no effect to resync it.
 */
function ShiftForm({ player, onSaved }: Readonly<{ player: PlayerAnalytics; onSaved: () => void }>) {
  const t = useTranslations();
  const [shift, setShift] = useState<number | null>(player.shift ?? 0);
  const [saving, setSaving] = useState(false);
  const queryClient = useQueryClient();
  const fieldId = `analytics-shift-${player.id}`;

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (shift === null) return;
    setSaving(true);
    try {
      await analyticsService.patchPlayerShift(player.id, shift);
      await queryClient.invalidateQueries({ queryKey: analyticsQueryKeys.all() });
      onSaved();
    } catch (error) {
      notify.apiError(error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <div className="grid gap-2">
        <Label htmlFor={fieldId}>{t("analytics.standings.colManual")}</Label>
        <NumberInput id={fieldId} value={shift} onValueChange={setShift} integer />
      </div>
      <DialogFooter>
        <Button type="submit" disabled={saving || shift === null}>
          {t("analytics.standings.save")}
        </Button>
      </DialogFooter>
    </form>
  );
}

/**
 * Organizer-only manual shift editor, shared by the player panel and the Table
 * view. Persists the override and invalidates the analytics reads so the page
 * recomputes; a refused save keeps the dialog open with the API's reason.
 */
export default function ChangeShiftDialog({ player, open, onOpenChange }: Readonly<ChangeShiftDialogProps>) {
  const t = useTranslations();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[25rem]">
        <DialogHeader>
          <DialogTitle>{t("analytics.standings.editManualShift")}</DialogTitle>
        </DialogHeader>
        <ShiftForm key={player.id} player={player} onSaved={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}
