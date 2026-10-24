"use client";

import { ExternalLink, MonitorPlay } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";

import { TwitchEmbed } from "@/components/stream/TwitchEmbed";
import { StreamWatchContext, type StreamWatch } from "@/components/stream/stream-watch";
import { Button } from "@/components/ui/button";
import { Dock } from "@/components/ui/dock";
import {
  embeddableTwitchChannel,
  streamEntryKey,
  streamPlatformLabel
} from "@/lib/social/stream-platform";
import type { StreamEntry, TournamentStreams } from "@/types/stream.types";

import { TournamentBroadcastDock } from "./TournamentBroadcastDock";

/**
 * The tournament's two corner players, and the one rule between them: a single
 * frame plays at a time.
 *
 * The official broadcast dock is always there (when the organizer has one). The
 * participant dock exists only while a viewer watches a team's POV, opened from
 * a live marker in the bracket (`StreamWatchContext`). It lives in the shell,
 * not in the bracket, so moving to another section keeps it playing.
 *
 * Opening a POV folds an open broadcast to its pill, and opening the broadcast
 * ends the POV: two muted frames stacked in one corner cover a third of a
 * desktop and all of a phone. The POV's close removes it rather than leaving a
 * pill behind; the bracket's marker is the way back.
 */
export function TournamentStreamDocks({
  streams,
  children
}: Readonly<{ streams: TournamentStreams | undefined; children: ReactNode }>) {
  const [pov, setPov] = useState<StreamEntry | null>(null);
  const [isBroadcastOpen, setIsBroadcastOpen] = useState(false);
  const triggerRef = useRef<HTMLElement | null>(null);

  // Stable identity: every slot row of the bracket reads this context.
  const watch = useCallback((entry: StreamEntry, trigger: HTMLElement) => {
    triggerRef.current = trigger;
    setPov(entry);
    setIsBroadcastOpen(false);
  }, []);
  const watchingKey = pov === null ? null : streamEntryKey(pov);
  const value = useMemo<StreamWatch>(() => ({ watchingKey, watch }), [watchingKey, watch]);

  return (
    <StreamWatchContext.Provider value={value}>
      {children}
      <TournamentBroadcastDock
        streams={streams}
        open={isBroadcastOpen}
        onOpenChange={(open) => {
          setIsBroadcastOpen(open);
          if (open) setPov(null);
        }}
      />
      {pov === null ? null : (
        <ParticipantStreamDock
          entry={pov}
          onClose={() => {
            setPov(null);
            // The close button leaves the DOM with the dock; without this a
            // keyboard user restarts from the top of the document. The marker
            // may be gone too (another section), and then <body> it is.
            if (triggerRef.current?.isConnected) triggerRef.current.focus();
          }}
        />
      )}
    </StreamWatchContext.Provider>
  );
}

/**
 * One participant's stream: whose it is, the player, a way out to the platform.
 * The entry is the snapshot taken at the click. A stream that ends under the
 * viewer keeps its frame, where the platform shows its own offline screen.
 */
function ParticipantStreamDock({
  entry,
  onClose
}: Readonly<{ entry: StreamEntry; onClose: () => void }>) {
  const t = useTranslations();
  const channel = embeddableTwitchChannel(entry);
  const player = entry.player?.name ?? entry.channel;
  const team = entry.player?.team?.name;
  const watchOn = t("stream.broadcast.watchOn", { platform: streamPlatformLabel(entry) });

  return (
    <Dock
      title={team ? `${player} · ${team}` : player}
      icon={<MonitorPlay className="size-4" aria-hidden />}
      hideLabel={t("stream.pov.close")}
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      actions={
        <Button asChild variant="ghost" size="icon" className="size-8 text-[color:var(--aqt-fg-muted)]">
          <a href={entry.url} target="_blank" rel="noopener noreferrer" aria-label={watchOn} title={watchOn}>
            <ExternalLink aria-hidden />
          </a>
        </Button>
      }
    >
      {channel ? (
        // Same box as the broadcast dock: the wrapper owns the ratio, because
        // `TwitchEmbed`'s 400x300 attributes beat `aspect-ratio` on the iframe.
        <div className="relative aspect-video w-full bg-black">
          <TwitchEmbed
            channel={channel}
            title={t("stream.broadcast.participantPlayerLabel", { channel })}
            className="absolute inset-0 size-full border-0"
          />
        </div>
      ) : null}
    </Dock>
  );
}
