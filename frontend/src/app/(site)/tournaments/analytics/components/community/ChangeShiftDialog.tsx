"use client";

import React, { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { PlayerAnalytics } from "@/types/analytics.types";
import analyticsService from "@/services/analytics.service";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface ChangeShiftDialogProps {
  player: PlayerAnalytics;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Organizer-only manual shift editor. Persists the override and invalidates the
 * analytics queries so the view recomputes. Shared by the community player
 * detail and the expert team table.
 */
export default function ChangeShiftDialog({ player, open, onOpenChange }: ChangeShiftDialogProps) {
  const t = useTranslations();
  const [shift, setShift] = useState(player.shift ?? 0);
  const [saving, setSaving] = useState(false);
  const queryClient = useQueryClient();

  // Keep the input in sync if the same dialog instance is reused for another
  // player (defensive — the parent also re-keys PlayerDetail per player).
  useEffect(() => {
    setShift(player.shift ?? 0);
  }, [player.id, player.shift]);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      await analyticsService.patchPlayerShift(player.team_id, player.id, shift);
      await queryClient.invalidateQueries({ queryKey: ["analytics"] });
      onOpenChange(false);
    } catch {
      toast.error(t("analytics.page.unavailable"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{t("analytics.standings.editManualShift")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={onSubmit} className="grid gap-4">
          <div className="grid grid-cols-4 items-center gap-4">
            <Label htmlFor={`community-shift-${player.id}`} className="text-right">
              {t("analytics.standings.colManual")}
            </Label>
            <Input
              id={`community-shift-${player.id}`}
              value={shift}
              className="col-span-3"
              type="number"
              onChange={(event) => setShift(Number(event.target.value))}
            />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={saving}>
              {t("analytics.standings.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
