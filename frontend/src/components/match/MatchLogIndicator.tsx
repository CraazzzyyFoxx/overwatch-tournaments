"use client";

import React, { useState } from "react";
import { ScrollText, FileDown, FileX } from "lucide-react";
import { cn } from "@/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export interface MatchLogRef {
  matchId: number;
  label?: string;
}

interface MatchLogIndicatorProps {
  /** Whether the encounter has any logs (authoritative availability flag). */
  hasLogs: boolean;
  /** Per-match downloadable logs within this encounter. When omitted, the
   *  indicator is informational only. */
  logs?: MatchLogRef[];
  size?: number;
  className?: string;
}

/** Direct, browser-navigable download URL for a match's parsed log. */
export const matchLogDownloadUrl = (matchId: number) => `/api/v1/matches/${matchId}/log`;

const BASE = "inline-flex h-7 w-7 items-center justify-center rounded-[7px] border transition-colors";
const HAS = "border-emerald-500/30 bg-emerald-500/10 text-emerald-500";
const NONE = "border-border text-muted-foreground/40";

const stop = (e: React.MouseEvent) => e.stopPropagation();

/**
 * Global indicator for match-log availability with download. Theme-agnostic
 * (uses shared tokens, no page-scoped vars) so it renders correctly anywhere
 * encounters are shown.
 * - no logs → dimmed, non-interactive;
 * - logs without per-match refs → emerald icon, "Logs available";
 * - one downloadable log → direct download link;
 * - several → click opens a popover listing each map's log.
 */
const MatchLogIndicator = ({ hasLogs, logs, size = 15, className }: MatchLogIndicatorProps) => {
  const [open, setOpen] = useState(false);
  const downloadable = logs ?? [];

  if (!hasLogs) {
    return (
      <span className={cn(BASE, NONE, className)} title="No logs" aria-label="No logs available">
        <FileX size={size} strokeWidth={1.75} />
      </span>
    );
  }

  if (downloadable.length === 0) {
    return (
      <span className={cn(BASE, HAS, className)} title="Logs available" aria-label="Logs available">
        <ScrollText size={size} strokeWidth={1.75} />
      </span>
    );
  }

  if (downloadable.length === 1) {
    const log = downloadable[0];
    return (
      <a
        href={matchLogDownloadUrl(log.matchId)}
        download
        onClick={stop}
        className={cn(BASE, HAS, "hover:brightness-125", className)}
        title={log.label ? `Download log: ${log.label}` : "Download log"}
        aria-label="Download log"
      >
        <FileDown size={size} strokeWidth={1.9} />
      </a>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          onClick={(e) => {
            stop(e);
            setOpen((v) => !v);
          }}
          className={cn(BASE, HAS, "hover:brightness-125", className)}
          title={`Download logs (${downloadable.length})`}
          aria-label={`Download logs (${downloadable.length})`}
        >
          <FileDown size={size} strokeWidth={1.9} />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-56 p-1.5" onClick={stop}>
        <div className="px-2 pb-1.5 pt-1 text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
          Match logs
        </div>
        <div className="flex flex-col">
          {downloadable.map((log, i) => (
            <a
              key={log.matchId}
              href={matchLogDownloadUrl(log.matchId)}
              download
              onClick={stop}
              className="flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] transition-colors hover:bg-muted"
            >
              <FileDown size={13} strokeWidth={1.9} className="text-emerald-500" />
              <span className="truncate">{log.label ?? `Map ${i + 1}`}</span>
            </a>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
};

export default MatchLogIndicator;
