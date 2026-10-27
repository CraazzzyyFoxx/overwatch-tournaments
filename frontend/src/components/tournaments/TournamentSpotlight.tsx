"use client";

import Link from "next/link";
import { ArrowRight, Pause, Play } from "lucide-react";
import { useTranslations } from "next-intl";

import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { FactsRow, GLASS_CLASS, StageBar, tournamentFacts } from "@/components/tournaments/TournamentFacts";
import { Button } from "@/components/ui/button";
import Image from "@/components/ui/image";
import { WorkspaceAvatar, type WorkspaceAvatarSource } from "@/components/workspace/WorkspaceAvatar";
import { useAutoplay } from "@/hooks/useAutoplay";
import { useMinuteClock } from "@/hooks/useMinuteClock";
import { useFormatter } from "@/lib/datetime/client";
import { stageProgress } from "@/lib/tournament/stage-progress";
import { getTournamentStatusMeta } from "@/lib/tournament/status";
import { tournamentHref } from "@/lib/tournament/url";
import { cn } from "@/lib/utils";
import type { Tournament } from "@/types/tournament.types";

/** How long each tournament holds the stage. */
export const SPOTLIGHT_INTERVAL_MS = 7000;

/** The thumbnail row's columns. */
const MAX_ITEMS = 5;

/** The crossfade of a change of tournament; none under reduced motion. */
const FADE_CLASS = "duration-200 motion-safe:animate-in motion-safe:fade-in";

export interface SpotlightItem {
  tournament: Tournament;
  /** `tournamentPicture`'s answer (`lib/tournament/art.ts`); `null` leaves the stage dark. */
  picture: string | null;
  /** Its community; absent, the stage names none. */
  workspace?: WorkspaceAvatarSource;
}

/**
 * Up to five tournaments, one at a time on a large stage: its picture blurred
 * and darkened behind everything, the sharp picture on the right fading into
 * it, and on the left its status, community, name, stage, facts and two ways
 * in. The thumbnails below pick one.
 *
 * It moves on by itself every `SPOTLIGHT_INTERVAL_MS`, the active thumbnail's
 * line filling meanwhile. It waits while the pointer is over the stage or
 * focus is inside it, and the line goes with the wait: a resumed stage starts
 * a fresh interval. The pause/play button stops and restarts it for good
 * (WCAG 2.2.2), and under reduced motion it starts stopped and never
 * crossfades. Nothing is read here; the caller hands in the items with their
 * pictures.
 */
