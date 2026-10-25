"use client";

import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";

import { PlayerAvatar } from "@/components/PlayerAvatar";
import { SocialIcon } from "@/components/social/SocialIcon";
import { TwitchEmbed } from "@/components/stream/TwitchEmbed";
import { TournamentTeamCardFrame } from "@/components/TournamentTeamCard";
import { Button } from "@/components/ui/button";
import { RowButton } from "@/components/ui/row-button";
import { useFormatter } from "@/lib/datetime/client";
import { getSocialProviderConfig } from "@/lib/social/providers";
import { formatStreamUptime, formatVodClock, twitchVodUrl } from "@/lib/social/stream-platform";
import type { StreamChapter, StreamVod } from "@/types/stream.types";

/**
 * A chapter the viewer asked to watch. `take` counts the picks, so picking the
 * same chapter again remounts the player and seeks back to its start.
 */
export type VodPick = { vod: StreamVod; chapter: StreamChapter; take: number };

const STARTED_AT = { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" } as const;
const TWITCH = getSocialProviderConfig("twitch").label;

/** Where in its series a chapter sits: "Map 2 · King's Row", or the series start. */
export function useChapterPlace(): (chapter: StreamChapter) => string {
  const t = useTranslations("stream.vods");
  return (chapter) => {
    if (chapter.kind === "series") return t("matchStart");
    const parts = [
      chapter.map_position != null ? t("map", { position: chapter.map_position }) : null,
      chapter.map_name
    ].filter(Boolean);
    return parts.length > 0 ? parts.join(" · ") : t("mapUnnamed");
  };
}

/** Avatar, name and — once rosters exist — the team, on one truncating line. */
export function StreamerName({ player }: Readonly<{ player: StreamVod["player"] }>) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <PlayerAvatar user={player} size={24} />
      <span className="truncate">{player.name}</span>
      {player.team ? (
        <span className="truncate text-caption font-normal text-[color:var(--aqt-fg-muted)]">
          {player.team.name}
        </span>
      ) : null}
    </span>
  );
}

/** The theater's frame while a past broadcast plays, and what is on it. */
export function VodTheater({ pick }: Readonly<{ pick: VodPick }>) {
  const t = useTranslations();
  const place = useChapterPlace();
  const { vod, chapter } = pick;

  return (
    <div className="flex min-w-0 flex-col">
      {/* Pure black for the same reason as `StreamTheater`: it is video. */}
      <div className="relative aspect-video w-full min-h-[300px] overflow-hidden bg-black">
        <TwitchEmbed
          key={pick.take}
          video={vod.vod_id}
          start={chapter.offset_s}
          title={t("stream.vods.playerLabel", { name: vod.player.name })}
          className="absolute inset-0 size-full border-0"
        />
      </div>

      <div className="flex min-w-0 flex-col gap-2.5 p-4">
        <h3 className="m-0 min-w-0 text-ui font-semibold">
          <StreamerName player={vod.player} />
        </h3>
        <p className="m-0 text-caption text-[color:var(--aqt-fg-muted)]">
          <span className="aqt-tnum">{formatVodClock(chapter.offset_s)}</span>
          {` · ${chapter.encounter_name} · ${place(chapter)}`}
        </p>
        <Button asChild variant="outline" size="sm" className="w-fit">
          <a href={twitchVodUrl(vod.vod_id, chapter.offset_s)} target="_blank" rel="noopener noreferrer">
            <SocialIcon provider="twitch" size={14} decorative />
            {t("stream.broadcast.watchOn", { platform: TWITCH })}
            <ExternalLink aria-hidden />
          </a>
        </Button>
      </div>
    </div>
  );
}

type PastBroadcastsProps = {
  vods: StreamVod[];
  /** The chapter in the theater, if a past broadcast is playing. */
  pick: VodPick | null;
  onPick: (vod: StreamVod, chapter: StreamChapter) => void;
};

