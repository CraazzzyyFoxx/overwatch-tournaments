"use client";

import { useQuery } from "@tanstack/react-query";
import { Crown, LifeBuoy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId } from "react";

import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { getRegistrationTeamStatus, REGISTRATION_TEAM_STATUS_TONE } from "@/lib/registration-team-tone";
import { ROSTER_SLOT_CODES, type RosterSlotCode } from "@/lib/roster-shape";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { cn } from "@/lib/utils";
import registrationService from "@/services/registration.service";
import registrationTeamService from "@/services/registration-team.service";
import type { RegistrationTeam, RegistrationTeamMember } from "@/types/registration-team.types";
import type { Tournament } from "@/types/tournament.types";

/** Canonical reading order of a roster: tank, damage, support, flex. */
const SLOT_RANK = new Map<string, number>(ROSTER_SLOT_CODES.map((code, index) => [code, index]));

function RosterRow({ member }: Readonly<{ member: RegistrationTeamMember }>) {
  const t = useTranslations();

  return (
    <li className="flex items-center gap-2 text-body">
      <RosterSlotGlyph code={member.slot_code} />
      {/* Name and its markers are one group: with the name on `flex-1` the crown
          drifted to the far edge of the card and read as a column of its own. */}
      <span className="flex min-w-0 items-center gap-1.5">
        <span className="truncate text-[color:var(--aqt-fg)]">
          {member.display_name ?? member.battle_tag ?? "—"}
        </span>
        {member.is_captain ? (
          <span
            className="inline-flex shrink-0 text-[color:var(--aqt-gold)]"
            title={t("registrationTeams.member.captain")}
          >
            <Crown className="size-3.5" aria-hidden />
            <span className="sr-only">{t("registrationTeams.member.captain")}</span>
          </span>
        ) : null}
        {member.is_substitute ? (
          <span
            className="inline-flex shrink-0 text-[color:var(--aqt-fg-dim)]"
            title={t("registrationTeams.member.substitute")}
          >
            <LifeBuoy className="size-3.5" aria-hidden />
            <span className="sr-only">{t("registrationTeams.member.substitute")}</span>
          </span>
        ) : null}
      </span>
    </li>
  );
}

/**
 * A slot nobody has taken yet, drawn in the roster instead of described under it.
 *
 * The shortfall used to be one sentence in the footer while the roster above it
 * was a list of glyphs — so the one question this section answers ("who can I
 * still join?") was the only thing you had to read rather than see. Drawing the
 * gap also stops a one-player card from being stretched to the height of a full
 * one by the grid, which was most of the dead space on this page.
 */
function OpenSlotRow({ code }: Readonly<{ code: RosterSlotCode }>) {
  const t = useTranslations();

  return (
    <li className="flex items-center gap-2 text-body opacity-60">
      <RosterSlotGlyph code={code} />
      <span className="truncate text-[color:var(--aqt-fg-muted)]">
        {t("registrationTeams.list.openSlot")}
      </span>
    </li>
  );
}

function RegistrationTeamCard({ team }: Readonly<{ team: RegistrationTeam }>) {
  const t = useTranslations();
  const headingId = useId();
  const status = getRegistrationTeamStatus(team);
  // Starters before substitutes, canonical slot order inside each, captain first
  // within a slot — the order a roster is read in, and the same shape in every
  // card so two rosters can be compared by looking at them.
  const roster = [...team.members].sort(
    (a, b) =>
      Number(a.is_substitute) - Number(b.is_substitute) ||
      (SLOT_RANK.get(a.slot_code ?? "") ?? ROSTER_SLOT_CODES.length) -
        (SLOT_RANK.get(b.slot_code ?? "") ?? ROSTER_SLOT_CODES.length) ||
      Number(b.is_captain) - Number(a.is_captain)
  );
  const openSlots = ROSTER_SLOT_CODES.flatMap((code) =>
    Array.from({ length: team.open_slots[code] ?? 0 }, () => code)
  );

  return (
    <article
      aria-labelledby={headingId}
      className="relative flex flex-col gap-3 overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] p-4 shadow-md backdrop-blur-md sm:p-5"
    >
      <header className="flex flex-wrap items-center justify-between gap-2">
        <Avatar className="size-7 shrink-0 rounded-md border border-[color:var(--aqt-border)]">
          {team.image_url ? <AvatarImage src={team.image_url} alt="" /> : null}
          <AvatarFallback className="rounded-md bg-[color:var(--aqt-overlay-2)] text-label font-semibold">
            {team.name.slice(0, 1).toUpperCase()}
          </AvatarFallback>
        </Avatar>
        <h3
          id={headingId}
          title={team.name}
          className="min-w-0 flex-1 truncate font-onest text-heading font-semibold text-[color:var(--aqt-fg)]"
        >
          {team.name}
        </h3>
        <Badge
          variant="outline"
          className={cn("shrink-0", REGISTRATION_TEAM_STATUS_TONE[status])}
        >
          {t(`registrationTeams.status.${status}`)}
        </Badge>
      </header>

      {/*
        Members and open slots only, never `team.invites`: the public endpoint
        omits them server-side precisely so the roster cannot leak who was asked
        and declined. Rendering them here would put that back.
      */}
      <ul className="flex flex-col gap-1.5">
        {roster
          .filter((member) => !member.is_substitute)
          .map((member) => (
            <RosterRow key={member.registration_id} member={member} />
          ))}
        {openSlots.map((code, index) => (
          <OpenSlotRow key={`${code}-${index}`} code={code} />
        ))}
        {roster
          .filter((member) => member.is_substitute)
          .map((member) => (
            <RosterRow key={member.registration_id} member={member} />
          ))}
      </ul>

      {/* Only once someone is actually on the bench: "0 of 2 substitutes" under
          every card is a tournament constant, not a fact about this team. The
          status pill above already carries "complete", and the missing slots are
          drawn in the list rather than spelled out again down here. */}
      {team.substitutes_used > 0 ? (
        <footer className="border-t border-[color:var(--aqt-border)] pt-2 text-caption text-[color:var(--aqt-fg-dim)]">
          {t("registrationTeams.list.substitutes", {
            used: team.substitutes_used,
            max: team.max_substitutes
          })}
        </footer>
      ) : null}
    </article>
  );
}

