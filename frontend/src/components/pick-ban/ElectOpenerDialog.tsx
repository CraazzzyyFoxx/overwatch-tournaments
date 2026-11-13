"use client";

import { useState } from "react";
import { Shuffle } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@craazzzyyfoxx/admin-kit/ui/alert-dialog";
import { notify } from "@/lib/notify";
import pickBanService from "@/services/pickBan.service";
import type { PickBanKind } from "@/types/tournament.types";
import { Spinner } from "@craazzzyyfoxx/admin-kit/ui/spinner";
import type { PickBanSeat } from "./pick-ban-model";

interface ElectOpenerDialogProps {
  kind: PickBanKind;
  encounterId: number;
  open: boolean;
  /** The participations that may open the round, in slot order. */
  seats: PickBanSeat[];
  queryKey: unknown[];
}

/**
 * Modal shown to the losing captain when `PickBanSession.awaiting_choice` is
 * true (`first_ban_rotation: result_loser_choice`). The backend enforces who
 * may submit this — `open` alone gates VISIBILITY, not authorization.
 */
export function ElectOpenerDialog({ kind, encounterId, open, seats, queryKey }: Readonly<ElectOpenerDialogProps>) {
  const t = useTranslations("pickBan.room");
  const queryClient = useQueryClient();
  const [choice, setChoice] = useState<number | null>(null);

  const mutation = useMutation({
    mutationFn: (first_team_id: number) => pickBanService.electOpener(kind, encounterId, { first_team_id }),
    onError: (error) => notify.apiError(error, { title: t("electOpener.failed") }),
    onSettled: () => {
      setChoice(null);
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  return (
    <AlertDialog open={open}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <Shuffle className="h-5 w-5" aria-hidden />
            {t("electOpener.title")}
          </AlertDialogTitle>
          <AlertDialogDescription>{t("electOpener.hint")}</AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex flex-col gap-2 sm:flex-row">
          {seats.map((seat) => (
            <Button
              key={seat.id}
              variant={choice === seat.id ? "accent" : "outline"}
              className="flex-1"
              onClick={() => setChoice(seat.id)}
            >
              {t("electOpener.choose", { team: seat.name })}
            </Button>
          ))}
        </div>
        <AlertDialogFooter>
          <Button
            disabled={choice == null || mutation.isPending}
            onClick={() => {
              if (choice != null) mutation.mutate(choice);
            }}
          >
            {mutation.isPending ? <Spinner className="mr-2" /> : null}
            {mutation.isPending ? t("electOpener.sending") : t("electOpener.confirm")}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
