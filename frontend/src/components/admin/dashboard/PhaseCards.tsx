"use client";

import { useState } from "react";
import { useNow, useTranslations } from "next-intl";
import { AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, Circle, Clock, Lock } from "lucide-react";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { buildChecklist, type ChecklistItem } from "@/components/admin/tournament-checklist";
import { formatDate, formatRelative } from "@/components/kit/format-time";
import { FactList } from "@/components/kit/FactList";
import { PhaseStrip, type Phase } from "@/components/kit/PhaseStrip";
import { StatusPill } from "@/components/kit/StatusPill";
import { TONE_TEXT, type Tone } from "@/components/ui/tone";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import Image from "@/components/ui/image";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusDot } from "@/components/ui/status-dot";
import { GameIcon } from "@/components/workspace/GameIcon";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import type { DashboardTournamentCard } from "@/types/admin-dashboard.types";
import type { TournamentStatus } from "@/types/tournament.types";

/** Cards shown before the rest fold into "N more", in the backend's priority order. */
const VISIBLE_CARDS = 3;
/** Open checklist items a card lists before pointing at the hub's full checklist. */
const MAX_CHECKLIST_ITEMS = 3;
/** The card phases in lifecycle order: the strip under a card's title marks where it stands. */
const PHASES = ["preparation", "registration", "formation", "live", "wrap_up"] as const;

/** As many columns as fit at 20rem: a lone card takes the whole column, three share it. */
const GRID_CLASS = "grid grid-cols-[repeat(auto-fit,minmax(min(100%,20rem),1fr))] gap-4";

export function PhaseCards({ cards }: Readonly<{ cards: DashboardTournamentCard[] }>) {
  const t = useTranslations("adminShell.dashboard");
  const [open, setOpen] = useState(false);
  const rest = cards.slice(VISIBLE_CARDS);

  return (
    <section aria-labelledby="dashboard-cards" className="flex flex-col gap-3">
      <h2 id="dashboard-cards" className="sr-only">
        {t("cardsTitle")}
      </h2>
      <div className={GRID_CLASS}>
        {cards.slice(0, VISIBLE_CARDS).map((card) => (
          <PhaseCard key={card.id} card={card} />
        ))}
      </div>
      {rest.length > 0 ? (
        <Collapsible open={open} onOpenChange={setOpen} className="flex flex-col gap-3">
          <CollapsibleContent className={GRID_CLASS}>
            {rest.map((card) => (
              <PhaseCard key={card.id} card={card} />
            ))}
          </CollapsibleContent>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="w-fit text-muted-foreground">
              {open ? t("fewerCards") : t("moreCards", { count: rest.length })}
              <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} aria-hidden />
            </Button>
          </CollapsibleTrigger>
        </Collapsible>
      ) : null}
    </section>
  );
}

/** One placeholder: a workspace mostly runs one tournament at a time, and a lone card takes the whole column. */
export function PhaseCardsSkeleton() {
  return <Skeleton className="h-56 rounded-xl" />;
}

/**
 * One tournament in work. Wide enough (a lone card), it splits into its
 * identity (cover, logo, phase, title, lifecycle, deadline, the way in) and
 * the phase's own body; narrower, the two stack. The split follows the card's
 * width, not the page's: the grid decides how wide a card is.
 */
