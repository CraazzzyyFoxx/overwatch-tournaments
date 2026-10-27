"use client";

import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";

import { SectionHead } from "@/components/match/EncounterAtoms";
import { StreamerName, useChapterPlace } from "@/components/stream/PastBroadcasts";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { formatVodClock, twitchVodUrl } from "@/lib/social/stream-platform";
import streamService from "@/services/stream.service";

/**
 * Participants' POV broadcasts of this match, each moment a link into the
 * Twitch VOD (new tab).
 *
 * Read on the client and absent until there is something to watch: no
 * skeleton, no empty state, no error note. Most matches have no broadcast, and
 * nothing on the page may move for a read that usually comes back empty. No
 * realtime resource carries it; the staleTime is the freshness.
 */
export default function EncounterWatch({ encounterId }: Readonly<{ encounterId: number }>) {
  const t = useTranslations();
  const place = useChapterPlace();
  const vodsQuery = useQuery({
    queryKey: encounterQueryKeys.vods(encounterId),
    queryFn: () => streamService.getEncounterVods(encounterId),
    staleTime: 60_000,
    meta: { suppressErrorToast: true }
  });
  const vods = vodsQuery.data?.vods ?? [];

  if (vods.length === 0) return null;

  return (
    <section aria-labelledby="encounter-watch-heading">
      <SectionHead titleId="encounter-watch-heading" title={t("stream.vods.watchMatch")} />
      <Card asChild className="m-0 list-none divide-y divide-[color:var(--aqt-border)] overflow-hidden p-0">
        <ul>
          {vods.map((vod) => (
            <li key={vod.vod_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
              <span className="min-w-0 text-ui font-semibold">
                <StreamerName player={vod.player} />
              </span>
              <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
                {vod.chapters.map((chapter, index) => {
                  const clock = formatVodClock(chapter.offset_s);
                  const where = place(chapter);
                  return (
                    // Static between reads, and two chapters can share every field.
                    <li key={index}>
                      <Button asChild variant="outline" size="sm">
                        <a
                          href={twitchVodUrl(vod.vod_id, chapter.offset_s)}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={t("stream.vods.open", {
                            chapter: `${vod.player.name} · ${where}`,
                            time: clock
                          })}
                        >
                          <span className="aqt-tnum">{clock}</span>
                          <span className="text-[color:var(--aqt-fg-muted)]">{where}</span>
                          <ExternalLink aria-hidden />
                        </a>
                      </Button>
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}
