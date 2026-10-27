"use client";

import React, { useState } from "react";
import { ScrollText, FileDown, FileX } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import type { RawSourceStatus } from "@/types/encounter.types";

interface MatchLogRef {
  matchId: number;
  rawAvailable: boolean;
  label?: string;
}

interface MatchLogIndicatorProps {
  /** Whether parsed observations exist, independently of raw availability. */
  hasLogs: boolean;
  /** Per-observation raw capability from the server. Omit for an informational indicator. */
  logs?: MatchLogRef[];
  size?: number;
  className?: string;
}

/** Direct, browser-navigable download URL for a match's parsed log. */
const matchLogDownloadUrl = (matchId: number) => `/api/v1/matches/${matchId}/log`;

const BASE =
  "inline-flex h-7 w-7 items-center justify-center rounded-[7px] border transition-colors " +
  "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";
const HAS =
  "border-[color:color-mix(in_srgb,var(--aqt-emerald)_30%,transparent)] " +
  "bg-[color:color-mix(in_srgb,var(--aqt-emerald)_10%,transparent)] text-[color:var(--aqt-emerald)]";
const NONE = "border-border text-[color:var(--aqt-fg-faint)]";

const stop = (e: React.MouseEvent) => e.stopPropagation();

export function RawLogStatus({
  raw_status,
  raw_available
}: Readonly<{ raw_status: RawSourceStatus | null; raw_available: boolean }>) {
  const t = useTranslations("common.rawLog");
  const status = raw_available ? "available" : raw_status === "available" ? "unverified" : raw_status ?? "none";
  return <span>{t(status)}</span>;
}

/**
 * Global indicator for match-log availability with download. Theme-agnostic
 * (uses shared tokens, no page-scoped vars) so it renders correctly anywhere
 * encounters are shown.
 * - no logs → dimmed, non-interactive;
 * - logs without verified raw refs, or a viewer who is not signed in →
 *   non-interactive parsed-statistics indicator;
 * - one downloadable log → direct download link;
 * - several → click opens a popover listing each map's log.
 *
 * The download is a browser-navigated `<a download>` against an authenticated
 * endpoint, so an anonymous visitor would get a 401 file instead of a log. The
 * availability signal stays — only the link is withheld.
 */
const MatchLogIndicator = ({ hasLogs, logs, size = 15, className }: MatchLogIndicatorProps) => {
  const t = useTranslations();
  const { status } = useAuthProfile();
  const [open, setOpen] = useState(false);
  // Only a confirmed session gets links: "idle"/"loading"/"error" mean the
  // viewer is not known yet, and offering a link that 401s is worse than
  // offering none — the store flips to "authenticated" and the link appears.
  const downloadable = status === "authenticated"
    ? (logs ?? []).filter((log) => log.rawAvailable)
    : [];

  if (!hasLogs) {
    const label = t("common.matchLogs.noneAvailable");
    return (
      <span role="img" className={cn(BASE, NONE, className)} title={t("common.matchLogs.none")} aria-label={label}>
        <FileX size={size} strokeWidth={1.75} aria-hidden />
      </span>
    );
  }

  if (downloadable.length === 0) {
    const label = t(logs != null && !logs.some((log) => log.rawAvailable)
      ? "common.matchLogs.rawUnavailable"
      : "common.matchLogs.available");
    return (
      <span role="img" className={cn(BASE, HAS, className)} title={label} aria-label={label}>
        <ScrollText size={size} strokeWidth={1.75} aria-hidden />
      </span>
    );
  }

  if (downloadable.length === 1) {
    const log = downloadable[0];
    const label = t("common.matchLogs.download", {
      label: log.label ?? t("common.matchLogs.map", { index: 1 })
    });
    return (
      <a
        href={matchLogDownloadUrl(log.matchId)}
        download
        onClick={stop}
        className={cn(BASE, HAS, "hover:brightness-125", className)}
        title={label}
        aria-label={label}
      >
        <FileDown size={size} strokeWidth={1.9} aria-hidden />
      </a>
    );
  }

  const allLabel = t("common.matchLogs.downloadAll", { count: downloadable.length });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={(e) => {
            stop(e);
            setOpen((v) => !v);
          }}
          className={cn("rounded-[7px] border", HAS, "hover:brightness-125", className)}
          title={allLabel}
          aria-label={allLabel}
        >
          <FileDown size={size} strokeWidth={1.9} aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-56 p-1.5" onClick={stop}>
        <Eyebrow as="div" tone="muted" className="px-2 pb-1.5 pt-1">
          {t("common.matchLogs.title")}
        </Eyebrow>
        <div className="flex flex-col">
          {downloadable.map((log, i) => (
            <a
              key={log.matchId}
              href={matchLogDownloadUrl(log.matchId)}
              download
              onClick={stop}
              className="flex items-center gap-2 rounded-md px-2 py-1.5 text-caption transition-colors hover:bg-muted focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
            >
              <FileDown size={13} strokeWidth={1.9} className="text-[color:var(--aqt-emerald)]" aria-hidden />
              <span className="truncate">
                {log.label ?? t("common.matchLogs.map", { index: i + 1 })}
              </span>
            </a>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
};

export default MatchLogIndicator;
