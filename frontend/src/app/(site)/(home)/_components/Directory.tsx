import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Plus } from "lucide-react";

import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { TrustedBadge } from "@/components/workspace/TrustedBadge";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import { Fact, OpenLoadError, Section, SectionHead } from "@/components/site/open-layout";
import { Skeleton } from "@/components/ui/skeleton";
import { getFormatter } from "@/lib/datetime/server";
import { getActiveTournaments, getPublicWorkspaces } from "@/lib/site/public-data";
import { getTournamentStatusMeta, isTournamentStatusActive } from "@/lib/tournament/status";
import { cn } from "@/lib/utils";
import statisticsService from "@/services/statistics.service";
import type { Tournament } from "@/types/tournament.types";
import type { WorkspaceListItem } from "@/types/workspace.types";

import { DirectoryRail } from "./DirectoryRail";

const TITLE_ID = "home-directory-title";

/** A slide: the card's top rule turns teal on hover (DESIGN §5, a whole-card link). */
const CARD_CLASS =
  "flex min-h-full flex-col gap-3 border-t border-[color:var(--aqt-border-3)] pt-5 transition-colors duration-150 hover:border-t-[color:var(--aqt-teal)] focus-visible:outline-offset-[-2px]";

/** Every slide snaps to the rail's start and a swipe stops on each one. */
const SLIDE_CLASS = "min-w-0 snap-start [scroll-snap-stop:always]";

interface DirectoryEntry {
  workspace: WorkspaceListItem;
  /** What this community has running right now, if anything. */
  active: Tournament | null;
  tournaments: number | null;
  players: number | null;
}

async function loadDirectory(): Promise<DirectoryEntry[]> {
  const [workspaces, activePage] = await Promise.all([
    getPublicWorkspaces(),
    getActiveTournaments()
  ]);
  const active = activePage.results.filter((tournament) =>
    isTournamentStatusActive(tournament.status)
  );

  const entries = await Promise.all(
    workspaces.map(async (workspace): Promise<DirectoryEntry> => {
      const mine = active.filter((tournament) => tournament.workspace_id === workspace.id);
      // ponytail: one statistics read per community (edge-cached, 60s) because
      // the directory read has no per-community totals. Fine for a few dozen
      // communities; past that, put the totals on the directory read.
      const totals = await statisticsService
        .getOverallStatistics({ workspaceId: workspace.id })
        .catch(() => null);
      return {
        workspace,
        active:
          mine.find(
            (tournament) => getTournamentStatusMeta(tournament.status).variant === "live"
          ) ??
          mine[0] ??
          null,
        tournaments: totals?.tournaments ?? null,
        players: totals?.players ?? null
      };
    })
  );

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
      <div className="flex min-w-0 items-center gap-3">
        <WorkspaceAvatar workspace={workspace} size={44} />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5 font-display text-heading font-semibold leading-[1.2]">
            <span className="min-w-0 truncate">{workspace.name}</span>
            <TrustedBadge status={workspace.verification_status} />
          </div>
          {host ? (
            <div className="mt-0.5 truncate text-caption text-[color:var(--aqt-fg-dim)]">{host}</div>
          ) : null}
        </div>
      </div>

      {active && variant ? (
        <div>
          <TournamentStatusPill status={variant}>
            {variant === "live" ? t("live") : statusLabel(active.status)}
          </TournamentStatusPill>
        </div>
      ) : null}

      {workspace.description ? (
        <p className="line-clamp-2 text-body leading-relaxed text-[color:var(--aqt-fg-muted)]">
          {workspace.description}
        </p>
      ) : null}

      <div className="mt-auto flex flex-wrap items-end gap-x-6 gap-y-3 pt-3">
        {entry.tournaments === null ? null : (
          <Fact
            value={format.number(entry.tournaments)}
            label={t("tournamentsLabel", { count: entry.tournaments })}
          />
        )}
        {entry.players === null ? null : (
          <Fact
            value={format.number(entry.players)}
            label={t("playersLabel", { count: entry.players })}
          />
        )}
      </div>
    </Link>
  );
}

/** The rail's last slide: the organizer page, drawn as the place a new community takes. */
async function JoinCard() {
  const t = await getTranslations("home.directory.cta");

  return (
    <Link href="/get-workspace" prefetch={false} className={cn(CARD_CLASS, "border-dashed")}>
      <div className="flex min-w-0 items-center gap-3">
        <span
          aria-hidden
          className="grid size-11 shrink-0 place-items-center rounded-[11px] border border-dashed border-[color:var(--aqt-border-3)] text-[color:var(--aqt-teal)] [&_svg]:size-5"
        >
          <Plus />
        </span>
        <b className="min-w-0 font-display text-heading font-semibold leading-[1.2] text-[color:var(--aqt-fg)]">
          {t("title")}
        </b>
      </div>
      <p className="text-body leading-relaxed text-[color:var(--aqt-fg-muted)]">{t("text")}</p>
    </Link>
  );
}

/** Three slides of the rail's grid, same rules, same hairlines. */
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
              className="flex min-w-0 flex-col gap-3 border-t border-[color:var(--aqt-border-3)] pt-5"
            >
              <div className="flex items-center gap-3">
                <Skeleton className="size-11 rounded-[11px]" />
                <div className="flex-1">
                  <Skeleton className="h-5 w-32" />
                  <Skeleton className="mt-1.5 h-3.5 w-24" />
                </div>
              </div>
              <Skeleton className="h-10 w-full" />
              <div className="flex gap-6 pt-3">
                <Skeleton className="h-9 w-16" />
                <Skeleton className="h-9 w-16" />
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
