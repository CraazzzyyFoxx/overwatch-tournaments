"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { getTournamentStatusMeta } from "@/lib/tournament/status";
import { tournamentHref } from "@/lib/tournament/url";
import { formatDateRange } from "@/lib/datetime";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { TeamFormation, Tournament } from "@/types/tournament.types";

import { stageProgress } from "./tournaments-helpers";

/**
 * Stand-in for a tournament without a cover.
 *
 * An organizer who never uploaded an image is the common case, so this is not
 * a placeholder but a second kind of cover: the tournament's own name, set
 * large on a teal-tinted wash. The earlier abstract grid-and-glow panel said
 * nothing — a third of the grid was interchangeable dark rectangles.
 *
 * `aria-hidden` because the name is already the card's `<h3>`; this is the same
 * fact drawn, not a second announcement. The logo, when there is one, still
 * renders over it.
 */
const CoverFallback = ({ name }: { name: string }) => (
  <span
    aria-hidden
    data-cover-fallback
    /* `z-[2]`: the scrim below exists for uploaded artwork; over this surface
       it would only grey out the name it is drawn from. */
    className="absolute inset-0 z-[2] flex items-center justify-center overflow-hidden px-4 text-center"
    style={{
      background:
        "linear-gradient(135deg, color-mix(in srgb, var(--aqt-teal) 18%, var(--aqt-bg-2)), var(--aqt-bg) 78%)"
    }}
  >
    <span className="absolute inset-x-0 top-0 z-[2] h-0.5 bg-[color:var(--aqt-teal)]" />
    <span className="line-clamp-3 font-onest text-[clamp(1.05rem,2.4vw,1.5rem)] font-bold leading-tight text-[color:color-mix(in_srgb,var(--aqt-fg)_72%,transparent)]">
      {name}
    </span>
  </span>
);

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
 *
 * Plain `<img>` (not `next/image`) for the same reason team logos use one — the
 * URL points at whatever S3/MinIO host the deployment configured, and
 * `next/image` hard-errors on a hostname missing from `remotePatterns`.
 */
const TournamentCard = ({ tournament }: { tournament: Tournament }) => {
  const t = useTranslations();
  const format = useFormatter();
  const { variant } = getTournamentStatusMeta(tournament.status);
  const isFinished = variant === "finished";
  const stage = stageProgress(tournament, tournament.status, t);
  const players = tournament.participants_count ?? 0;
  const teams = tournament.teams_count;

  return (
    <Link
      href={tournamentHref(tournament)}
      className="group flex h-full w-full flex-col overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] outline-none transition-colors hover:border-[color:var(--aqt-teal)] focus-visible:border-[color:var(--aqt-teal)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
    >
      <div className="relative aspect-video w-full overflow-hidden bg-[color:var(--aqt-bg-2)]">
        {tournament.cover_image_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- see the note above
          <img
            src={tournament.cover_image_url}
            alt=""
            aria-hidden
            data-cover
            loading="lazy"
            decoding="async"
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <CoverFallback name={tournament.name} />
        )}

        {/* Scrim: the logo sits on artwork we do not control, so the contrast
            under it cannot be left to the image. */}
        <span
          aria-hidden
          className="absolute inset-x-0 bottom-0 z-[1] h-2/3 bg-gradient-to-t from-[color:var(--aqt-bg)] via-[color:color-mix(in_srgb,var(--aqt-bg)_55%,transparent)] to-transparent"
        />

        {tournament.logo_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- see the note above
          <img
            src={tournament.logo_url}
            alt=""
            aria-hidden
            data-logo
            width={40}
            height={40}
            loading="lazy"
            decoding="async"
            className="absolute bottom-2 left-2 z-[2] size-10 rounded-md border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] object-cover"
          />
        ) : null}

        {/* Status rides the cover's corner so the title keeps the card's full
            width: sharing a row with the name wrapped long titles onto three
            lines. A completed tournament gets no chip at all - the card is a
            dated record, and "COMPLETED" on three quarters of the grid is the
            least useful word on the page. The wrapper is the opaque backing the
            translucent chip tint needs over artwork we do not control. */}
        {isFinished ? null : (
          <span className="absolute right-2 top-2 z-[2] flex rounded-md bg-[color:var(--aqt-bg)]">
            <span className={cn("tn-status", variant)}>
              <span aria-hidden className="dot" />
              {t(`common.statusBadge.${tournament.status}`)}
            </span>
          </span>
        )}
      </div>

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
            /* `tn-stage` only for the fill palette; its 80px track is a
               table-column measure, so the width is forced inline (a
               `.aqt-tn`-scoped selector outranks any utility class). */
            <div className="tn-stage w-full">
              <div className="progress" style={{ width: "100%", height: 4 }}>
                <div
                  className={cn(
                    "fill",
                    stage.fill === "amber" && "amber",
                    stage.fill === "muted" && "muted"
                  )}
                  style={{ width: `${stage.pct}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </Link>
  );
};

export default TournamentCard;
