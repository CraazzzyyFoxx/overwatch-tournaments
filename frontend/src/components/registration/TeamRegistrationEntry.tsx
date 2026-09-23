"use client";

import { useQuery } from "@tanstack/react-query";
import { UsersRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { ROLES } from "@/lib/roster/roles";
import { isRegistrationOpen } from "@/lib/tournament/status";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
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
}: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations("registrationTeams");
  const { status: authStatus, user } = useAuthProfile();
  const isAuthenticated = authStatus === "authenticated" && user != null;
  const [open, setOpen] = useState(false);

  const registrationOpen = isRegistrationOpen(tournament);

  const myRegQuery = useQuery({
    queryKey: tournamentQueryKeys.registration(tournament.workspace_id, tournament.id),
    queryFn: () => registrationService.getMyRegistration(tournament.id),
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
   * Constrained to the tournament's roster override when it has one, because the
   * server rejects a slot the shape does not define (`slot_not_in_shape`). An
   * all-`flex` roster yields none and the entry hides — that shape needs a slot
   * picker this UI does not have yet.
   */
  const override = tournament.roster_slots_json ?? null;
  const availableSlots: RosterSlotOption[] = ROLES.filter(
    (role) => !override || (override[role.code] ?? 0) > 0,
  ).map((role) => ({ code: role.code, count: override?.[role.code] ?? 1 }));
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
