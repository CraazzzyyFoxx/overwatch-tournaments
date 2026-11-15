"use client";

import { Fragment, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";

import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import type { Tone } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { cn } from "@/lib/utils";

export interface EntityHubHeaderProps {
  title: ReactNode;
  status?: { label: string; tone: Tone };
  /** Metric/date fragments, joined with a middot. */
  meta?: ReactNode[];
  actions?: ReactNode;
  backHref?: string;
  /**
   * The entity's own mark (a person's avatar, a team's logo), between the back
   * link and the title. Placed beside the whole header instead, the back
   * chevron ends up between the mark and the name it belongs to.
   */
  leading?: ReactNode;
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
  leading,
  level = 1
}: Readonly<EntityHubHeaderProps>) {
  const t = useTranslations("kit.actions");
  const metaParts = (meta ?? []).filter(
    (part) => part !== null && part !== undefined && part !== false
  );
  const Heading = level === 1 ? "h1" : "h2";

  return (
    <div className="flex flex-wrap items-start gap-3">
      {backHref ? (
        <Button asChild variant="ghost" size="icon-sm" className="mt-1 shrink-0 text-muted-foreground">
          <Link href={backHref} aria-label={t("back")}>
            <ChevronLeft aria-hidden />
          </Link>
        </Button>
      ) : null}
      {leading ? <div className="shrink-0">{leading}</div> : null}

      {/* `min-w-48`: past that the actions wrap under the title instead of squeezing it to nothing. */}
      <div className="min-w-48 flex-1">
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
