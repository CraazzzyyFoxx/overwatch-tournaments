"use client";

import React from "react";
import { ScrollText, FileDown, FileX } from "lucide-react";
import { cn } from "@/lib/utils";

interface MatchLogIndicatorProps {
  hasLogs: boolean;
  /**
   * Download URL for the log file. When provided (and `hasLogs`), the indicator
   * becomes an actionable download link. Backend endpoint is pending
   * (see profile restore plan, Phase 7) — until it exists callers omit this and
   * the badge stays informational.
   */
  downloadUrl?: string | null;
  /** Alternative to `downloadUrl`: custom click handler that performs the download. */
  onDownload?: () => void;
  /** Log file name, used for the `download` attribute and aria/title labels. */
  logName?: string | null;
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

/**
 * Reusable indicator for match-log availability.
 * - no logs → dimmed, non-interactive;
 * - logs without download wiring → emerald icon, tooltip "Logs available";
 * - logs + download → actionable download button/link.
 */
const MatchLogIndicator = ({
  hasLogs,
  downloadUrl,
  onDownload,
  logName,
  size = 15,
  className
}: MatchLogIndicatorProps) => {
  if (!hasLogs) {
    return (
      <span
        className={cn(BASE, className)}
        style={mutedStyle}
        title="No logs"
        aria-label="No logs available"
      >
        <FileX size={size} strokeWidth={1.75} />
      </span>
    );
  }

  const canDownload = Boolean(downloadUrl || onDownload);

  if (!canDownload) {
    return (
      <span
        className={cn(BASE, className)}
        style={emeraldStyle}
        title="Logs available"
        aria-label="Logs available"
      >
        <ScrollText size={size} strokeWidth={1.75} />
      </span>
    );
  }

  const label = logName ? `Download log: ${logName}` : "Download log";

  if (downloadUrl) {
    return (
      <a
        href={downloadUrl}
        download={logName ?? undefined}
        onClick={(e) => e.stopPropagation()}
        className={cn(BASE, "hover:brightness-125", className)}
        style={emeraldStyle}
        title={label}
        aria-label={label}
      >
        <FileDown size={size} strokeWidth={1.9} />
      </a>
    );
  }

  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onDownload?.();
      }}
      className={cn(BASE, "hover:brightness-125", className)}
      style={emeraldStyle}
      title={label}
      aria-label={label}
    >
      <FileDown size={size} strokeWidth={1.9} />
    </button>
  );
};

export default MatchLogIndicator;
