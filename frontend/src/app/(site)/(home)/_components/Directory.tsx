import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { ArrowRight, Plus, Trophy, Users, type LucideIcon } from "lucide-react";

import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { TrustedBadge } from "@/components/workspace/TrustedBadge";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { OpenLoadError, Section, SectionHead } from "@/components/site/open-layout";
import { Skeleton } from "@/components/ui/skeleton";
import type { Formatter } from "@/lib/datetime";
import { getFormatter } from "@/lib/datetime/server";
import { getActiveTournaments, getPublicCommunities, type PublicCommunity } from "@/lib/site/public-data";
import { getTournamentStatusMeta } from "@/lib/tournament/status";
import { cn } from "@/lib/utils";
import type { Tournament } from "@/types/tournament.types";

import { DirectoryRail } from "./DirectoryRail";
import { FEATURED_GLOW } from "./NowOnPlatform";
import { NumbersReveal } from "./NumbersReveal";

const TITLE_ID = "home-directory-title";

/**
 * A slide: the bento's framed tile on its faint radial lift, one whole-card link whose frame turns teal and glows
 * under the pointer or focus (DESIGN §5 game polish). `h-full`: the rail's grid stretches each slide to its row, so
 * the cards of a row share one height. The focus ring is inset, as the rail is a scroller and clips an outset one.
 */
const CARD_CLASS = cn(
  "group relative flex h-full flex-col overflow-hidden rounded-[var(--aqt-radius)] border border-[color:var(--aqt-border)] bg-[radial-gradient(130%_120%_at_0%_0%,var(--aqt-card-2),var(--aqt-card)_62%)] shadow-[inset_0_1px_0_var(--aqt-overlay-3)] transition-[border-color,box-shadow] duration-300 focus-visible:outline-offset-[-2px]",
  FEATURED_GLOW
);

/**
 * The logo leads the card (communities have no banner of their own): a faint ring and a soft teal glow lift it off
 * the tile.
 */
const LOGO_CLASS =
  "shadow-[0_0_0_1px_var(--aqt-overlay-border),0_12px_36px_-12px_color-mix(in_srgb,var(--aqt-teal)_55%,transparent)]";

/** Every slide snaps to the rail's start and a swipe stops on each one. */
const SLIDE_CLASS = "min-w-0 snap-start [scroll-snap-stop:always]";

interface DirectoryEntry extends PublicCommunity {
  /** What this community has running right now, if anything. */
  active: Tournament | null;
}

async function loadDirectory(): Promise<DirectoryEntry[]> {
  // Running tournaments only: the read filters by status server-side.
  const [communities, { results: active }] = await Promise.all([
    getPublicCommunities(),
    getActiveTournaments()
  ]);

  const entries = communities.map((community): DirectoryEntry => {
    const mine = active.filter((tournament) => tournament.workspace_id === community.workspace.id);
    const running =
      mine.find((tournament) => getTournamentStatusMeta(tournament.status).variant === "live") ??
      mine[0] ??
      null;
    return { ...community, active: running };
  });

  // Communities with something running come first, then the biggest ones.
  return entries.sort(
    (a, b) =>
      Number(Boolean(b.active)) - Number(Boolean(a.active)) ||
      (b.tournaments ?? 0) - (a.tournaments ?? 0)
  );
}

/**
 * Every public community, newest activity first — the platform's catalogue as
 * a carousel (`DirectoryRail`), closing with the slot a new community fills.
 * `#directory` is the footer's "Communities" link.
 */
export async function Directory() {
  const t = await getTranslations("home.directory");

  let entries: DirectoryEntry[] | null = null;
  try {
    entries = await loadDirectory();
  } catch {
    entries = null;
  }

  if (entries === null) {
    return (
      <Section id="directory" labelledBy={TITLE_ID}>
        <SectionHead title={t("title")} titleId={TITLE_ID} sub={t("sub")} />
        <OpenLoadError what={t("error")} dashed />
      </Section>
    );
  }

  return (
    <Section id="directory" labelledBy={TITLE_ID}>
      <DirectoryRail titleId={TITLE_ID}>
        {entries.map((entry) => (
          <li key={entry.workspace.id} className={SLIDE_CLASS}>
            <CommunityCard entry={entry} />
          </li>
        ))}
        <li className={SLIDE_CLASS}>
          <JoinCard />
        </li>
      </DirectoryRail>
    </Section>
  );
}

