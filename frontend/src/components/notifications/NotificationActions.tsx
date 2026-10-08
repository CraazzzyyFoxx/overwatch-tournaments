"use client";

import { useMutation } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { translateRegistrationTeamError } from "@/lib/registration/team-errors";
import { cn } from "@/lib/utils";
import registrationTeamService from "@/services/registration-team.service";
import registrationService from "@/services/registration.service";
import type { NotificationItem } from "@/types/notification.types";

/** What a resolved row says afterwards — also the message key under `notifications.actions`. */
export type ResolvedAction = "checkedIn" | "accepted" | "declined";

interface NotificationActionsProps {
  item: NotificationItem;
  /** Lifted: the bell row and the floating card both outlive this component's mutation. */
  done: ResolvedAction | null;
  onResolved: (action: ResolvedAction) => void;
  /** Wrapper spacing — a row indents the buttons, the urgent card does not. */
  className?: string;
}

/**
 * The one-click answer a notification carries: a check-in, or an invite to take
 * or refuse. Both ids travel in the payload (`tournament_id`, `invite_id`), so
 * neither action has to resolve anything first; a row missing its id renders no
 * buttons at all and stays a plain link to the tournament.
 */
export function NotificationActions({ item, done, onResolved, className }: NotificationActionsProps) {
  const t = useTranslations("notifications.actions");
  const tErrors = useTranslations("registrationTeams.errors");

  const tournamentId = item.payload.tournament_id;
  const inviteId = item.payload.invite_id;

  const checkIn = useMutation({
    mutationFn: () => registrationService.checkInMyRegistration(tournamentId as number),
    meta: { suppressErrorToast: true },
    onSuccess: () => onResolved("checkedIn")
  });
  const answerInvite = useMutation({
    mutationFn: async (answer: "accepted" | "declined") => {
      if (answer === "accepted") await registrationTeamService.accept({ invite_id: inviteId as number });
      else await registrationTeamService.decline({ invite_id: inviteId as number });
      return answer;
    },
    meta: { suppressErrorToast: true },
    onSuccess: (answer) => onResolved(answer)
  });

  if (done) {
    return (
      <p
        className={cn(
          "flex items-center gap-1.5 text-caption font-semibold text-[color:var(--aqt-emerald)]",
          className
        )}
      >
        <Check className="size-3.5" aria-hidden />
        {t(done)}
      </p>
    );
  }

  const isCheckIn = item.kind === "check_in.opened" && typeof tournamentId === "number";
  const isInvite = item.kind === "team_invite.received" && typeof inviteId === "number";
  if (!isCheckIn && !isInvite) return null;

  const pending = checkIn.isPending || answerInvite.isPending;
  const error = checkIn.error ?? answerInvite.error;

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="flex flex-wrap items-center gap-2">
        {isCheckIn ? (
          <Button
            static={false}
            size="sm"
            className="h-8 px-3 text-caption"
            aria-busy={pending}
            disabled={pending}
            onClick={() => checkIn.mutate()}
          >
            {t(pending ? "working" : "checkIn")}
          </Button>
        ) : (
          <>
            <Button
              static={false}
              size="sm"
              className="h-8 px-3 text-caption"
              aria-busy={answerInvite.isPending && answerInvite.variables === "accepted"}
              disabled={pending}
              onClick={() => answerInvite.mutate("accepted")}
            >
              {t("accept")}
            </Button>
            <Button
              static={false}
              variant="outline"
              size="sm"
              className="h-8 border-[color:var(--aqt-border-2)] px-3 text-caption"
              aria-busy={answerInvite.isPending && answerInvite.variables === "declined"}
              disabled={pending}
              onClick={() => answerInvite.mutate("declined")}
            >
              {t("decline")}
            </Button>
          </>
        )}
      </div>
      {error ? (
        <p role="alert" className="text-caption text-[color:var(--aqt-rose-text)]">
          {translateRegistrationTeamError(tErrors, error, t("failed"))}
        </p>
      ) : null}
    </div>
  );
}
