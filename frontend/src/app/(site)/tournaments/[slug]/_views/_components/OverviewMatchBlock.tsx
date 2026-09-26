"use client";

import { useTranslations } from "next-intl";

import type { Encounter } from "@/types/encounter.types";

import { MatchCard } from "../../_components/MatchCard";
import { MatchRow } from "../../_components/MatchRow";
import { TournamentPageState } from "../../_components/TournamentPageState";
import { selectOverviewMatchLists } from "../tournamentOverview.model";
import type { OverviewMatchPresenter } from "../useOverviewMatchPresenter";
import { CardLink, OverviewCard } from "./OverviewCards";

/**
 * ⑤ Live first and framed; nothing live falls back to the schedule, and
 * without a schedule to the last results.
 */
export function OverviewMatchBlock({
  encounters,
  clockNow,
  overviewHref,
  presenter
}: Readonly<{
  encounters: readonly Encounter[];
  clockNow: number | null;
  overviewHref: string;
  presenter: OverviewMatchPresenter;
}>) {
  const t = useTranslations();
  const { live, upcoming, recent, pending } = selectOverviewMatchLists(encounters, clockNow);

  const matchRows = (rows: Encounter[], withTime: boolean) => (
    <div>
      {rows.map((encounter) => (
        <MatchRow
          key={encounter.id}
          encounter={encounter}
          leading={
            (withTime ? presenter.clock(encounter.scheduled_at) : null) ??
            presenter.encounterRound(encounter)
          }
          trailing={encounter.best_of ? `Bo${encounter.best_of}` : undefined}
          bracketHref={presenter.bracketHref(encounter)}
          returnTo={overviewHref}
        />
      ))}
    </div>
  );

  if (live.length > 0) {
    return (
      <OverviewCard
        title={t("tournamentDetail.overview.live.title")}
        action={
          <CardLink href={`${overviewHref}/matches`}>
            {t("tournamentDetail.overview.live.all")}
          </CardLink>
        }
      >
        <div className="grid gap-2 sm:grid-cols-2">
          {live.map((encounter) => (
            <MatchCard
              key={encounter.id}
              encounter={encounter}
              eyebrow={presenter.eyebrowOf(encounter)}
              href={presenter.bracketHref(encounter)}
              streamsCount={presenter.streamsCountOf(encounter)}
            />
          ))}
        </div>
      </OverviewCard>
    );
  }
  if (upcoming.length > 0) {
    return (
      <OverviewCard
        title={t("tournamentDetail.overview.upcoming.title")}
        action={
          <CardLink href={`${overviewHref}/matches?view=time`}>
            {t("tournamentDetail.overview.live.all")}
          </CardLink>
        }
      >
        {matchRows(upcoming, true)}
      </OverviewCard>
    );
  }
  if (recent.length > 0) {
    return (
      <OverviewCard
        title={t("tournamentDetail.overview.recent.title")}
        action={
          <CardLink href={`${overviewHref}/matches`}>
            {t("tournamentDetail.overview.live.all")}
          </CardLink>
        }
      >
        {matchRows(recent, false)}
      </OverviewCard>
    );
  }
  if (pending.length > 0) {
    return (
      <OverviewCard
        title={t("tournamentDetail.overview.upcoming.title")}
        action={
          <CardLink href={`${overviewHref}/matches`}>
            {t("tournamentDetail.overview.live.all")}
          </CardLink>
        }
      >
        {matchRows(pending, false)}
      </OverviewCard>
    );
  }
  return (
    <TournamentPageState
      state="empty"
      title={t("tournamentDetail.overview.empty.title")}
      description={t("tournamentDetail.overview.empty.description")}
    />
  );
}