/**
 * Participants' past broadcasts, one group card each, its rows the moments the
 * streamer's team played. A row plays that moment in the page's one player; the
 * icon beside it opens the same moment on Twitch.
 */
export function PastBroadcasts({ vods, pick, onPick }: Readonly<PastBroadcastsProps>) {
  const t = useTranslations();
  const format = useFormatter();
  const place = useChapterPlace();
  const units = { h: t("common.duration.h"), m: t("common.duration.m") };

  return (
    <section aria-labelledby="past-broadcasts-heading">
      <h2 id="past-broadcasts-heading" className="m-0 text-ui font-semibold text-[color:var(--aqt-fg)]">
        {t("stream.vods.heading")}
      </h2>
      <div className="mt-3 grid gap-3 lg:grid-cols-2 lg:items-start">
        {vods.map((vod) => {
          const duration = formatStreamUptime(vod.started_at, units, Date.parse(vod.ended_at));
          return (
            <TournamentTeamCardFrame
              key={vod.vod_id}
              name={<StreamerName player={vod.player} />}
              metricValue={
                <span className="text-caption font-normal text-[color:var(--aqt-fg-muted)]">
                  {format.dateTime(new Date(vod.started_at), STARTED_AT)}
                  {duration ? ` · ${duration}` : null}
                </span>
              }
            >
              <ol className="m-0 list-none divide-y divide-[color:var(--aqt-overlay-border)] p-0">
                {vod.chapters.map((chapter, index) => {
                  const clock = formatVodClock(chapter.offset_s);
                  const where = place(chapter);
                  const label = `${chapter.encounter_name} · ${where}`;
                  const isPlaying =
                    pick?.vod.vod_id === vod.vod_id &&
                    pick.chapter.offset_s === chapter.offset_s &&
                    pick.chapter.encounter_id === chapter.encounter_id &&
                    pick.chapter.map_position === chapter.map_position;
                  return (
                    // A chapter list is static between reads and two chapters
                    // can share every field, so the position is the identity.
                    <li key={index} className="flex min-w-0 items-center">
                      <RowButton
                        onClick={() => onPick(vod, chapter)}
                        aria-current={isPlaying ? "true" : undefined}
                        aria-label={t("stream.vods.play", { chapter: label, time: clock })}
                        title={label}
                        className="flex min-w-0 flex-1 items-baseline gap-3 py-2.5 ps-3.5 pe-2"
                      >
                        <span className="aqt-tnum min-w-14 shrink-0 text-caption font-semibold text-[color:var(--aqt-teal)]">
                          {clock}
                        </span>
                        <span className="min-w-0 truncate text-caption text-[color:var(--aqt-fg)]">
                          {chapter.encounter_name}
                          <span className="text-[color:var(--aqt-fg-dim)]">{` · ${where}`}</span>
                        </span>
                      </RowButton>
                      <Button asChild variant="ghost" size="icon-sm" className="me-2 shrink-0">
                        <a
                          href={twitchVodUrl(vod.vod_id, chapter.offset_s)}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={t("stream.vods.open", { chapter: label, time: clock })}
                          title={t("stream.vods.open", { chapter: label, time: clock })}
                        >
                          <ExternalLink aria-hidden />
                        </a>
                      </Button>
                    </li>
                  );
                })}
              </ol>
              <div className="border-t border-[color:var(--aqt-overlay-border)] px-2 py-1.5">
                <Button asChild variant="ghost" size="xs">
                  <a
                    href={vod.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={t("stream.vods.watchVod", { name: vod.player.name })}
                  >
                    <SocialIcon provider="twitch" size={12} decorative />
                    {t("stream.broadcast.watchOn", { platform: TWITCH })}
                    <ExternalLink aria-hidden />
                  </a>
                </Button>
              </div>
            </TournamentTeamCardFrame>
          );
        })}
      </div>
    </section>
  );
}
