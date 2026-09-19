"use client";

import Link from "next/link";
import { ArrowRight, Star } from "lucide-react";
import { useFormatter } from "next-intl";

import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { DivisionGridVersion } from "@/types/workspace.types";

import { bandsFromTiers } from "./editor/draftReducer";
import { LadderBar } from "./LadderBar";
import { VERSION_STATE_TONE, versionState } from "./versionStatus";

export interface VersionHistoryProps {
  versions: DivisionGridVersion[];
  activeVersionId: number | null;
  /**
   * Tournaments pinned to each version, from the active version's readiness
   * payload. `null` while that is unknown (nothing active, or still loading):
   * a missing entry then means "unknown", not "none".
   */
  tournamentCounts: Record<number, number> | null;
  /**
   * Whether a published version may be activated right now, by id. `undefined`
   * while its readiness is loading; absent for versions that are not
   * candidates (drafts, archived, the active one).
   */
  activatable: Record<number, boolean | undefined>;
  onActivate?: (version: DivisionGridVersion) => void;
  editorHref: (versionId: number) => string;
}

/**
 * The version history of one grid, newest first (F11 ·3).
 *
 * A list rather than a grid of cards: a workspace usually has one to four
 * versions, and one card in a four-column grid reads as abandoned. Every row
 * carries the version's ladder cut, so the history shows *what changed*
 * between versions instead of asking the reader to compare captions.
 */
export function VersionHistory({
  versions,
  activeVersionId,
  tournamentCounts,
  activatable,
  onActivate,
  editorHref
}: Readonly<VersionHistoryProps>) {
  const format = useFormatter();
  const ordered = [...versions].sort((left, right) => right.version - left.version);

  return (
    <ol className="divide-y divide-border rounded-xl border border-border bg-card">
      {ordered.map((version) => {
        const state = versionState(version, activeVersionId);
        const bands = bandsFromTiers(version.tiers);
        const isDraft = version.status === "draft";
        const canActivate = version.id in activatable;
        const ready = activatable[version.id];

        const usage =
          state === "active"
            ? "in force"
            : tournamentCounts === null
              ? null
              : `${tournamentCounts[version.id] ?? 0} ${
                  tournamentCounts[version.id] === 1 ? "tournament" : "tournaments"
                }`;
        const when = isDraft
          ? "not published"
          : version.published_at
            ? format.dateTime(new Date(version.published_at), { dateStyle: "medium" })
            : null;

        return (
          <li
            key={version.id}
            className={cn(
              "grid grid-cols-[3.25rem_minmax(0,1fr)] items-start gap-x-4 gap-y-3 px-4 py-3 lg:grid-cols-[3.25rem_minmax(0,1fr)_auto]",
              state === "archived" && "opacity-60"
            )}
          >
            <span
              className={cn(
                "font-display text-lg font-semibold leading-6 tabular-nums",
                state === "active" ? "text-primary" : "text-foreground"
              )}
            >
              v{version.version}
            </span>

            <div className="flex min-w-0 flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 truncate text-sm font-medium" title={version.label}>
                  {version.label}
                </span>
                <StatusPill tone={VERSION_STATE_TONE[state]}>{state}</StatusPill>
              </div>
              <LadderBar bands={bands} tone={state === "active" ? "accent" : "neutral"} />
              <p className="font-mono text-label uppercase tracking-wider text-muted-foreground">
                {[`${bands.length} divisions`, usage, when].filter(Boolean).join(" · ")}
              </p>
            </div>

            <div className="col-start-2 flex flex-wrap items-center gap-2 lg:col-start-3 lg:justify-end">
              {canActivate && onActivate ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={ready !== true}
                  title={
                    ready === false
                      ? "Every older version a tournament still reads needs a complete mapping into this one first."
                      : undefined
                  }
                  onClick={() => onActivate(version)}
                >
                  <Star aria-hidden className="size-3.5" />
                  Activate v{version.version}
                </Button>
              ) : null}
              {isDraft ? (
                <Link
                  href={editorHref(version.id)}
                  className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Open editor
                  <ArrowRight aria-hidden className="size-3.5" />
                </Link>
              ) : (
                <Link
                  href={editorHref(version.id)}
                  className="inline-flex items-center rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  View
                </Link>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