/**
 * The registered teams of a tournament, as cards.
 *
 * Lives on the Participants page rather than behind its own tab. A dedicated tab
 * put three sections in one conceptual space (`Teams`, `Participants`,
 * `Registered teams`) and, worse, duplicated the `Teams` tab outright once the
 * organizer exported: both then listed the same teams. Participants is where you
 * already go to see who entered, so the team view belongs above that list.
 *
 * The count includes the viewer's team, whose management panel appears above.
 */
export default function RegistrationTeamsList({
  tournament
}: Readonly<{ tournament: Tournament }>) {
  const t = useTranslations();
  const { status: authStatus, user } = useAuthProfile();
  const isAuthenticated = authStatus === "authenticated" && user != null;

  const teamsQuery = useQuery({
    queryKey: tournamentQueryKeys.registrationTeams(tournament.workspace_id, tournament.id),
    queryFn: () => registrationTeamService.listPublic(tournament.id)
  });
  // Same query key `MyTeamSection` already uses, so this is a cache read, not a
  // second request: a captain's own team is already shown in full detail above
  // (`MyTeamPanel`), so showing it again here as a third summary of the same
  // roster and shortfall would be the exact clutter this section exists to avoid.
  const myRegQuery = useQuery({
    queryKey: tournamentQueryKeys.registration(tournament.workspace_id, tournament.id),
    queryFn: () => registrationService.getMyRegistration(tournament.id),
    enabled: isAuthenticated
  });
  const myTeamId = myRegQuery.data?.team?.id ?? null;

  const activeTeams = (teamsQuery.data?.items ?? []).filter(
    (team) => team.status === "forming" || team.status === "complete",
  );
  const teams = activeTeams.filter((team) => team.id !== myTeamId);
  const totalTeams = activeTeams.length;
  const freeAgents = teamsQuery.data?.unassigned_players ?? 0;

  if (teamsQuery.isLoading || (isAuthenticated && myRegQuery.isLoading)) {
    return (
      <section className="flex flex-col gap-3">
        <Skeleton className="h-6 w-48" />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }, (_, index) => (
            <Skeleton key={index} className="h-48 w-full rounded-xl" />
          ))}
        </div>
      </section>
    );
  }

  if (teamsQuery.isError && !teamsQuery.data) {
    return (
      <section role="alert" className="grid gap-2 rounded-xl border border-[color:var(--aqt-border)] p-4">
        <h2 className="font-semibold">{t("registrationTeams.list.loadError")}</h2>
        <Button variant="outline" className="justify-self-start" onClick={() => void teamsQuery.refetch()}>
          {t("common.retry")}
        </Button>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="font-onest text-heading font-semibold text-[color:var(--aqt-fg)]">
          {t("registrationTeams.list.title")}
        </h2>
        <span className="text-body text-[color:var(--aqt-fg-muted)]">
          {t("registrationTeams.list.count", { count: totalTeams })}
        </span>
        {/* Muted, not amber: on this card amber means "roster still short", and
            free agents are an opportunity, not a warning. */}
        {freeAgents > 0 ? (
          <span className="text-body text-[color:var(--aqt-fg-dim)]">
            {t("registrationTeams.list.freeAgents", { count: freeAgents })}
          </span>
        ) : null}
      </div>
      <p className="text-sm text-[color:var(--aqt-fg-muted)]">
        {t("registrationTeams.list.stateHint")}
      </p>
      {myTeamId !== null && (
        <p className="text-sm text-[color:var(--aqt-fg-muted)]">{t("registrationTeams.list.ownTeamAbove")}</p>
      )}
      {totalTeams === 0 && (
        <p className="text-sm text-[color:var(--aqt-fg-muted)]">{t("registrationTeams.list.empty")}</p>
      )}
      {teamsQuery.isError && (
        <div role="alert" className="flex flex-wrap items-center gap-2">
          <span>{t("registrationTeams.list.loadError")}</span>
          <Button variant="outline" onClick={() => void teamsQuery.refetch()}>{t("common.retry")}</Button>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {teams.map((team) => (
          <RegistrationTeamCard key={team.id} team={team} />
        ))}
      </div>
    </section>
  );
}
