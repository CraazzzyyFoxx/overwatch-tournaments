"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { useCatalogEntities } from "@/hooks/useCatalogEntities";
import { tournamentPicture } from "@/lib/tournament/art";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { stageProgress } from "@/lib/tournament/stage-progress";
import { getTournamentStatusMeta } from "@/lib/tournament/status";
import { tournamentHref } from "@/lib/tournament/url";
import { formatDateRange } from "@/lib/datetime";
import { useFormatter } from "@/lib/datetime/client";
import encounterService from "@/services/encounter.service";
import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { TournamentCover } from "@/components/tournaments/TournamentCover";
import { Progress } from "@/components/ui/progress";
import { GameLabel } from "@/components/workspace/GameLabel";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { TeamFormation, Tournament } from "@/types/tournament.types";

/**
 * One tournament in the card view.
 *
 * The whole card is a single `<Link>`: the row view already learnt that nesting
 * interactive elements (a bracket shortcut inside a card-wide target) leaves
 * keyboard users with duplicated stops and screen readers with two competing
 * names for one object. Deep links to sub-routes stay in the list view.
 *
 * Both images are `alt=""`: the name, dates and counters directly below carry
 * every fact the picture does, so announcing the artwork adds only noise.
 */
const TournamentCard = ({
  tournament,
  games
}: {
  tournament: Tournament;
  /** Installed games by code, passed only when the list spans several games (spec §6.1). */
  games?: Map<string, DisciplineDescriptor>;
}) => {
  const t = useTranslations();
  const format = useFormatter();
  const { variant } = getTournamentStatusMeta(tournament.status);
  const isFinished = variant === "finished";
  const stage = stageProgress(tournament, tournament.status, t);
  const players = tournament.participants_count ?? 0;
  const teams = tournament.teams_count;
  // Only a card without a cover reads anything for its picture: the map last
  // played in it, else its game's maps (one catalog read shared by every card
  // of the game). A failed read counts as nothing to draw from.
  // ponytail: one encounter read per uncovered card; a last-map field on the
  // list's own read if pages grow.
  const covered = Boolean(tournament.cover_image_url);
  const latest = useQuery({
    queryKey: tournamentQueryKeys.latestPlayed(tournament.id),
    queryFn: ({ signal }) => encounterService.getLatestPlayed(tournament, { signal }),
    enabled: !covered,
    staleTime: 5 * 60_000
  });
  const catalog = useCatalogEntities(covered ? null : tournament.discipline, "map");
  const picture = tournamentPicture(
    tournament,
    latest.isError ? null : latest.data,
    catalog.isError ? [] : catalog.data
  );

  return (
    <Link
      href={tournamentHref(tournament)}
      className="group flex h-full w-full flex-col overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] transition-colors hover:border-[color:var(--aqt-teal)] focus-visible:border-[color:var(--aqt-teal)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
    >
      <TournamentCover tournament={tournament} picture={picture} sizes="(max-width: 768px) 100vw, 33vw">
        {/* Status rides the cover's corner so the title keeps the card's full
            width: sharing a row with the name wrapped long titles onto three
            lines. A completed tournament gets no chip at all - the card is a
            dated record, and "COMPLETED" on three quarters of the grid is the
            least useful word on the page. The wrapper is the opaque backing the
            translucent chip tint needs over artwork we do not control. */}
        {isFinished ? null : (
          <span className="absolute right-2 top-2 z-[2] flex rounded-md bg-[color:var(--aqt-bg)]">
            <TournamentStatusPill status={variant}>
              {t(`common.statusBadge.${tournament.status}`)}
            </TournamentStatusPill>
          </span>
        )}
      </TournamentCover>

      <div className="flex flex-1 flex-col gap-2.5 p-4">
        <h3 className="flex min-w-0 items-start gap-2 text-ui font-semibold leading-snug text-[color:var(--aqt-fg)] transition-colors group-hover:text-[color:var(--aqt-teal)]">
          <span className="line-clamp-2">{tournament.name}</span>
          {tournament.is_hidden && (
            <span className="aqt-tnum mt-0.5 shrink-0 rounded border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-1.5 py-px text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
              {t("common.previewBadge")}
            </span>
          )}
        </h3>
        {/* Sentence case and one separator, matching the row in the list view:
            an all-caps date was the loudest line on the card. The description
            used to sit under it, on the half of the cards that have one, and
            only made the rows uneven. */}
        <p className="aqt-tnum flex flex-wrap items-center gap-x-1.5 text-caption text-[color:var(--aqt-fg-muted)]">
          <span>{formatDateRange(format, tournament.start_date, tournament.end_date)}</span>
          {games ? (
            <>
              <span aria-hidden className="text-[color:var(--aqt-fg-dim)]">·</span>
              <GameLabel code={tournament.discipline} games={games} />
            </>
          ) : null}
          {tournament.is_league && (
            <>
              <span aria-hidden className="text-[color:var(--aqt-fg-dim)]">·</span>
              <span>{t("common.league")}</span>
            </>
          )}
          {tournament.team_formation && (
            <>
              <span aria-hidden className="text-[color:var(--aqt-fg-dim)]">·</span>
              <span>{t(`common.${tournament.team_formation as TeamFormation}`)}</span>
            </>
          )}
        </p>

        <div className="mt-auto flex flex-col gap-2 border-t border-[color:var(--aqt-border)] pt-3">
          <div className="flex items-baseline justify-between gap-3 text-caption">
            {/* A finished tournament has no stage left to report: "Final" at
                100% was a bar that never moved on any completed card. The
                counts are what still tell those cards apart. */}
            {isFinished ? null : (
              <span className="font-semibold text-[color:var(--aqt-fg-muted)]">{stage.label}</span>
            )}
            {/* `ml-auto`: the counts hold the same corner whether or not a stage
                label shares the row, so a mixed grid scans in one column. */}
            <span className="aqt-tnum ml-auto flex items-center gap-1.5 text-[color:var(--aqt-fg-muted)]">
              <span>{t("tournamentsList.card.playersCount", { count: players })}</span>
              {teams != null ? (
                <>
                  <span aria-hidden className="text-[color:var(--aqt-fg-dim)]">·</span>
                  <span>{t("tournamentsList.card.teamsCount", { count: teams })}</span>
                </>
              ) : null}
            </span>
          </div>
          {isFinished ? null : (
            /* The label beside it carries the stage; the bar only pictures it. */
            <Progress aria-hidden size="sm" tone={stage.tone} value={stage.pct} />
          )}
        </div>
      </div>
    </Link>
  );
};

export default TournamentCard;
