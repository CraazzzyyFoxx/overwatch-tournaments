"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Clock, LogIn, UserPlus, XCircle } from "lucide-react";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { getCurrentPathForAuthRedirect } from "@/lib/auth/redirect";
import { cn } from "@/lib/utils";
import { isRegistrationOpen } from "@/lib/tournament/status";
import { reachedAtLeast } from "@/lib/tournament/lifecycle";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useAuthModalStore } from "@/stores/auth-modal.store";
import registrationService from "@/services/registration.service";
import { tournamentHref } from "@/lib/tournament/url";
import type { Tournament } from "@/types/tournament.types";

import { useTranslations } from "next-intl";
import RegistrationWizard from "@/components/registration/RegistrationWizard";
import TeamRegistrationEntry from "@/components/registration/TeamRegistrationEntry";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

type Props = {
  tournament: Tournament;
  /** `sm` (the collapsed rail): every state at the rail's 32px control height. */
  size?: "default" | "sm";
};

export default function TournamentRegisterButton({
  tournament,
  size = "default"
}: Readonly<Props>) {
  const small = size === "sm";
  const workspaceId = tournament.workspace_id;
  const tournamentId = tournament.id;
  const tournamentName = tournament.name;
  const t = useTranslations();
  const { user, status: authStatus } = useAuthProfile();
  const openAuthModal = useAuthModalStore((state) => state.open);
  const isAuthenticated = authStatus === "authenticated" && user !== null;
  const [showModal, setShowModal] = useState(false);

  const formQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationForm(workspaceId, tournamentId),
    queryFn: () => registrationService.getForm(tournamentId)
  });

  const myRegQuery = useQuery({
    queryKey: tournamentQueryKeys.registration(workspaceId, tournamentId),
    queryFn: () => registrationService.getMyRegistration(tournamentId),
    enabled: isAuthenticated
  });

  const form = formQuery.data;
  const myReg = myRegQuery.data;
  const handleAuthClick = () => {
    const nextPath =
      typeof window === "undefined"
        ? tournamentHref(tournament)
        : getCurrentPathForAuthRedirect(window.location);

    openAuthModal(nextPath);
  };

  if (formQuery.isLoading) return null;
  if (!form) return null;
  // Who is asking is unknown until the profile resolves, and the server render
  // and hydration always see "idle" — with the form seeded server-side, a
  // signed-in viewer would otherwise be offered "Login to register" first, and
  // a registered one "Registration closed" before their own status.
  if (authStatus === "idle" || authStatus === "loading") return null;
  if (isAuthenticated && myRegQuery.isLoading) return null;

  // The viewer's own registration, for as long as it is news: through check-in
  // and the forming of the teams, open window or not. Once the matches are on,
  // the slot belongs to what the tournament is doing.
  if (myReg && !reachedAtLeast(tournament.status, "live")) {
    const statusMap: Record<string, { icon: typeof Clock; label: string; className: string }> = {
      pending: {
        icon: Clock,
        label: t("common.pendingReview"),
        className:
          "border-[color:color-mix(in_srgb,var(--aqt-amber)_20%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_10%,transparent)] text-[color:var(--aqt-amber)]"
      },
      approved: {
        icon: CheckCircle2,
        label: t("common.approved"),
        className:
          "border-[color:color-mix(in_srgb,var(--aqt-emerald)_20%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-emerald)_10%,transparent)] text-[color:var(--aqt-emerald)]"
      },
      rejected: {
        icon: XCircle,
        label: t("common.rejected"),
        className:
          "border-[color:color-mix(in_srgb,var(--aqt-rose)_20%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-rose)_10%,transparent)] text-[color:var(--aqt-rose)]"
      },
      withdrawn: {
        icon: XCircle,
        label: t("common.withdrawn"),
        className:
          "border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg-muted)]"
      }
    };
    const config = statusMap[myReg.status] ?? statusMap.pending;
    const StatusIcon = config.icon;
    return (
      <HoverPrefetchLink
        href={tournamentHref(tournament, "/participants")}
        className={cn(
          "inline-flex items-center gap-2 rounded-lg border font-medium transition-opacity hover:opacity-80",
          small ? "h-8 px-3 text-caption" : "px-4 py-2 text-sm",
          config.className
        )}
      >
        <StatusIcon className="size-4" aria-hidden />
        {config.label}
      </HoverPrefetchLink>
    );
  }

  // The form must exist (checked above) but no longer decides openness — the
  // tournament's REGISTRATION schedule window does.
  if (!isRegistrationOpen(tournament)) {
    // Someone may still come to sign up while the tournament registers or
    // checks in. From the forming of the teams on nobody asks, and a dead box
    // would be the loudest thing in the hero.
    if (reachedAtLeast(tournament.status, "draft")) return null;
    return (
      // A STATE, not a control: the subtle button's box and palette, without the hover a click would need.
      <div
        className={cn(
          "inline-flex items-center gap-2 rounded-md border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] font-medium text-[color:var(--aqt-fg-dim)]",
          small ? "h-8 px-3 text-caption" : "h-9 px-4 text-sm"
        )}
      >
        <Clock className="size-4" aria-hidden />
        {t("registration.button.closed")}
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <Button type="button" size={small ? "sm" : "default"} onClick={handleAuthClick}>
        <LogIn aria-hidden />
        {t("registration.button.loginToRegister")}
      </Button>
    );
  }

  // A team-registration tournament has ONE way in: found a team, or accept a
  // captain's invite. The solo button used to stand beside it, which let a player
  // spend their single registration row (there is one per player) on a free-agent
  // slot nobody had asked them for — and once spent, founding a team is
  // foreclosed. `TeamRegistrationEntry` hides itself for a viewer who cannot act,
  // so this renders nothing rather than a dead control.
  if (tournament.team_formation === "registration") {
    return <TeamRegistrationEntry tournament={tournament} />;
  }

  return (
    <>
      <Button type="button" size={small ? "sm" : "default"} onClick={() => setShowModal(true)}>
        <UserPlus aria-hidden />
        {t("registration.button.register")}
      </Button>
      <Dialog open={showModal} onOpenChange={setShowModal}>
        <DialogContent className="max-h-[94vh] overflow-y-auto sm:max-w-2xl lg:max-w-3xl">
          <DialogTitle className="sr-only">
            {tournamentName
              ? t("registration.wizard.titleFor", { name: tournamentName })
              : t("registration.wizard.title")}
          </DialogTitle>
          <RegistrationWizard
            workspaceId={workspaceId}
            tournamentId={tournamentId}
            tournamentName={tournamentName}
            form={form}
            onClose={() => setShowModal(false)}
          />
        </DialogContent>
      </Dialog>
    </>
  );
}
