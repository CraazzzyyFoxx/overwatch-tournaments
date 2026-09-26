"use client";

import { useTranslations } from "next-intl";

import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { Registration, RegistrationListResponse } from "@/types/registration.types";
import type { Tournament } from "@/types/tournament.types";

import { PhaseTimeline } from "../../_components/PhaseTimeline";
import { CardLink, OverviewCard } from "./OverviewCards";
import { RegistrationSummary, StatTile } from "./RegistrationSummary";

/**
 * A: before the first whistle (§3A). The phase timeline IS the page, with the
 * registration figures and the format card under it.
 */
export function OverviewRegistrationView({
  tournament,
  registrationList,
  registrations,
  overviewHref,
  clockNow,
  formatCard,
  linksCard
}: Readonly<{
  tournament: Tournament;
  registrationList: RegistrationListResponse | null;
  registrations: readonly Registration[];
  overviewHref: string;
  clockNow: number | null;
  formatCard: React.ReactNode;
  linksCard: React.ReactNode;
}>) {
  const t = useTranslations();
  const format = useFormatter();

  const teamsCount = tournament.teams_count ?? 0;
  const submitted = [...registrations]
    .filter((registration) => registration.submitted_at !== null)
    .sort((left, right) => String(right.submitted_at).localeCompare(String(left.submitted_at)));
  const latest = submitted
    .slice(0, 3)
    .map((registration) => registration.battle_tag)
    .filter((tag): tag is string => typeof tag === "string" && tag.length > 0);
  const latestAt = submitted[0]?.submitted_at ?? null;
  const latestAgo =
    latestAt !== null && clockNow !== null
      ? format.relativeTime(new Date(latestAt), clockNow)
      : null;
  const isTeamRegistration = tournament.team_formation === "registration";
  // Both aside cards are optional, and an aside column holding nothing reads
  // as a broken layout rather than as restraint.
  const hasAside = linksCard !== null;

  return (
    <>
      {/* ① The phase timeline IS the page before the tournament starts. */}
      <OverviewCard id="phases">
        <PhaseTimeline tournament={tournament} orientation="horizontal" />
      </OverviewCard>

      <div className={cn("grid gap-4", hasAside && "lg:grid-cols-[6fr_4fr]")}>
        <div className={cn("grid content-start gap-4", !hasAside && "lg:grid-cols-2")}>
          {/* ② "Tanks are short" is what a draft/balancer tournament is read
              for; a team-registration one counts teams instead. */}
          <OverviewCard
            title={t("tournamentDetail.overview.registration.title")}
            action={
              <CardLink href={`${overviewHref}/participants`}>
                {t("tournamentDetail.overview.registration.all")}
              </CardLink>
            }
          >
            {isTeamRegistration ? (
              <div className="grid gap-2 sm:grid-cols-2">
                <StatTile
                  label={t("tournamentDetail.overview.registration.teams")}
                  value={String(teamsCount)}
                />
                <StatTile
                  label={t("tournamentDetail.overview.registration.total")}
                  value={String(registrationList?.total ?? tournament.registrations_count ?? 0)}
                  hint={
                    registrationList?.max_participants
                      ? `/ ${registrationList.max_participants}`
                      : undefined
                  }
                />
              </div>
            ) : (
              <>
                {/* "Tanks are short" — the same figures the participants page
                    falls back to when the roster itself is hidden. */}
                <RegistrationSummary
                  total={registrationList?.total ?? registrations.length}
                  roleCounts={registrationList?.role_counts ?? {}}
                  maxParticipants={registrationList?.max_participants}
                />
                {latest.length > 0 ? (
                  <p className="mt-2 truncate text-caption text-[color:var(--aqt-fg-faint)]">
                    {t("tournamentDetail.overview.registration.latest")}: {latest.join(" · ")}
                    {latestAgo ? ` · ${latestAgo}` : null}
                  </p>
                ) : null}
              </>
            )}
          </OverviewCard>

          {formatCard}
        </div>

        {/* Organizer links — the same tail the other two branches end on. */}
        {hasAside ? (
          <div className="grid content-start gap-4">
            {linksCard}
          </div>
        ) : null}
      </div>
    </>
  );
}
