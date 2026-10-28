"use client";

import { useNow, useTranslations } from "next-intl";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { formatDate, formatRelative } from "@/components/kit/format-time";
import { StatusPill } from "@/components/kit/StatusPill";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { TONE_TEXT } from "@/components/ui/tone";
import { GameIcon } from "@/components/workspace/GameIcon";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { DashboardTimelineEvent, DashboardTournamentCard } from "@/types/admin-dashboard.types";
import type { TournamentStatus } from "@/types/tournament.types";
import { Block, BlockError } from "./Block";
import { dayLabel, groupByDay } from "./model";

/**
 * Phase-schedule boundaries of the next seven days, listed by day. Overdue
 * starts (a phase the tournament should have entered and has not) lead in their
 * own group in the error tone: they are the entries that are already late.
 */
export function Timeline({
  events,
  cardOf,
  failed,
  onRetry,
  className
}: Readonly<{
  /** `undefined` while loading. */
  events: DashboardTimelineEvent[] | undefined;
  cardOf: ReadonlyMap<number, DashboardTournamentCard>;
  failed: boolean;
  onRetry: () => void;
  className?: string;
}>) {
  const t = useTranslations("adminShell.dashboard");
  const format = useFormatter();
  const now = useNow();
  const title = t("timeline");

  if (failed) {
    return (
      <Block title={title} className={className}>
        <BlockError title={title} onRetry={onRetry} />
      </Block>
    );
  }
  if (!events) {
    return (
      <Block title={title} className={className}>
        <div className="space-y-2">
          {Array.from({ length: 3 }, (_, index) => (
            <Skeleton key={index} className="h-9 rounded-md" />
          ))}
        </div>
      </Block>
    );
  }

  const words = { today: t("dayToday"), tomorrow: t("dayTomorrow"), yesterday: t("dayYesterday") };
  const overdue = events.filter((event) => event.overdue);
  const groups = [
    ...(overdue.length > 0 ? [{ key: "overdue", label: t("timelineOverdue"), late: true, events: overdue }] : []),
    ...groupByDay(
      events.filter((event) => !event.overdue),
      (event) => event.at,
      format
    ).map((day) => ({ key: day.key, label: dayLabel(format, day.date, now, words), late: false, events: day.items }))
  ];

  return (
    <Block title={title} className={className}>
      {groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("timelineEmpty")}</p>
      ) : (
        <div className="flex flex-col gap-4">
          {groups.map((group) => (
            <div key={group.key}>
              <Eyebrow as="h3" tone="muted" className={cn(group.late && TONE_TEXT.danger)}>
                {group.label}
              </Eyebrow>
              <ul className="mt-1 divide-y divide-border/50">
                {group.events.map((event) => (
                  <li key={`${event.tournament_id}:${event.status}:${event.edge}`}>
                    <TimelineRow event={event} card={cardOf.get(event.tournament_id)} />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </Block>
  );
}

/** Time, what happens, whose; the relative time at the end, the absolute date in its `title`. */
function TimelineRow({
  event,
  card
}: Readonly<{ event: DashboardTimelineEvent; card: DashboardTournamentCard | undefined }>) {
  const t = useTranslations("adminShell.dashboard");
  const tStatus = useTranslations("common.statusBadge");
  const format = useFormatter();
  const phase = tStatus(event.status as TournamentStatus);
  return (
    // Bleeds to the card edge so the hover fill spans the card.
    <HoverPrefetchLink
      href={`/admin/tournaments/${event.tournament_id}/settings/schedule`}
      className="-mx-6 grid grid-cols-[4.5rem_minmax(0,1fr)_auto] items-baseline gap-x-3 px-6 py-2 transition-colors hover:bg-accent/30 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
    >
      <time dateTime={event.at} className="whitespace-nowrap text-sm tabular-nums text-foreground">
        {format.dateTime(new Date(event.at), { hour: "2-digit", minute: "2-digit" })}
      </time>
      <span className="grid min-w-0 gap-x-3 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)] sm:items-baseline">
        <span className={cn("text-sm font-medium sm:truncate", event.overdue ? TONE_TEXT.danger : "text-foreground")}>
          {event.overdue
            ? t("edgeOverdue", { phase })
            : t(event.edge === "start" ? "edgeStart" : "edgeEnd", { phase })}
        </span>
        <span className="flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
          {card ? <GameIcon slug={card.discipline} /> : null}
          <span className="truncate" title={event.tournament_name}>
            {event.tournament_name}
          </span>
          {card?.is_hidden ? (
            <StatusPill tone="neutral" className="shrink-0">
              {t("hidden")}
            </StatusPill>
          ) : null}
        </span>
      </span>
      <span className="text-xs tabular-nums text-muted-foreground" title={formatDate(format, event.at)}>
        {formatRelative(format, event.at)}
      </span>
    </HoverPrefetchLink>
  );
}
