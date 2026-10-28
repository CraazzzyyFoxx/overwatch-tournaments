"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { MatchReportForm, matchReportDraftKey } from "@/components/tournaments/MatchReportForm";
import { seatsBySlot } from "@/lib/encounter/seats";
import type { Encounter } from "@/types/encounter.types";

interface MatchReportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  encounter: Encounter;
}

/**
 * The series report as a modal, for the bracket and the encounter page. The
 * form itself is `MatchReportForm`, which the pre-game room mounts inline as
 * the last step of its loop — this file is only the shell.
 */
export function MatchReportDialog({ open, onOpenChange, encounter }: Readonly<MatchReportDialogProps>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open ? <MatchReportDialogBody encounter={encounter} onOpenChange={onOpenChange} /> : null}
    </Dialog>
  );
}

function MatchReportDialogBody({
  encounter,
  onOpenChange
}: Readonly<Omit<MatchReportDialogProps, "open">>) {
  const t = useTranslations();

  return (
    <DialogContent className="max-w-lg">
      <DialogHeader>
        <DialogTitle>{t("matchReport.title")}</DialogTitle>
        <DialogDescription>
          {seatsBySlot(encounter.teams).map((seat) => seat.name).join(" vs ")}
        </DialogDescription>
      </DialogHeader>

      <MatchReportForm
        key={matchReportDraftKey(encounter)}
        encounter={encounter}
        onSubmitted={() => onOpenChange(false)}
        fieldsClassName="max-h-[70vh] overflow-y-auto pr-1 mt-2"
        cancelAction={
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            size="lg"
          >
            {t("matchEdit.cancel")}
          </Button>
        }
      />
    </DialogContent>
  );
}
