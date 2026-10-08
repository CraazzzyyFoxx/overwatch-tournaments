import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { TournamentStatusPill } from "@/components/tournaments/StatusPill";
import { TrustedBadge } from "@/components/workspace/TrustedBadge";
import { WorkspaceAvatar } from "@/components/workspace/WorkspaceAvatar";
import {
  EYEBROW_CLASS,
  Fact,
  LoadError,
  SECTION_TITLE_CLASS,
  Section
} from "@/components/site/open-layout";
import { Skeleton } from "@/components/ui/skeleton";
import { getFormatter } from "@/lib/datetime/server";
import { getTournamentStatusMeta, isTournamentStatusActive } from "@/lib/tournament/status";
import statisticsService from "@/services/statistics.service";
import type { Tournament } from "@/types/tournament.types";
import type { Workspace } from "@/types/workspace.types";

import { DirectoryRail } from "./DirectoryRail";
import { getActiveTournaments, getPublicWorkspaces } from "./home-data";

const TITLE_ID = "home-directory-title";

interface DirectoryEntry {
  workspace: Workspace;
  /** What this community has running right now, if anything. */
  active: Tournament | null;
  tournaments: number | null;
  players: number | null;
}

async function loadDirectory(): Promise<DirectoryEntry[]> {
  const [workspaces, activePage] = await Promise.all([getPublicWorkspaces(), getActiveTournaments()]);
  const active = activePage.results.filter((tournament) =>
    isTournamentStatusActive(tournament.status)
  );

  const entries = await Promise.all(
    workspaces.map(async (workspace): Promise<DirectoryEntry> => {
      const mine = active.filter((tournament) => tournament.workspace_id === workspace.id);
      // A community's own totals: there is no per-workspace column on the
      // directory read, so each card asks for its numbers (edge-cached, 60s).
      const totals = await statisticsService
        .getOverallStatistics({ workspaceId: workspace.id })
        .catch(() => null);
      return {
        workspace,
        active:
          mine.find((tournament) => getTournamentStatusMeta(tournament.status).variant === "live") ??
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

/** Every public community, newest activity first — the platform's catalogue. */
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
        <DirectoryHead />
        <LoadError what={t("error")} dashed />
      </Section>
    );
  }

  return (
    <Section id="directory" labelledBy={TITLE_ID}>
      <DirectoryRail titleId={TITLE_ID}>
        {entries.map((entry) => (
          <li key={entry.workspace.id} className="min-w-0 snap-start [scroll-snap-stop:always]">
            <CommunityCard entry={entry} />
          </li>
        ))}
      </DirectoryRail>
    </Section>
  );
}

/** The head without the rail controls — the error state has nothing to steer. */
async function DirectoryHead() {
  const t = await getTranslations("home.directory");
  return (
    <div className="mb-4">
      <span className={`${EYEBROW_CLASS} mb-1.5 block`}>{t("rubric")}</span>
      <h2 id={TITLE_ID} className={SECTION_TITLE_CLASS}>
        {t("title")}
      </h2>
      <p className="mt-1.5 text-body text-[color:var(--aqt-fg-dim)]">{t("sub")}</p>
    </div>
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
    <Link
      href={`/workspace/${workspace.slug}`}
      prefetch={false}
      className="flex min-h-full flex-col gap-3 border-t border-[color:var(--aqt-border-3)] pt-4 transition-colors duration-150 hover:border-t-[color:var(--aqt-teal)] focus-visible:outline-offset-[-2px]"
    >
      <div className="flex min-w-0 items-start gap-3">
        <WorkspaceAvatar workspace={workspace} size={44} />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5 font-display text-heading font-bold leading-[1.2]">
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
        <p className="line-clamp-2 text-body text-[color:var(--aqt-fg-muted)]">
          {workspace.description}
        </p>
      ) : null}

      <div className="mt-auto flex flex-wrap items-end gap-x-[22px] gap-y-2.5 pt-1">
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

/** Three card shapes on the rail's grid, same rules, same hairlines. */
export function DirectorySkeleton() {
  return (
    <Section id="directory" labelledBy={TITLE_ID}>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div>
          <Skeleton className="h-3 w-16" />
          <Skeleton className="mt-2 h-7 w-52" />
          <Skeleton className="mt-2 h-4 w-72" />
        </div>
        <Skeleton className="h-9 w-[120px]" />
      </div>
      <ul className="grid auto-cols-[100%] grid-flow-col gap-8 overflow-hidden min-[640px]:auto-cols-[calc((100%-32px)/2)] min-[1100px]:auto-cols-[calc((100%-2*32px)/3)]">
        {Array.from({ length: 3 }).map((_, index) => (
          <li
            key={index}
            className="flex min-w-0 flex-col gap-3 border-t border-[color:var(--aqt-border-3)] pt-4"
          >
            <div className="flex items-start gap-3">
              <Skeleton className="size-11 rounded-[11px]" />
              <div className="flex-1">
                <Skeleton className="h-5 w-32" />
                <Skeleton className="mt-1.5 h-3.5 w-24" />
              </div>
            </div>
            <Skeleton className="h-10 w-full" />
            <div className="flex gap-[22px] pt-1">
              <Skeleton className="h-9 w-16" />
              <Skeleton className="h-9 w-16" />
            </div>
          </li>
        ))}
      </ul>
    </Section>
  );
}
