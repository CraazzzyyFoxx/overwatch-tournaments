"use client";

import { Fragment, type ReactNode } from "react";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";

import { StatusPill } from "@/components/kit/StatusPill";
import type { Tone } from "@/components/kit/tone";
import { cn } from "@/lib/utils";

export interface EntityHubHeaderProps {
  title: ReactNode;
  status?: { label: string; tone: Tone };
  /** Metric/date fragments, joined with a middot. */
  meta?: ReactNode[];
  actions?: ReactNode;
  backHref?: string;
  /**
   * Heading rank, and with it the title's size. `1` (default) is the header of
   * the screen; `2` is an entity nested in one that already owns the `<h1>` —
   * a stage inside the tournament hub. Without this a nested header either
   * emits a second `<h1>` or gets hand-rolled beside the kit.
   */
  level?: 1 | 2;
}

/**
 * The header of every T3 hub: tournament, person, team, achievement.
 *
 * Replaces the old tournament workspace header plus the three hand-rolled
 * entity headings, so a hub reads the same whatever entity it is about. No
 * `Card`: per the design book a header is grouped by air and a hairline, not
 * a frame.
 */
export function EntityHubHeader({
  title,
  status,
  meta,
  actions,
  backHref,
  level = 1
}: Readonly<EntityHubHeaderProps>) {
  const metaParts = (meta ?? []).filter(
    (part) => part !== null && part !== undefined && part !== false
  );
  const Heading = level === 1 ? "h1" : "h2";

  return (
    <div className="flex flex-wrap items-start gap-3">
      {backHref ? (
        <Link
          href={backHref}
          aria-label="Back"
          className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ChevronLeft aria-hidden className="size-4" />
        </Link>
      ) : null}

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Heading
            className={cn(
              "min-w-0 truncate font-display font-semibold text-foreground",
              level === 1 ? "text-2xl" : "text-lg"
            )}
          >
            {title}
          </Heading>
          {status ? <StatusPill tone={status.tone}>{status.label}</StatusPill> : null}
        </div>

        {metaParts.length > 0 ? (
          <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-sm text-muted-foreground">
            {metaParts.map((part, index) => (
              <Fragment key={index}>
                {index > 0 ? <span aria-hidden>·</span> : null}
                <span>{part}</span>
              </Fragment>
            ))}
          </p>
        ) : null}
      </div>

      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}