function PhaseCard({ card }: Readonly<{ card: DashboardTournamentCard }>) {
  const t = useTranslations("adminShell.dashboard");
  const tStatus = useTranslations("common.statusBadge");
  const format = useFormatter();
  const base = `/admin/tournaments/${card.id}`;
  const status = tStatus(card.status as TournamentStatus);
  const phaseName = t(`phase.${card.phase}`);
  // Formation and live each span two statuses; the status says which one,
  // unless its label already is the phase's own name.
  const phaseLine =
    (card.phase === "formation" || card.phase === "live") && status !== phaseName
      ? `${phaseName} · ${status}`
      : phaseName;
  // The one way in: the existing screen where this phase's work is done.
  const actionHref = {
    preparation: `${base}/settings/general`,
    registration: `${base}/registration/entries`,
    formation: card.team_formation === "draft" ? `${base}/teams/draft` : `${base}/teams/roster`,
    live: `${base}/matches/encounters`,
    wrap_up: `${base}/overview`
  }[card.phase];
  const current = PHASES.findIndex((phase) => phase === card.phase);

  return (
    <Card className="@container flex flex-col overflow-hidden">
      {card.cover_image_url ? (
        <div className="relative h-24 shrink-0 bg-[color:var(--aqt-bg-2)]">
          <Image
            src={card.cover_image_url}
            alt=""
            aria-hidden
            fill
            sizes="(max-width: 1280px) 100vw, 70vw"
            className="object-cover"
          />
        </div>
      ) : null}
      {/* Stacked, a taller neighbour's slack goes under the body, not between the action and the body. */}
      <div className="grid flex-1 grid-rows-[auto_1fr] @3xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] @3xl:grid-rows-1">
        <div className="flex min-w-0 flex-col gap-4 p-6">
          <div className="flex min-w-0 items-start gap-3">
            {card.logo_url ? (
              <Image
                src={card.logo_url}
                alt=""
                aria-hidden
                width={48}
                height={48}
                // Rides the cover's lower edge; `relative` paints it over the positioned cover.
                className={cn(
                  "relative size-12 shrink-0 rounded-lg border border-border bg-background object-cover",
                  card.cover_image_url && "-mt-12"
                )}
              />
            ) : null}
            <div className="min-w-0 flex-1 space-y-1">
              <p className={eyebrowClass("muted")}>{phaseLine}</p>
              {/* `items-start`: a two-line title keeps its game mark and pill on its first line. */}
              <div className="flex min-w-0 items-start gap-2">
                <span className="mt-1 flex shrink-0">
                  <GameIcon slug={card.discipline} size={16} />
                </span>
                <h3 title={card.name} className="line-clamp-2 min-w-0 break-words font-display text-title font-semibold">
                  <HoverPrefetchLink href={base} className="hover:underline focus-visible:underline">
                    {card.name}
                  </HoverPrefetchLink>
                </h3>
                {card.is_hidden ? (
                  <StatusPill tone="neutral" className="mt-0.5 shrink-0">
                    {t("hidden")}
                  </StatusPill>
                ) : null}
              </div>
            </div>
          </div>
          <PhaseStrip
            variant="compact"
            phases={PHASES.map(
              (phase, index): Phase => ({
                key: phase,
                label: t(`phase.${phase}`),
                state: index < current ? "done" : index === current ? "current" : "todo"
              })
            )}
          />
          {card.next_deadline_at ? (
            <p
              className="flex items-center gap-1.5 text-sm text-foreground"
              title={formatDate(format, card.next_deadline_at)}
            >
              <Clock className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              {t("nextDeadline", { when: formatRelative(format, card.next_deadline_at) })}
            </p>
          ) : null}
          <Button asChild variant="outline" size="sm" className="mt-auto w-fit">
            <HoverPrefetchLink href={actionHref}>
              {t(`action.${card.phase}`)}
              <ArrowRight className="size-3.5" aria-hidden />
            </HoverPrefetchLink>
          </Button>
        </div>
        {/* Its own container: the facts inside fit their columns to this zone, not to the card. */}
        <div className="@container min-w-0 border-t border-border/50 p-6 @3xl:border-l @3xl:border-t-0">
          {card.phase === "registration" ? (
            <RegistrationBody card={card} />
          ) : card.phase === "live" ? (
            <PlayBody card={card} />
          ) : card.phase === "wrap_up" ? (
            <WrapUpBody card={card} />
          ) : (
            <ChecklistBody card={card} />
          )}
        </div>
      </div>
    </Card>
  );
}

function NoAccess() {
  const tCommon = useTranslations("common");
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <Lock className="size-3.5 shrink-0" aria-hidden />
      {tCommon("noAccess")}
    </p>
  );
}

/**
 * Preparation and formation: the hub's own living checklist, open items only.
 * `buildChecklist` already drops what the card's status no longer needs, so a
 * formation card never nags "registration form" after registration closed.
 */
