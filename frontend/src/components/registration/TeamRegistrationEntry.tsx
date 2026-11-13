"use client";

import { useQuery } from "@tanstack/react-query";
import { UsersRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@craazzzyyfoxx/admin-kit/ui/dialog";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { slotCodesOf } from "@/lib/roster/shape";
import { isSignUpOpen, nodesOfKind } from "@/lib/tournament/flow-nodes";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { tournamentMyRegistrationQueryOptions } from "@/lib/tournament/registrations-query";
import registrationService from "@/services/registration.service";
import type { Tournament } from "@/types/tournament.types";

import type { RosterSlotOption } from "./RosterSlotPicker";
import TeamRegistrationWizard from "./TeamRegistrationWizard";

/**
 * The "Register a team" affordance: a button that OPENS the captain wizard.
 * Split out of `MyTeamSection` so it can sit in the tournament header. It first
 * shipped there as a link to the Teams tab, which made the primary action of a
 * team tournament a navigation step — and left two identical buttons on screen
 * once the tab rendered its own. On a team-registration tournament it is now the
 * ONLY header action: `TournamentRegisterButton` renders this instead of the solo
 * Register button, because one registration row per player means registering solo
 * silently forecloses founding a team.
 *
 * Renders nothing (rather than a disabled button) when the caller cannot act:
 * anonymous, registration closed, already registered, or already on a team. The
 * explanatory copy for the "already registered" case lives on the Teams tab next
 * to the roster, where there is room for a sentence.
 */
export default function TeamRegistrationEntry({
  tournament,
  registrationNodeId,
}: Readonly<{ tournament: Tournament; registrationNodeId: number }>) {
  const t = useTranslations("registrationTeams");
  const { status: authStatus, user } = useAuthProfile();
  const isAuthenticated = authStatus === "authenticated" && user != null;
  const [open, setOpen] = useState(false);

  const registrationNode = nodesOfKind(tournament, "registration").find((node) => node.id === registrationNodeId) ?? null;
  const registrationOpen = isSignUpOpen(registrationNode);

  const myRegQuery = useQuery({
    ...tournamentMyRegistrationQueryOptions(tournament, registrationNode),
    enabled: isAuthenticated,
  });
  const formQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationForm(tournament.workspace_id, tournament.id),
    queryFn: () => registrationService.getForm(tournament.id),
    enabled: isAuthenticated && registrationOpen,
  });

  if (!isAuthenticated || !registrationOpen) return null;
  // A live registration — solo or as a team member — means there is nothing to
  // found. Both are the same row; see `accept_invite`'s attach path.
  if (myRegQuery.data || !formQuery.data) return null;

  /**
   * Slots the captain may occupy, each with its multiplicity in the roster.
   * The server projects these from the tournament's frozen team format, including
   * open slots, and rejects any slot the projection does not define — so with no
   * projection there is no slot to offer, and none is invented.
   */
  const shape = tournament.roster_shape?.slots ?? {};
  const availableSlots: RosterSlotOption[] = slotCodesOf(shape).map((code) => ({
    code,
    count: shape[code] ?? 1,
  }));
  if (availableSlots.length === 0) return null;

  return (
    <>
      <Button type="button" variant="outline" onClick={() => setOpen(true)}>
        <UsersRound className="size-4" aria-hidden />
        {t("create.action")}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[94vh] overflow-y-auto sm:max-w-2xl lg:max-w-3xl">
          <DialogTitle>{t("create.titleFor", { name: tournament.name })}</DialogTitle>
          <TeamRegistrationWizard
            workspaceId={tournament.workspace_id}
            tournamentId={tournament.id}
            registrationNodeId={registrationNodeId}
            tournamentName={tournament.name}
            form={formQuery.data}
            availableSlots={availableSlots}
            onClose={() => setOpen(false)}
          />
        </DialogContent>
      </Dialog>
    </>
  );
}
