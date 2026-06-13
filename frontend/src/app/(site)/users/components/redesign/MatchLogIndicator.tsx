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
  /** Per-match downloadable logs within this encounter. */
  logs?: MatchLogRef[];
  /** Builds a download URL for a match log. Without it, the indicator stays informational. */
  hrefFor?: (matchId: number) => string;
  size?: number;
  className?: string;
}

const emeraldStyle: React.CSSProperties = {
  borderColor: "hsl(152 60% 50% / 0.3)",
  color: "var(--aqt-emerald)",
  background: "hsl(152 60% 50% / 0.08)"
};

const mutedStyle: React.CSSProperties = {
  borderColor: "var(--aqt-border)",
  color: "var(--aqt-fg-faint)",
  background: "transparent"
};

const BASE =
  "inline-flex h-7 w-7 items-center justify-center rounded-[7px] border transition-colors";

const stop = (e: React.MouseEvent) => e.stopPropagation();

/**
 * Reusable match-log indicator with download.
 * - no logs → dimmed, non-interactive;
 * - logs without a `hrefFor` → emerald icon, "Logs available";
 * - one downloadable log → direct download link;
 * - several → click opens a popover listing each map's log.
 */
const MatchLogIndicator = ({ hasLogs, logs, hrefFor, size = 15, className }: MatchLogIndicatorProps) => {
  const [open, setOpen] = useState(false);
  const downloadable = hrefFor && logs ? logs : [];

  if (!hasLogs) {
    return (
      <span className={cn(BASE, className)} style={mutedStyle} title="No logs" aria-label="No logs available">
        <FileX size={size} strokeWidth={1.75} />
      </span>
    );
  }

  if (downloadable.length === 0) {
    return (
      <span className={cn(BASE, className)} style={emeraldStyle} title="Logs available" aria-label="Logs available">
        <ScrollText size={size} strokeWidth={1.75} />
      </span>
    );
  }

  if (downloadable.length === 1) {
    const log = downloadable[0];
    return (
      <a
        href={hrefFor!(log.matchId)}
        download
        onClick={stop}
        className={cn(BASE, "hover:brightness-125", className)}
        style={emeraldStyle}
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
          className={cn(BASE, "hover:brightness-125", className)}
          style={emeraldStyle}
          title={`Download logs (${downloadable.length})`}
          aria-label={`Download logs (${downloadable.length})`}
        >
          <FileDown size={size} strokeWidth={1.9} />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-56 p-1.5" onClick={stop}>
        <div className="px-2 pb-1.5 pt-1 text-[10px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">
          Match logs
        </div>
        <div className="flex flex-col">
          {downloadable.map((log, i) => (
            <a
              key={log.matchId}
              href={hrefFor!(log.matchId)}
              download
              onClick={stop}
              className="flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-[color:var(--aqt-fg)] transition-colors hover:bg-[hsl(0_0%_100%/0.05)]"
            >
              <FileDown size={13} strokeWidth={1.9} className="text-[color:var(--aqt-emerald)]" />
              <span className="truncate">{log.label ?? `Map ${i + 1}`}</span>
            </a>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
};

export default MatchLogIndicator;
