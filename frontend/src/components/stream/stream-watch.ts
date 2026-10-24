import { createContext } from "react";

import type { StreamEntry } from "@/types/stream.types";

/**
 * The page's participant-stream player: which stream it plays and how to hand
 * it another. Provided by the tournament shell (`TournamentStreamDocks`), which
 * owns the dock the stream plays in. `null` outside it, where a live marker
 * stays an indication with nothing to open.
 */
export interface StreamWatch {
  /** `streamEntryKey` of the stream in the dock, or `null`. */
  watchingKey: string | null;
  /** Play `entry`. `trigger` gets focus back when the dock is closed. */
  watch: (entry: StreamEntry, trigger: HTMLElement) => void;
}

export const StreamWatchContext = createContext<StreamWatch | null>(null);