function ChecklistBody({ card }: Readonly<{ card: DashboardTournamentCard }>) {
  const t = useTranslations("adminShell.dashboard");
  const tChecklist = useTranslations("adminTournaments.checklist");
  const items = buildChecklist(
    card.readiness,
    {
      basePath: `/admin/tournaments/${card.id}`,
      status: card.status as TournamentStatus,
      hasChallongeSource: card.has_challonge_source
    },
    tChecklist
  );
  // Masked groups come back as "no-access" items: neither work nor progress.
  if (items.every((item) => item.state === "no-access" || item.state === "skipped")) return <NoAccess />;
  const open = items.filter((item) => item.state === "todo" || item.state === "warn");
  if (open.length === 0) {
    return (
      <p className={cn("flex items-center gap-2 text-sm", TONE_TEXT.success)}>
        <CheckCircle2 className="size-4 shrink-0" aria-hidden />
        {t("everyStepDone")}
      </p>
    );
  }
  return (
    <ul className="divide-y divide-border/50">
      {open.slice(0, MAX_CHECKLIST_ITEMS).map((item) => (
        <li key={item.key}>
          <ChecklistRow item={item} progress={rowProgress(item.key, card.readiness)} />
        </li>
      ))}
      {open.length > MAX_CHECKLIST_ITEMS ? (
        <li className="pt-2 text-xs text-muted-foreground">
          {t("moreInChecklist", { count: open.length - MAX_CHECKLIST_ITEMS })}
        </li>
      ) : null}
    </ul>
  );
}

/** How far a row that counts toward a whole has got, in percent; `null` for a plain step. */
function rowProgress(key: string, readiness: DashboardTournamentCard["readiness"]): number | null {
  const [done, total] =
    key === "ranks"
      ? [readiness.registrations_ranked, readiness.registrations_approved]
      : key === "pool_ready"
        ? [readiness.pool_ready, (readiness.pool_ready ?? 0) + (readiness.pool_need_fix ?? 0)]
        : [null, null];
  return done == null || !total ? null : Math.min(100, (done / total) * 100);
}

