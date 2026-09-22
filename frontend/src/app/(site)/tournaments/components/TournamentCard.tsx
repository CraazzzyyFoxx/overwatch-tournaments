"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { getTournamentStatusMeta } from "@/lib/tournament/status";
import { tournamentHref } from "@/lib/tournament/url";
import { cn, formatDateRange } from "@/lib/utils";
import type { Tournament } from "@/types/tournament.types";

import { stageProgress } from "./tournaments-helpers";

/**
 * Stand-in for a tournament without a cover.
 *
 * Deliberately not a grey rectangle: an organizer who never uploaded an image
 * is the common case, so the placeholder has to be a first-class surface. It
 * borrows the hero frame's treatment — teal hairline, radially masked grid, one
 * restrained glow — so a coverless card reads as part of the same page rather
 * than as a broken image.
 */
const COVER_FALLBACK = (
  <span aria-hidden data-cover-fallback className="absolute inset-0 overflow-hidden">
    <span className="absolute inset-x-0 top-0 z-[2] h-0.5 bg-[color:var(--aqt-teal)]" />
    <span
      className="absolute inset-0 opacity-45"
      style={{
        backgroundImage:
          "linear-gradient(var(--aqt-border) 1px, transparent 1px), linear-gradient(90deg, var(--aqt-border) 1px, transparent 1px)",
        backgroundSize: "32px 32px",
        WebkitMaskImage: "radial-gradient(120% 120% at 20% 0%, #000 35%, transparent 80%)",
        maskImage: "radial-gradient(120% 120% at 20% 0%, #000 35%, transparent 80%)"
      }}
    />
    <span
      className="absolute -left-[8%] -top-[30%] h-[150%] w-3/5"
      style={{ background: "var(--aqt-hero-glow)" }}
    />
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
  const locale = useLocale();
  const { variant } = getTournamentStatusMeta(tournament.status);
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
          COVER_FALLBACK
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
      </div>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex flex-col gap-1.5">
          {/* The status belongs with the facts, not floating on the cover: it is
              the first thing a reader wants to know, so it shares the name's
              baseline instead of a corner of the artwork. */}
          <div className="flex items-start justify-between gap-3">
            <h3 className="flex min-w-0 items-start gap-2 text-ui font-semibold leading-snug text-[color:var(--aqt-fg)] transition-colors group-hover:text-[color:var(--aqt-teal)]">
              <span className="line-clamp-2">{tournament.name}</span>
              {tournament.is_hidden && (
                <span className="aqt-tnum mt-0.5 shrink-0 rounded border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-1.5 py-px text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-dim)]">
                  {t("common.previewBadge")}
                </span>
              )}
            </h3>
            <span className={cn("tn-status mt-px shrink-0", variant)}>
              <span aria-hidden className="dot" />
              {t(`common.statusBadge.${tournament.status}`)}
            </span>
          </div>
          <p className="aqt-tnum flex flex-wrap items-center gap-x-2 text-label uppercase tracking-[0.06em] text-[color:var(--aqt-fg-dim)]">
            <span>{formatDateRange(tournament.start_date, tournament.end_date, locale)}</span>
            {tournament.is_league && (
              <>
                <span aria-hidden className="text-[color:var(--aqt-fg-faint)]">/</span>
                <span>{t("common.league")}</span>
              </>
            )}
            {tournament.team_formation && (
              <>
                <span aria-hidden className="text-[color:var(--aqt-fg-faint)]">/</span>
                <span className="text-[color:var(--aqt-fg-muted)]">
                  {tournament.team_formation === "draft" ? t("common.draft") : t("common.balancer")}
                </span>
              </>
            )}
          </p>
        </div>

        {tournament.description ? (
          <p className="line-clamp-2 text-caption leading-relaxed text-[color:var(--aqt-fg-muted)]">
            {tournament.description}
          </p>
        ) : null}

        <div className="mt-auto flex flex-col gap-2 border-t border-[color:var(--aqt-border)] pt-3">
          <div className="flex items-baseline justify-between gap-3 text-label">
            <span className="aqt-tnum font-semibold uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
              {stage.label}
            </span>
            <span className="aqt-tnum flex items-center gap-1.5 text-[color:var(--aqt-fg-dim)]">
              <span>{t("tournamentsList.card.playersCount", { count: players })}</span>
              {teams != null ? (
                <>
                  <span aria-hidden className="text-[color:var(--aqt-fg-faint)]">·</span>
                  <span>{t("tournamentsList.card.teamsCount", { count: teams })}</span>
                </>
              ) : null}
            </span>
          </div>
          {/* `tn-stage` only for the fill palette; its 80px track is a table-column
              measure, so the width is forced inline (a `.aqt-tn`-scoped selector
              outranks any utility class). */}
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
        </div>
      </div>
    </Link>
  );
};

export default TournamentCard;