async function CommunityCard({ entry }: Readonly<{ entry: DirectoryEntry }>) {
  const [t, statusLabel, format] = await Promise.all([
    getTranslations("home.directory"),
    getTranslations("common.statusBadge"),
    getFormatter()
  ]);
  const { workspace, active } = entry;
  // Only a verified custom domain is an address worth showing; platform
  // subdomains are plumbing.
  const host = workspace.custom_domain_verified_at ? workspace.custom_domain : null;
  const variant = active ? getTournamentStatusMeta(active.status).variant : null;

  return (
    <Link href={`/workspace/${workspace.slug}`} prefetch={false} className={CARD_CLASS}>
      <div className="flex flex-1 flex-col gap-4 p-5">
        <div className="flex items-start justify-between gap-3">
          <WorkspaceAvatar workspace={workspace} size={64} className={LOGO_CLASS} />
          {active && variant ? (
            <TournamentStatusPill status={variant}>
              {variant === "live" ? t("live") : statusLabel(active.status)}
            </TournamentStatusPill>
          ) : null}
        </div>
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-1.5 font-display text-heading font-semibold text-[color:var(--aqt-fg)]">
            <span className="min-w-0 truncate">{workspace.name}</span>
            <TrustedBadge status={workspace.verification_status} />
          </div>
          {host ? (
            <div className="mt-0.5 truncate text-caption text-[color:var(--aqt-fg-dim)]">{host}</div>
          ) : null}
          {active ? (
            <p title={active.name} className="mt-1.5 truncate text-caption text-[color:var(--aqt-fg-muted)]">
              {t(`featured.${variant === "live" ? "live" : "upcoming"}`, { name: active.name })}
            </p>
          ) : null}
        </div>

        {/* One line, the rest in `title`: every card takes the tallest one's height, so a long
            description would open a gap in all the others. */}
        {workspace.description ? (
          <p title={workspace.description} className="truncate text-body text-[color:var(--aqt-fg-muted)]">
            {workspace.description}
          </p>
        ) : null}

        {entry.tournaments === null && entry.players === null ? null : (
          <NumbersReveal className="mt-auto flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-[color:var(--aqt-overlay-border)] pt-4">
            {entry.tournaments === null ? null : (
              <CardFact
                icon={Trophy}
                value={entry.tournaments}
                label={t("tournamentsLabel", { count: entry.tournaments })}
                format={format}
              />
            )}
            {entry.players === null ? null : (
              <CardFact
                icon={Users}
                value={entry.players}
                label={t("playersLabel", { count: entry.players })}
                format={format}
              />
            )}
          </NumbersReveal>
        )}
      </div>
    </Link>
  );
}

/** A fact after its icon: the figure `NumbersReveal` counts up to (`data-count`), then its word. */
function CardFact({
  icon: Icon,
  value,
  label,
  format
}: Readonly<{ icon: LucideIcon; value: number; label: string; format: Formatter }>) {
  return (
    <span className="inline-flex items-center gap-2 text-caption text-[color:var(--aqt-fg-muted)]">
      <Icon aria-hidden className="size-4 shrink-0 text-[color:var(--aqt-teal)]" />
      <b data-count={value} className="font-display text-heading font-bold tabular-nums text-[color:var(--aqt-fg)]">
        {format.number(value)}
      </b>
      {label}
    </span>
  );
}

/** The rail's last slide: the organizer page, drawn as the place a new community takes. */
async function JoinCard() {
  const [t, organizer] = await Promise.all([
    getTranslations("home.directory.cta"),
    getTranslations("home.organizer")
  ]);

  return (
    <Link
      href="/get-workspace"
      prefetch={false}
      className={cn(
        CARD_CLASS,
        "border-dashed border-[color:color-mix(in_srgb,var(--aqt-teal)_40%,transparent)]"
      )}
    >
      <div className="flex flex-1 flex-col gap-4 p-5">
        {/* The logo's place holds a glowing plus: the slot is still empty. */}
        <span
          aria-hidden
          className="grid size-16 place-items-center rounded-2xl border border-dashed border-[color:color-mix(in_srgb,var(--aqt-teal)_55%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_12%,transparent)] text-[color:var(--aqt-teal)] shadow-[0_12px_36px_-12px_color-mix(in_srgb,var(--aqt-teal)_55%,transparent)]"
        >
          <Plus className="size-6" />
        </span>
        <div className="flex flex-col gap-2">
          <b className="font-display text-heading font-semibold text-[color:var(--aqt-fg)]">{t("title")}</b>
          <p className="text-body text-[color:var(--aqt-fg-muted)]">{t("text")}</p>
        </div>
        <span className="mt-auto inline-flex items-center gap-1.5 pt-3 text-body font-semibold text-[color:var(--aqt-teal)]">
          {organizer("cta")}
          <ArrowRight aria-hidden className="size-4" />
        </span>
      </div>
    </Link>
  );
}

/** Three slides of the rail's grid, in the cards' shape. */
export function DirectorySkeleton() {
  return (
    <Section id="directory" labelledBy={TITLE_ID}>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="min-w-0 max-w-full">
          <Skeleton className="h-7 w-52" />
          <Skeleton className="mt-1.5 h-4 w-72 max-w-full" />
        </div>
      </div>
      <div className="md:px-14">
        <ul className="grid auto-cols-[100%] grid-flow-col gap-8 overflow-hidden min-[640px]:auto-cols-[calc((100%-32px)/2)] min-[1100px]:auto-cols-[calc((100%-2*32px)/3)]">
          {Array.from({ length: 3 }).map((_, index) => (
            <li
              key={index}
              className="flex min-w-0 flex-col overflow-hidden rounded-[var(--aqt-radius)] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]"
            >
              <div className="flex flex-col gap-4 p-5">
                <Skeleton className="size-16 rounded-2xl" />
                <div>
                  <Skeleton className="h-5 w-36" />
                  <Skeleton className="mt-1.5 h-4 w-48 max-w-full" />
                </div>
                <Skeleton className="h-5 w-full" />
                <div className="flex gap-6 border-t border-[color:var(--aqt-overlay-border)] pt-4">
                  <Skeleton className="h-6 w-28" />
                  <Skeleton className="h-6 w-24" />
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-3 flex justify-center">
        <Skeleton className="h-11 w-[132px]" />
      </div>
    </Section>
  );
}