function ChecklistRow({ item, progress }: Readonly<{ item: ChecklistItem; progress: number | null }>) {
  const warn = item.state === "warn";
  const Icon = warn ? AlertTriangle : Circle;
  const body = (
    <>
      <Icon className={cn("mt-0.5 size-3.5 shrink-0", TONE_TEXT[warn ? "warning" : "neutral"])} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="min-w-0 flex-1 truncate text-sm text-foreground">{item.label}</span>
          {item.detail ? (
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{item.detail}</span>
          ) : null}
        </div>
        {/* The detail prints the count; the bar only shows how far along it is. */}
        {progress == null ? null : <Progress value={progress} aria-hidden size="sm" className="mt-2" />}
      </div>
    </>
  );
  // Bleeds to the card edge so the hover fill spans the card.
  const shared = "-mx-6 flex items-start gap-2 px-6 py-2";
  if (!item.href) return <div className={shared}>{body}</div>;
  return (
    <HoverPrefetchLink
      href={item.href}
      className={cn(
        shared,
        "transition-colors hover:bg-accent/30 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      )}
    >
      {body}
    </HoverPrefetchLink>
  );
}

/** A count toward a whole: label and exact value over a bar (DESIGN §8, leader-scaled bar). */
function Meter({ label, value, total }: Readonly<{ label: string; value: number; total: number }>) {
  const t = useTranslations("adminShell.dashboard");
  const text = t("playProgress", { completed: value, total });
  return (
    <div className="flex flex-col gap-1.5">
      {/* Read once, as the bar's own name and value. */}
      <div aria-hidden className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="tabular-nums text-foreground">{text}</span>
      </div>
      <Progress
        value={total > 0 ? Math.min(100, (value / total) * 100) : 0}
        aria-label={label}
        getValueLabel={() => text}
        size="sm"
      />
    </div>
  );
}

/** The funnel: pending and approved, then how much of the approved is ranked and checked in; the pace and the deadline. */
function RegistrationBody({ card }: Readonly<{ card: DashboardTournamentCard }>) {
  const t = useTranslations("adminShell.dashboard");
  const format = useFormatter();
  const readiness = card.readiness;
  const approved = readiness.registrations_approved;
  const closesAt = card.registration_closes_at;
  const now = useNow();
  const closed = closesAt != null && new Date(closesAt).getTime() < now.getTime();
  return (
    <div className="flex flex-col gap-4">
      {/* `registrations_approved` is the team.read sentinel: null masks the whole group. */}
      {approved == null ? (
        <NoAccess />
      ) : (
        <>
          <FactList
            facts={[
              {
                label: t("pending"),
                value: readiness.registrations_pending,
                tone: readiness.registrations_pending ? "warning" : undefined
              },
              { label: t("approved"), value: approved }
            ]}
          />
          <Meter label={t("ranked")} value={readiness.registrations_ranked ?? 0} total={approved} />
          <Meter label={t("checkedIn")} value={readiness.registrations_checked_in ?? 0} total={approved} />
        </>
      )}
      <ul className="space-y-1 text-xs text-muted-foreground">
        {card.registrations_last_24h != null ? (
          <li className="tabular-nums">{t("registrationsLast24h", { count: card.registrations_last_24h })}</li>
        ) : null}
        {closesAt ? (
          <li className={cn(closed && TONE_TEXT.warning)}>
            {t(closed ? "registrationOverdue" : "registrationCloses", { when: formatRelative(format, closesAt) })}
          </li>
        ) : null}
      </ul>
    </div>
  );
}

/** Played against scheduled, then what is running, late or contested. */
function PlayBody({ card }: Readonly<{ card: DashboardTournamentCard }>) {
  const t = useTranslations("adminShell.dashboard");
  const play = card.play;
  if (!play) return <NoAccess />;
  return (
    <div className="flex flex-col gap-4">
      <Meter label={t("play.completed")} value={play.encounters_completed} total={play.encounters_total} />
      <FactList
        className="grid grid-cols-2 gap-x-4 gap-y-3 @md:grid-cols-4"
        facts={[
          {
            label: t("play.live"),
            // The one loop DESIGN §10 allows: something is being played right now.
            value:
              play.encounters_live > 0 ? (
                <span className="inline-flex items-center gap-1.5">
                  <StatusDot tone="danger" pulse className="size-2" />
                  {play.encounters_live}
                </span>
              ) : (
                play.encounters_live
              )
          },
          {
            label: t("play.overdue"),
            value: play.encounters_overdue,
            tone: play.encounters_overdue ? "danger" : undefined
          },
          {
            label: t("play.pendingConfirmation"),
            value: play.encounters_pending_confirmation,
            tone: play.encounters_pending_confirmation ? "warning" : undefined
          },
          {
            label: t("play.disputed"),
            value: play.encounters_disputed,
            tone: play.encounters_disputed ? "danger" : undefined
          }
        ]}
      />
    </div>
  );
}

/** The four wrap-up conditions; a masked one says so instead of passing for done. */
function WrapUpBody({ card }: Readonly<{ card: DashboardTournamentCard }>) {
  const t = useTranslations("adminShell.dashboard");
  const wrapUp = card.wrap_up;
  if (!wrapUp) return null;

  const resultsOpen = wrapUp.results_open;
  const withLogs = wrapUp.duel_encounters_with_logs ?? 0;
  const duels = wrapUp.duel_encounters_total ?? 0;
  const achievements = wrapUp.achievements_status;
  const recalc = wrapUp.standings_recalc_pending;
  // `done: null` is a condition the reader may not see.
  const conditions: { key: string; label: string; done: boolean | null; text: string }[] = [
    {
      key: "results",
      label: t("wrapUp.results"),
      done: resultsOpen == null ? null : resultsOpen === 0,
      text: resultsOpen ? t("wrapUp.resultsOpen", { count: resultsOpen }) : t("wrapUp.resultsDone")
    },
    {
      key: "logs",
      label: t("wrapUp.logs"),
      done: wrapUp.logs_used == null ? null : !wrapUp.logs_used || withLogs >= duels,
      text: !wrapUp.logs_used
        ? t("wrapUp.logsNotUsed")
        : withLogs >= duels
          ? t("wrapUp.logsDone")
          : t("wrapUp.logsOpen", { withLogs, total: duels })
    },
    {
      key: "achievements",
      label: t("wrapUp.achievements"),
      done: achievements == null ? null : achievements === "done" || achievements === "not_configured",
      text:
        achievements === "not_configured"
          ? t("wrapUp.achievementsNotConfigured")
          : achievements === "done"
            ? t("wrapUp.achievementsDone")
            : t("wrapUp.achievementsOpen")
    },
    {
      key: "standings",
      label: t("wrapUp.standings"),
      done: recalc == null ? null : !recalc,
      text: recalc ? t("wrapUp.standingsOpen") : t("wrapUp.standingsDone")
    }
  ];

  return (
    <ul className="space-y-2">
      {conditions.map((condition) => {
        const Icon = condition.done == null ? Lock : condition.done ? CheckCircle2 : Circle;
        const tone: Tone = condition.done == null ? "neutral" : condition.done ? "success" : "warning";
        return (
          <li key={condition.key} className="flex items-start gap-2 text-sm">
            <Icon className={cn("mt-0.5 size-3.5 shrink-0", TONE_TEXT[tone])} aria-hidden />
            <span className={cn(condition.done == null && "text-muted-foreground")}>
              {condition.done == null ? t("wrapUp.restricted", { label: condition.label }) : condition.text}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
