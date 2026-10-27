import { Calendar, Clock, Shield, Users, type LucideIcon } from "lucide-react";

import { formatDateRange, type Formatter } from "@/lib/datetime";
import { reachedAtLeast } from "@/lib/tournament/lifecycle";
import type { StageProgress, Translate } from "@/lib/tournament/stage-progress";
import type { Tournament } from "@/types/tournament.types";

/**
 * Frosted glass under a chip that sits on a picture. A status pill's own tint
 * is translucent, and over artwork we do not control it needs a surface that
 * reads on any of it.
 */
export const GLASS_CLASS =
  "flex rounded-md bg-[color:color-mix(in_srgb,var(--aqt-bg)_62%,transparent)] shadow-[inset_0_1px_0_var(--aqt-overlay-3)] backdrop-blur-md backdrop-saturate-150";

type FactKind = "dates" | "countdown" | "players" | "teams" | "registrations";

export interface TournamentFact {
  kind: FactKind;
  text: string;
  /** The instant a dated fact is about, for `<time>`. */
  dateTime?: string;
  /** The absolute date behind a relative one. */
  title?: string;
}

const FACT_ICON: Record<FactKind, LucideIcon> = {
  dates: Calendar,
  countdown: Clock,
  players: Users,
  teams: Shield,
  registrations: Users
};

// Tournament days are stored as UTC midnights, so they are read in UTC (see
// `formatDateRange`).
const DAY = { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" } as const;
const LONG_DAY = { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" } as const;

/**
 * What a tournament is besides its name, fact by fact. Before play: its start
 * date, how far off that is, and its applications. From play on: its dates,
 * players and teams. A count the read did not carry (`null`) is left out
 * rather than shown as zero; the countdown waits for `now` (a client knows it
 * only after hydration) and drops once the start has passed.
 */
export function tournamentFacts(
  tournament: Pick<
    Tournament,
    "status" | "start_date" | "end_date" | "participants_count" | "teams_count" | "registrations_count"
  >,
  t: Translate,
  format: Formatter,
  now: number | null
): TournamentFact[] {
  const start = new Date(tournament.start_date);
  const dateTime = start.toISOString();

  if (!reachedAtLeast(tournament.status, "live")) {
    const facts: TournamentFact[] = [{ kind: "dates", text: format.dateTime(start, DAY), dateTime }];
    if (now !== null && start.getTime() > now) {
      facts.push({
        kind: "countdown",
        text: format.relativeTime(start, now),
        dateTime,
        title: format.dateTime(start, LONG_DAY)
      });
    }
    if (tournament.registrations_count !== null) {
      facts.push({
        kind: "registrations",
        text: t("workspace.applications", { count: tournament.registrations_count })
      });
    }
    return facts;
  }

  const facts: TournamentFact[] = [
    { kind: "dates", text: formatDateRange(format, start, tournament.end_date), dateTime }
  ];
  if (tournament.participants_count !== null) {
    facts.push({
      kind: "players",
      text: t("tournamentsList.card.playersCount", { count: tournament.participants_count })
    });
  }
  if (tournament.teams_count !== null) {
    facts.push({ kind: "teams", text: t("tournamentsList.card.teamsCount", { count: tournament.teams_count }) });
  }
  return facts;
}

/** One fact after its icon. */
export function IconFact({ fact }: Readonly<{ fact: TournamentFact }>) {
  const Icon = FACT_ICON[fact.kind];
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <Icon aria-hidden className="size-[15px] shrink-0 text-[color:var(--aqt-fg-dim)]" />
      {fact.dateTime ? (
        <time dateTime={fact.dateTime} title={fact.title} className="truncate">
          {fact.text}
        </time>
      ) : (
        <span className="truncate">{fact.text}</span>
      )}
    </span>
  );
}

/** A tournament's facts as one wrapping line. */
export function FactsRow({ facts }: Readonly<{ facts: readonly TournamentFact[] }>) {
  return (
    <span className="flex max-w-full flex-wrap items-center gap-x-4 gap-y-1.5 text-body text-[color:var(--aqt-fg-muted)]">
      {facts.map((fact) => (
        <IconFact key={fact.kind} fact={fact} />
      ))}
    </span>
  );
}

/**
 * A running tournament's stage: its name, then a glowing bar of how far
 * through its stages it is. The bar only pictures the label's news
 * (`stageProgress` is a coarse proxy, not a figure to read out), so it is
 * hidden from assistive tech.
 */
export function StageBar({ stage }: Readonly<{ stage: StageProgress }>) {
  return (
    <span className="flex max-w-full items-center gap-3 text-body text-[color:var(--aqt-fg-muted)]">
      <span className="truncate">{stage.label}</span>
      <span
        aria-hidden
        className="h-1 w-36 shrink-0 rounded-full bg-[color:color-mix(in_srgb,var(--aqt-fg)_14%,transparent)] sm:w-44"
      >
        <span
          className="aqt-bar-grow block h-full rounded-full bg-gradient-to-r from-[color:var(--aqt-teal-deep)] to-[color:var(--aqt-teal)] shadow-[0_0_12px_color-mix(in_srgb,var(--aqt-teal)_70%,transparent)]"
          style={{ width: `${stage.pct}%` }}
        />
      </span>
    </span>
  );
}