export function TournamentSpotlight({ items }: Readonly<{ items: readonly SpotlightItem[] }>) {
  const t = useTranslations();
  const format = useFormatter();
  const now = useMinuteClock();
  const shown = items.slice(0, MAX_ITEMS);
  const count = shown.length;
  const { index: current, select, playing, autoplay, toggle, holdProps } = useAutoplay(count, SPOTLIGHT_INTERVAL_MS);

  if (count === 0) return null;
  const { tournament, picture, workspace } = shown[current];
  const variant = getTournamentStatusMeta(tournament.status).variant;

  return (
    // The pause/play button sits beside the stage, not in it: focusing or
    // pointing at it must not count as the pause it is there to lift.
    <div role="group" aria-label={t("tournamentsList.spotlight.label")} className="relative">
      <div
        className="relative isolate flex min-h-[480px] flex-col justify-end gap-6 overflow-hidden rounded-[22px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-5 sm:px-10 sm:pb-6 sm:pt-9"
        {...holdProps}
      >
        {/* Keyed by tournament, so a change remounts it and it fades in. */}
        <div key={`art-${tournament.id}`} aria-hidden className={cn("absolute inset-0 -z-10", FADE_CLASS)}>
          {picture ? (
            <>
              {/* The same file as the sharp picture (same `sizes`), so it costs
                  no second download. Oversized so the blur has no soft edge. */}
              <span className="absolute -inset-16">
                <Image
                  src={picture}
                  alt=""
                  fill
                  sizes="(min-width: 1024px) 66vw, 100vw"
                  className="object-cover blur-[46px] brightness-[.42] saturate-[1.35]"
                />
              </span>
              <span className="absolute inset-y-0 right-0 w-2/3 [mask-image:linear-gradient(90deg,transparent,var(--aqt-bg)_38%)]">
                <Image src={picture} alt="" fill sizes="(min-width: 1024px) 66vw, 100vw" className="object-cover" />
                <span className="absolute inset-0 bg-gradient-to-b from-transparent from-45% to-[color:color-mix(in_srgb,var(--aqt-bg)_85%,transparent)]" />
              </span>
            </>
          ) : null}
        </div>

        <div
          key={`body-${tournament.id}`}
          className={cn("flex flex-col items-start gap-3.5 sm:max-w-[70%] lg:max-w-[48%]", FADE_CLASS)}
        >
          {/* A finished tournament carries no status: its dates are already among the facts. */}
          {variant === "finished" ? null : (
            <span className={GLASS_CLASS}>
              <TournamentStatusPill status={variant}>{t(`common.statusBadge.${tournament.status}`)}</TournamentStatusPill>
            </span>
          )}
          {workspace ? (
            <span className="flex max-w-full items-center gap-2 text-caption text-[color:var(--aqt-fg-muted)]">
              <WorkspaceAvatar workspace={workspace} size={22} />
              <span className="truncate">{workspace.name}</span>
            </span>
          ) : null}
          <b className="max-w-full text-balance font-display text-title font-extrabold text-[color:var(--aqt-fg)] sm:text-headline">
            {tournament.name}
          </b>
          {variant === "live" ? <StageBar stage={stageProgress(tournament, tournament.status, t)} /> : null}
          <FactsRow facts={tournamentFacts(tournament, t, format, now)} />
          <span className="mt-1 flex flex-wrap gap-2.5">
            <Button asChild>
              <Link href={tournamentHref(tournament)} prefetch={false}>
                {t("tournamentsList.spotlight.open")}
                <ArrowRight aria-hidden />
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link href={tournamentHref(tournament, "/bracket")} prefetch={false}>
                {t("common.bracket")}
              </Link>
            </Button>
          </span>
        </div>

        <div role="group" aria-label={t("tournamentsList.spotlight.pick")} className="grid grid-cols-5 gap-2 sm:gap-3">
          {shown.map((item, position) => (
            <Button
              key={item.tournament.id}
              variant={null}
              size={null}
              aria-pressed={position === current}
              // The visible name is cut to the thumbnail's width (and hidden on a
              // phone); the full one is the button's name.
              aria-label={item.tournament.name}
              onClick={() => select(position)}
              className="relative aspect-video overflow-hidden rounded-xl bg-[color:var(--aqt-bg-2)] opacity-55 transition-[opacity,box-shadow] duration-200 hover:opacity-85 aria-pressed:opacity-100 aria-pressed:ring-2 aria-pressed:ring-[color:var(--aqt-teal)] aria-pressed:shadow-[0_10px_30px_-10px_color-mix(in_srgb,var(--aqt-teal)_60%,transparent)]"
            >
              {item.picture ? (
                <Image src={item.picture} alt="" fill sizes="(min-width: 1024px) 220px, 20vw" className="object-cover" />
              ) : null}
              <span
                aria-hidden
                className="absolute inset-x-0 bottom-0 hidden truncate bg-gradient-to-b from-transparent to-[color:color-mix(in_srgb,var(--aqt-bg)_92%,transparent)] px-2.5 pb-2 pt-4 text-left text-label font-semibold text-[color:var(--aqt-fg)] sm:block"
              >
                {item.tournament.name}
              </span>
              {/* The time left on this one; mounted only while the stage moves,
                  so a resume draws it from empty with its fresh interval. */}
              {position === current && playing ? (
                <span
                  aria-hidden
                  className="absolute left-0 top-0 h-0.5 w-full origin-left bg-[color:var(--aqt-teal)]"
                  style={{ animation: `aqt-grow-x ${SPOTLIGHT_INTERVAL_MS}ms linear both` }}
                />
              ) : null}
            </Button>
          ))}
        </div>
      </div>
      {count > 1 ? (
        <Button
          variant="outline"
          size="icon"
          aria-label={t(autoplay ? "tournamentsList.spotlight.pause" : "tournamentsList.spotlight.play")}
          onClick={toggle}
          className="absolute right-4 top-4 backdrop-blur-md sm:right-6 sm:top-6"
        >
          {autoplay ? <Pause aria-hidden /> : <Play aria-hidden />}
        </Button>
      ) : null}
    </div>
  );
}
